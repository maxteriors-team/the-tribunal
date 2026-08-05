"""Per-workspace caps on the address-autocomplete endpoints.

Address lookup runs on Google Places when a key is configured, which bills per
request. A typeahead fires far more often than the Find Leads search does, so
this uses the same fixed-window counters as
:mod:`app.services.rate_limiting.scraping_limiter` with a ceiling sized for
interactive typing instead of batch prospecting: a debounced field costs a
handful of calls per address, so the hourly cap still allows dozens of contacts
per hour while stopping a stuck key or a scripted client from running up a bill.

Keys:

* ``address_lookup:ws:<workspace_id>:hour:<YYYYMMDDHH>`` — TTL 1h
* ``address_lookup:ws:<workspace_id>:day:<YYYYMMDD>``    — TTL until UTC midnight

Fail-open on Redis errors, matching the scraping limiter: a Redis outage must
not make address entry impossible.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog

from app.core.rate_limit_helpers import raise_rate_limited
from app.db.redis import get_redis
from app.services.rate_limiting.rate_limiter import INCREMENT_WITH_LIMIT_SCRIPT

logger = structlog.get_logger()

ADDRESS_LOOKUP_HOURLY_LIMIT = 400
ADDRESS_LOOKUP_DAILY_LIMIT = 3000


def _seconds_until_next_hour(now: datetime) -> int:
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max(1, int((next_hour - now).total_seconds()))


def _seconds_until_midnight(now: datetime) -> int:
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


async def _check_and_increment(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
    """Atomically check-and-increment one fixed-window counter."""
    redis_client = await get_redis()
    result = await redis_client.eval(  # type: ignore[misc]
        INCREMENT_WITH_LIMIT_SCRIPT, 1, key, limit, expire_seconds
    )
    return bool(int(result[0])), int(result[1])


async def enforce_address_lookup_rate_limit(
    workspace_id: uuid.UUID,
    *,
    hourly_limit: int = ADDRESS_LOOKUP_HOURLY_LIMIT,
    daily_limit: int = ADDRESS_LOOKUP_DAILY_LIMIT,
) -> None:
    """Enforce hourly + daily address-lookup quotas for one workspace.

    Raises:
        HTTPException: 429 with ``Retry-After`` (seconds until the soonest
            window reset) when either quota is exhausted.
    """
    now = datetime.now(UTC)
    windows = (
        (
            "hour",
            f"address_lookup:ws:{workspace_id}:hour:{now:%Y%m%d%H}",
            hourly_limit,
            _seconds_until_next_hour(now),
        ),
        (
            "day",
            f"address_lookup:ws:{workspace_id}:day:{now:%Y%m%d}",
            daily_limit,
            _seconds_until_midnight(now),
        ),
    )

    for window, key, limit, ttl in windows:
        try:
            allowed, current = await _check_and_increment(key, limit, ttl)
        except Exception as exc:  # noqa: BLE001 - fail-open intentionally
            logger.warning(
                "address_lookup_rate_limit_redis_error",
                workspace_id=str(workspace_id),
                window=window,
                error=str(exc),
            )
            return

        if not allowed:
            logger.info(
                "address_lookup_rate_limit_exceeded",
                workspace_id=str(workspace_id),
                window=window,
                limit=limit,
                current=current,
                retry_after_seconds=ttl,
            )
            raise_rate_limited(
                ttl,
                detail=(
                    f"Address lookup limit reached for this workspace. "
                    f"Try again in {ttl} seconds, or type the address manually."
                ),
            )
