"""Fail-closed spend limits for authenticated browser calling."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from app.db.redis import get_redis

logger = structlog.get_logger()

_INCREMENT_WITH_LIMIT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
  return {0, current}
end
current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return {1, current}
"""


class SoftphoneRateLimitError(RuntimeError):
    """Raised when an operator or workspace exhausts its call allowance."""


class SoftphoneRateLimitUnavailableError(RuntimeError):
    """Raised when spend protection cannot be checked."""


async def enforce_softphone_token_limit(*, user_id: int) -> None:
    """Limit short-lived credential minting to ten tokens per user-hour."""
    now = datetime.now(UTC)
    await _check(
        key=f"softphone:token:user:{user_id}:{now:%Y%m%d%H}",
        limit=10,
        ttl_seconds=3600,
    )


async def enforce_softphone_call_limits(*, workspace_id: str, user_id: int) -> None:
    """Limit paid call attempts per user and workspace."""
    now = datetime.now(UTC)
    checks = (
        (f"softphone:call:user-hour:{user_id}:{now:%Y%m%d%H}", 60, 3600),
        (f"softphone:call:workspace-hour:{workspace_id}:{now:%Y%m%d%H}", 300, 3600),
        (f"softphone:call:user-day:{user_id}:{now:%Y%m%d}", 300, 86400),
        (f"softphone:call:workspace-day:{workspace_id}:{now:%Y%m%d}", 1500, 86400),
    )
    for key, limit, ttl_seconds in checks:
        await _check(key=key, limit=limit, ttl_seconds=ttl_seconds)


async def _check(*, key: str, limit: int, ttl_seconds: int) -> None:
    try:
        redis = await get_redis()
        result = await redis.eval(_INCREMENT_WITH_LIMIT, 1, key, limit, ttl_seconds)  # type: ignore[misc]
    except Exception as exc:
        logger.error("softphone_rate_limit_unavailable", exc_info=exc)
        raise SoftphoneRateLimitUnavailableError(
            "Browser calling is unavailable while spend protection is offline"
        ) from exc

    if not bool(int(result[0])):
        raise SoftphoneRateLimitError("Browser calling limit reached; try again later")
