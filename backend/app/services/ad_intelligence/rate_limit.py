"""Provider call rate-limiting, cost metering, and response caching for
ad-library intelligence.

The Meta Ad Library default tier is ~200 calls/hour/app. Because the CRM runs
its background workers inside the API process (and may run multiple replicas),
re-scans + monitors could collectively blow past that tier. This module:

* enforces a **global hourly cap** on provider calls (shared across replicas);
* meters **call cost** per platform per hour for ops visibility;
* provides a short-TTL **response cache / idempotency** layer so identical
  searches within a window reuse a result instead of spending budget.

All state lives in Redis (shared across processes) and fails *open* — a Redis
outage must never wedge discovery; the upstream 429 handling is the backstop.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from app.core.config import settings
from app.db.redis import get_redis

logger = structlog.get_logger()

# Default cache TTL for identical ad-library searches (seconds).
RESPONSE_CACHE_TTL_SECONDS = 900

# Atomic check-and-increment with a per-key TTL (mirrors rate_limiter.py).
_INCREMENT_WITH_LIMIT = """
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


def _hour_bucket(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y%m%d%H")


def _provider_cap(platform: str) -> int:
    """Resolve the hourly call cap for a platform."""
    if platform == "google":
        # SerpApi/Google path; reuse the same conservative cap by default.
        return settings.meta_ad_library_rate_limit_per_hour
    return settings.meta_ad_library_rate_limit_per_hour


async def acquire_provider_call_slot(
    platform: str,
    *,
    cost: int = 1,
    cap: int | None = None,
) -> tuple[bool, int]:
    """Try to reserve ``cost`` provider call(s) within the current hour.

    Returns ``(allowed, current_count)``. The counter is global per platform
    per hour so all replicas share one budget. Redis being unreachable fails
    *open* (allows the call) but logs — we'd rather make the call than wedge
    discovery, and the upstream 429 handling is the real backstop.
    """
    limit = cap if cap is not None else _provider_cap(platform)
    key = f"ad_library:rate:{platform}:{_hour_bucket()}"
    try:
        redis = await get_redis()
        allowed = True
        current = 0
        for _ in range(max(1, cost)):
            result = await redis.eval(_INCREMENT_WITH_LIMIT, 1, key, limit, 3600)  # type: ignore[misc]
            allowed = bool(int(result[0]))
            current = int(result[1])
            if not allowed:
                break
        if not allowed:
            logger.warning(
                "ad_library_rate_limited",
                platform=platform,
                limit=limit,
                current=current,
            )
        return allowed, current
    except Exception as exc:  # noqa: BLE001 - fail open, never wedge discovery
        logger.warning("ad_library_rate_limit_unavailable", error=type(exc).__name__)
        return True, 0


async def current_usage(platform: str) -> int:
    """Return the number of provider calls used this hour (best-effort)."""
    key = f"ad_library:rate:{platform}:{_hour_bucket()}"
    try:
        redis = await get_redis()
        value = await redis.get(key)
        return int(value) if value else 0
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------------------
# Cost meter
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ProviderUsage:
    """Snapshot of provider usage for a platform in the current hour."""

    platform: str
    calls_this_hour: int
    cap_per_hour: int

    @property
    def remaining(self) -> int:
        return max(0, self.cap_per_hour - self.calls_this_hour)


async def record_cost(platform: str, *, cost: int = 1) -> None:
    """Increment the per-platform per-hour cost meter (best-effort)."""
    key = f"ad_library:cost:{platform}:{_hour_bucket()}"
    try:
        redis = await get_redis()
        new_value = await redis.incrby(key, max(0, cost))
        if new_value == cost:
            await redis.expire(key, 3600)
    except Exception as exc:  # noqa: BLE001
        logger.debug("ad_library_cost_meter_unavailable", error=type(exc).__name__)


async def get_usage(platform: str) -> ProviderUsage:
    """Return the current hour's usage snapshot for ``platform``."""
    calls = await current_usage(platform)
    return ProviderUsage(
        platform=platform, calls_this_hour=calls, cap_per_hour=_provider_cap(platform)
    )


# ---------------------------------------------------------------------------
# Response cache / idempotency
# ---------------------------------------------------------------------------


def cache_key_for_search(workspace_id: Any, platform: str, params: dict[str, Any]) -> str:
    """Deterministic cache key for an identical ad-library search.

    Only the parameters that affect provider results are hashed; pagination /
    bookkeeping fields are excluded by the caller before passing ``params``.
    """
    basis = json.dumps(
        {"workspace_id": str(workspace_id), "platform": platform, "params": params},
        sort_keys=True,
        default=str,
    )
    digest = hashlib.blake2b(basis.encode(), digest_size=16).hexdigest()
    return f"ad_library:cache:{platform}:{digest}"


async def get_cached_search(cache_key: str) -> dict[str, Any] | None:
    """Return a cached search payload, or ``None`` on miss / error."""
    try:
        redis = await get_redis()
        raw = await redis.get(cache_key)
        if not raw:
            return None
        decoded: dict[str, Any] = json.loads(raw)
        return decoded
    except Exception as exc:  # noqa: BLE001
        logger.debug("ad_library_cache_read_failed", error=type(exc).__name__)
        return None


async def set_cached_search(
    cache_key: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = RESPONSE_CACHE_TTL_SECONDS,
) -> None:
    """Cache a search payload for a short window (best-effort)."""
    try:
        redis = await get_redis()
        await redis.setex(cache_key, ttl_seconds, json.dumps(payload, default=str))
    except Exception as exc:  # noqa: BLE001
        logger.debug("ad_library_cache_write_failed", error=type(exc).__name__)
