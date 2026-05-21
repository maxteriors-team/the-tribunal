"""Redis-based distributed rate limiting for SMS campaigns."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog

from app.db.redis import get_redis

logger = structlog.get_logger()


# Lua script for atomic token bucket rate limiting
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1]) or capacity
local last_refill = tonumber(bucket[2]) or now

-- Refill tokens based on elapsed time
local elapsed = now - last_refill
tokens = math.min(capacity, tokens + (elapsed * rate))

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 10)
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 10)
    return 0
end
"""

# Lua script for atomic increment with limit check
INCREMENT_WITH_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local expire_seconds = tonumber(ARGV[2])

local current = redis.call('GET', key)
current = tonumber(current) or 0

if current >= limit then
    return {0, current}
end

current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, expire_seconds)
end

return {1, current}
"""


class RateLimiter:
    """Distributed rate limiter using Redis.

    Implements multiple rate limiting strategies:
    - Per-second throttle using token bucket algorithm
    - Hourly limits with auto-expiring keys
    - Daily limits with midnight rollover
    - Campaign-level per-minute sliding window
    """

    def __init__(self) -> None:
        self.logger = logger.bind(component="rate_limiter")
        self._token_bucket_sha: str | None = None
        self._increment_sha: str | None = None

    async def _get_token_bucket_sha(self) -> str:
        """Get or load the token bucket Lua script SHA."""
        if self._token_bucket_sha is None:
            redis_client = await get_redis()
            self._token_bucket_sha = await redis_client.script_load(TOKEN_BUCKET_SCRIPT)
        return self._token_bucket_sha

    async def _get_increment_sha(self) -> str:
        """Get or load the increment Lua script SHA."""
        if self._increment_sha is None:
            redis_client = await get_redis()
            self._increment_sha = await redis_client.script_load(INCREMENT_WITH_LIMIT_SCRIPT)
        return self._increment_sha

    async def check_and_increment_per_second(
        self,
        phone_number_id: uuid.UUID,
        messages_per_second: float,
    ) -> bool:
        """Check if message can be sent based on per-second rate limit.

        Uses token bucket algorithm in Redis for smooth rate limiting.

        Args:
            phone_number_id: Phone number UUID
            messages_per_second: Allowed messages per second

        Returns:
            True if message can be sent, False if rate limited
        """
        redis_client = await get_redis()
        key = f"rate_limit:per_second:{phone_number_id}"

        now = datetime.now(UTC).timestamp()
        # Burst capacity = 5 seconds worth of tokens
        capacity = max(5, int(messages_per_second * 5))

        try:
            sha = await self._get_token_bucket_sha()
            result = await redis_client.evalsha(  # type: ignore[misc]
                sha, 1, key, now, messages_per_second, capacity
            )
        except Exception:
            # Fallback to eval if SHA not found
            result = await redis_client.eval(  # type: ignore[misc]
                TOKEN_BUCKET_SCRIPT, 1, key, now, messages_per_second, capacity
            )

        allowed = bool(int(result))

        if not allowed:
            self.logger.debug(
                "per_second_rate_limit_hit",
                phone_number_id=str(phone_number_id),
                rate=messages_per_second,
            )

        return allowed

    async def check_and_increment_hourly(
        self,
        phone_number_id: uuid.UUID,
        hourly_limit: int,
    ) -> tuple[bool, int]:
        """Check hourly rate limit and increment if allowed.

        Args:
            phone_number_id: Phone number UUID
            hourly_limit: Maximum messages per hour

        Returns:
            Tuple of (allowed, current_count)
        """
        redis_client = await get_redis()

        # Key expires at end of current hour
        now = datetime.now(UTC)
        hour_key = now.strftime("%Y%m%d%H")
        key = f"rate_limit:hourly:{phone_number_id}:{hour_key}"

        try:
            sha = await self._get_increment_sha()
            result = await redis_client.evalsha(sha, 1, key, hourly_limit, 3600)  # type: ignore[misc]
        except Exception:
            result = await redis_client.eval(  # type: ignore[misc]
                INCREMENT_WITH_LIMIT_SCRIPT, 1, key, hourly_limit, 3600
            )

        allowed = bool(int(result[0]))
        current_count = int(result[1])

        if not allowed:
            self.logger.debug(
                "hourly_rate_limit_hit",
                phone_number_id=str(phone_number_id),
                limit=hourly_limit,
                current=current_count,
            )

        return allowed, current_count

    async def check_and_increment_daily(
        self,
        phone_number_id: uuid.UUID,
        daily_limit: int,
    ) -> tuple[bool, int]:
        """Check daily rate limit and increment if allowed.

        Args:
            phone_number_id: Phone number UUID
            daily_limit: Maximum messages per day

        Returns:
            Tuple of (allowed, current_count)
        """
        redis_client = await get_redis()

        # Key expires at end of current day (UTC)
        now = datetime.now(UTC)
        day_key = now.strftime("%Y%m%d")
        key = f"rate_limit:daily:{phone_number_id}:{day_key}"

        # Calculate seconds until midnight
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        expire_seconds = int((midnight - now).total_seconds())

        try:
            sha = await self._get_increment_sha()
            result = await redis_client.evalsha(sha, 1, key, daily_limit, expire_seconds)  # type: ignore[misc]
        except Exception:
            result = await redis_client.eval(  # type: ignore[misc]
                INCREMENT_WITH_LIMIT_SCRIPT, 1, key, daily_limit, expire_seconds
            )

        allowed = bool(int(result[0]))
        current_count = int(result[1])

        if not allowed:
            self.logger.debug(
                "daily_rate_limit_hit",
                phone_number_id=str(phone_number_id),
                limit=daily_limit,
                current=current_count,
            )

        return allowed, current_count

    async def check_and_increment_campaign_daily(
        self,
        campaign_id: uuid.UUID,
        daily_limit: int,
    ) -> tuple[bool, int]:
        """Check campaign daily send cap and increment if allowed."""
        redis_client = await get_redis()
        now = datetime.now(UTC)
        day_key = now.strftime("%Y%m%d")
        key = f"rate_limit:campaign_daily:{campaign_id}:{day_key}"
        midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        expire_seconds = int((midnight - now).total_seconds())

        try:
            sha = await self._get_increment_sha()
            result = await redis_client.evalsha(sha, 1, key, daily_limit, expire_seconds)  # type: ignore[misc]
        except Exception:
            result = await redis_client.eval(  # type: ignore[misc]
                INCREMENT_WITH_LIMIT_SCRIPT, 1, key, daily_limit, expire_seconds
            )

        allowed = bool(int(result[0]))
        current_count = int(result[1])
        if not allowed:
            self.logger.debug(
                "campaign_daily_rate_limit_hit",
                campaign_id=str(campaign_id),
                limit=daily_limit,
                current=current_count,
            )
        return allowed, current_count

    async def get_campaign_daily_count(self, campaign_id: uuid.UUID) -> int:
        """Get the current UTC-day campaign send count."""
        redis_client = await get_redis()
        day_key = datetime.now(UTC).strftime("%Y%m%d")
        key = f"rate_limit:campaign_daily:{campaign_id}:{day_key}"
        value = await redis_client.get(key)
        return int(value) if value else 0

    async def check_campaign_rate_limit(
        self,
        campaign_id: uuid.UUID,
        messages_per_minute: int,
    ) -> bool:
        """Check campaign-level rate limit (per minute sliding window).

        Uses a sorted set with timestamps to implement sliding window.

        Args:
            campaign_id: Campaign UUID
            messages_per_minute: Maximum messages per minute

        Returns:
            True if message can be sent
        """
        redis_client = await get_redis()
        key = f"rate_limit:campaign:{campaign_id}"

        now = datetime.now(UTC).timestamp()
        window_start = now - 60  # 60 second window

        # Use pipeline for atomic operations
        pipe = redis_client.pipeline()
        # Remove old entries outside the window
        pipe.zremrangebyscore(key, 0, window_start)
        # Count current messages in window
        pipe.zcard(key)
        results = await pipe.execute()

        current_count = results[1]

        if current_count >= messages_per_minute:
            self.logger.debug(
                "campaign_rate_limit_hit",
                campaign_id=str(campaign_id),
                limit=messages_per_minute,
                current=current_count,
            )
            return False

        # Add this message timestamp
        message_id = f"{now}:{uuid.uuid4()}"
        pipe = redis_client.pipeline()
        pipe.zadd(key, {message_id: now})
        pipe.expire(key, 120)  # Keep for 2 minutes
        await pipe.execute()

        return True

    async def get_current_counts(
        self,
        phone_number_id: uuid.UUID,
    ) -> dict[str, int]:
        """Get current rate limit counts for monitoring.

        Args:
            phone_number_id: Phone number UUID

        Returns:
            Dictionary with current counts
        """
        redis_client = await get_redis()

        now = datetime.now(UTC)
        hour_key = now.strftime("%Y%m%d%H")
        day_key = now.strftime("%Y%m%d")

        hourly_key = f"rate_limit:hourly:{phone_number_id}:{hour_key}"
        daily_key = f"rate_limit:daily:{phone_number_id}:{day_key}"

        pipe = redis_client.pipeline()
        pipe.get(hourly_key)
        pipe.get(daily_key)
        results = await pipe.execute()

        return {
            "hourly": int(results[0]) if results[0] else 0,
            "daily": int(results[1]) if results[1] else 0,
        }

    async def reset_rate_limits(
        self,
        phone_number_id: uuid.UUID,
    ) -> None:
        """Reset all rate limits for a phone number.

        Useful after quarantine release or for testing.

        Args:
            phone_number_id: Phone number UUID
        """
        redis_client = await get_redis()

        now = datetime.now(UTC)
        hour_key = now.strftime("%Y%m%d%H")
        day_key = now.strftime("%Y%m%d")

        keys_to_delete = [
            f"rate_limit:per_second:{phone_number_id}",
            f"rate_limit:hourly:{phone_number_id}:{hour_key}",
            f"rate_limit:daily:{phone_number_id}:{day_key}",
        ]

        await redis_client.delete(*keys_to_delete)

        self.logger.info(
            "rate_limits_reset",
            phone_number_id=str(phone_number_id),
        )

    async def get_remaining_capacity(
        self,
        phone_number_id: uuid.UUID,
        daily_limit: int,
        hourly_limit: int,
    ) -> dict[str, int]:
        """Get remaining capacity for a phone number.

        Args:
            phone_number_id: Phone number UUID
            daily_limit: Configured daily limit
            hourly_limit: Configured hourly limit

        Returns:
            Dictionary with remaining capacity
        """
        counts = await self.get_current_counts(phone_number_id)

        return {
            "hourly_remaining": max(0, hourly_limit - counts["hourly"]),
            "daily_remaining": max(0, daily_limit - counts["daily"]),
            "hourly_used": counts["hourly"],
            "daily_used": counts["daily"],
        }
