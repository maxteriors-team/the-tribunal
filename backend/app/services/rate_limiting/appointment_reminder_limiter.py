"""Per-workspace caps on manual appointment reminder SMS sends.

A reminder click creates provider spend and customer-visible messaging. Fixed
hourly and daily Redis windows stop scripted or stuck clients from repeatedly
sending the same class of message while leaving normal dispatch use ample room.
The limiter fails closed: a Redis outage must not turn a paid messaging endpoint
into an unmetered send path.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException, status

from app.core.rate_limit_helpers import raise_rate_limited
from app.db.redis import get_redis
from app.services.rate_limiting.rate_limiter import INCREMENT_WITH_LIMIT_SCRIPT

logger = structlog.get_logger()

APPOINTMENT_REMINDER_USER_HOURLY_LIMIT = 25
APPOINTMENT_REMINDER_WORKSPACE_HOURLY_LIMIT = 100
APPOINTMENT_REMINDER_WORKSPACE_DAILY_LIMIT = 500


def _seconds_until_next_hour(now: datetime) -> int:
    next_hour = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
    return max(1, int((next_hour - now).total_seconds()))


def _seconds_until_midnight(now: datetime) -> int:
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


async def _check_and_increment(key: str, limit: int, expire_seconds: int) -> tuple[bool, int]:
    """Atomically check and increment one fixed-window counter."""
    redis_client = await get_redis()
    result = await redis_client.eval(  # type: ignore[misc]
        INCREMENT_WITH_LIMIT_SCRIPT, 1, key, limit, expire_seconds
    )
    return bool(int(result[0])), int(result[1])


async def enforce_appointment_reminder_rate_limit(
    workspace_id: uuid.UUID,
    user_id: int,
    *,
    user_hourly_limit: int = APPOINTMENT_REMINDER_USER_HOURLY_LIMIT,
    workspace_hourly_limit: int = APPOINTMENT_REMINDER_WORKSPACE_HOURLY_LIMIT,
    workspace_daily_limit: int = APPOINTMENT_REMINDER_WORKSPACE_DAILY_LIMIT,
) -> None:
    """Enforce per-user and workspace reminder-send quotas."""
    now = datetime.now(UTC)
    hour_ttl = _seconds_until_next_hour(now)
    windows = (
        (
            "user_hour",
            f"appointment_reminder:ws:{workspace_id}:user:{user_id}:hour:{now:%Y%m%d%H}",
            user_hourly_limit,
            hour_ttl,
        ),
        (
            "workspace_hour",
            f"appointment_reminder:ws:{workspace_id}:hour:{now:%Y%m%d%H}",
            workspace_hourly_limit,
            hour_ttl,
        ),
        (
            "workspace_day",
            f"appointment_reminder:ws:{workspace_id}:day:{now:%Y%m%d}",
            workspace_daily_limit,
            _seconds_until_midnight(now),
        ),
    )

    for window, key, limit, ttl in windows:
        try:
            allowed, current = await _check_and_increment(key, limit, ttl)
        except Exception as exc:  # noqa: BLE001 - fail closed intentionally
            logger.error(
                "appointment_reminder_rate_limit_redis_error",
                workspace_id=str(workspace_id),
                window=window,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Reminder sending is temporarily unavailable",
            ) from exc

        if not allowed:
            logger.info(
                "appointment_reminder_rate_limit_exceeded",
                workspace_id=str(workspace_id),
                window=window,
                limit=limit,
                current=current,
                retry_after_seconds=ttl,
            )
            raise_rate_limited(
                ttl,
                detail=(
                    "Appointment reminder limit reached for this workspace. "
                    f"Try again in {ttl} seconds."
                ),
            )
