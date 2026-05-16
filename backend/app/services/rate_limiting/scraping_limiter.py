"""Redis-backed rate limiting for paid Google Places scraping endpoints.

The Find Leads endpoints in ``app/api/v1/scraping.py`` and
``app/api/v1/find_leads_ai.py`` call the paid Google Places API. Without a
per-workspace cap, a buggy client or abusive user could rack up real money in
charges. This module enforces a per-workspace hourly + daily quota using a
fixed-window counter in Redis.

Keys (per the API contract used in tests):

* ``scraping:ws:<workspace_id>:hour:<YYYYMMDDHH>`` — TTL 1h
* ``scraping:ws:<workspace_id>:day:<YYYYMMDD>``   — TTL until UTC midnight

On limit-exceeded the request fails with HTTP 429 and a ``Retry-After`` header
expressed in seconds until the *narrowest* window resets (hour resets sooner
than day, so we surface that).

Fail-open behavior: if Redis is unreachable we log a warning and let the
request through. The paid API still has its own quota on the upstream side; we
prefer transient outages over locking every workspace out of the feature.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog

from app.core.rate_limit_helpers import raise_rate_limited
from app.db.redis import get_redis
from app.services.rate_limiting.rate_limiter import INCREMENT_WITH_LIMIT_SCRIPT

logger = structlog.get_logger()


# Default limits — tuned to keep Google Places costs predictable per workspace.
SCRAPING_HOURLY_LIMIT = 20
SCRAPING_DAILY_LIMIT = 100

_ONE_HOUR_SECONDS = 3600


def _hour_bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d%H")


def _day_bucket(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def _seconds_until_next_hour(now: datetime) -> int:
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max(1, int((next_hour - now).total_seconds()))


def _seconds_until_midnight(now: datetime) -> int:
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


async def _check_and_increment(
    key: str,
    limit: int,
    expire_seconds: int,
) -> tuple[bool, int]:
    """Atomically check-and-increment a fixed-window counter.

    Returns ``(allowed, current_count)``. When ``allowed`` is ``False`` the
    counter is *not* incremented further so a steady stream of rejected
    requests can't keep extending the window's effective ceiling.
    """
    redis_client = await get_redis()
    result = await redis_client.eval(  # type: ignore[misc]
        INCREMENT_WITH_LIMIT_SCRIPT, 1, key, limit, expire_seconds
    )
    allowed = bool(int(result[0]))
    current = int(result[1])
    return allowed, current


async def enforce_scraping_rate_limit(
    workspace_id: uuid.UUID,
    *,
    hourly_limit: int = SCRAPING_HOURLY_LIMIT,
    daily_limit: int = SCRAPING_DAILY_LIMIT,
) -> None:
    """Enforce per-workspace hourly + daily caps on Google Places searches.

    Raises:
        HTTPException: 429 with a ``Retry-After`` header (seconds) when either
            the hourly or daily quota is exhausted. The header points to the
            *soonest* reset so clients don't sleep longer than necessary.
    """
    now = datetime.now(UTC)
    hour_key = f"scraping:ws:{workspace_id}:hour:{_hour_bucket(now)}"
    day_key = f"scraping:ws:{workspace_id}:day:{_day_bucket(now)}"

    hour_ttl = _seconds_until_next_hour(now)
    day_ttl = _seconds_until_midnight(now)

    try:
        hour_allowed, hour_count = await _check_and_increment(
            key=hour_key,
            limit=hourly_limit,
            expire_seconds=hour_ttl,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open intentionally
        logger.warning(
            "scraping_rate_limit_redis_error",
            workspace_id=str(workspace_id),
            window="hour",
            error=str(exc),
        )
        return

    if not hour_allowed:
        logger.info(
            "scraping_rate_limit_exceeded",
            workspace_id=str(workspace_id),
            window="hour",
            limit=hourly_limit,
            current=hour_count,
            retry_after_seconds=hour_ttl,
        )
        raise_rate_limited(
            hour_ttl,
            detail=(
                f"Hourly search limit reached for this workspace. "
                f"Try again in {hour_ttl} seconds."
            ),
        )

    try:
        day_allowed, day_count = await _check_and_increment(
            key=day_key,
            limit=daily_limit,
            expire_seconds=day_ttl,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open intentionally
        logger.warning(
            "scraping_rate_limit_redis_error",
            workspace_id=str(workspace_id),
            window="day",
            error=str(exc),
        )
        return

    if not day_allowed:
        logger.info(
            "scraping_rate_limit_exceeded",
            workspace_id=str(workspace_id),
            window="day",
            limit=daily_limit,
            current=day_count,
            retry_after_seconds=day_ttl,
        )
        raise_rate_limited(
            day_ttl,
            detail=(
                f"Daily search limit reached for this workspace. "
                f"Try again in {day_ttl} seconds."
            ),
        )
