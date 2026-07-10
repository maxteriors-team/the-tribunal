"""Local availability engine: weekly hours + free/busy -> bookable slots.

Cal.com computes bookable slots server-side; Google Calendar only exposes raw
free/busy. This module rebuilds the missing slot engine so the AI agent keeps
auto-booking from live availability.

Given a workspace/staff schedule config (weekly working hours, timezone, slot
duration, buffers, minimum notice, booking horizon) and the calendar's busy
intervals, it emits slots in the exact ``{"date", "time", "iso"}`` shape that
``BookingService`` already consumes — so nothing upstream changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger()

# Monday=0 .. Sunday=6 -> config keys.
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

_DEFAULT_WEEKLY_HOURS: dict[str, list[list[str]]] = {
    "mon": [["09:00", "17:00"]],
    "tue": [["09:00", "17:00"]],
    "wed": [["09:00", "17:00"]],
    "thu": [["09:00", "17:00"]],
    "fri": [["09:00", "17:00"]],
    "sat": [],
    "sun": [],
}


@dataclass
class ScheduleConfig:
    """Normalized availability configuration."""

    timezone: str = "America/New_York"
    slot_duration_minutes: int = 30
    buffer_before_minutes: int = 0
    buffer_after_minutes: int = 0
    min_notice_minutes: int = 0
    max_horizon_days: int = 60
    weekly_hours: dict[str, list[list[str]]] = field(
        default_factory=lambda: {k: list(v) for k, v in _DEFAULT_WEEKLY_HOURS.items()}
    )

    def zoneinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("America/New_York")


def resolve_schedule_config(
    schedule_config: dict[str, Any] | None,
    *,
    default_timezone: str = "America/New_York",
) -> ScheduleConfig:
    """Coerce a raw JSON schedule config (or ``None``) into a ScheduleConfig."""
    raw = schedule_config or {}
    resolved = ScheduleConfig(
        timezone=str(raw.get("timezone") or default_timezone),
        slot_duration_minutes=_positive_int(raw.get("slot_duration_minutes"), 30),
        buffer_before_minutes=_non_negative_int(raw.get("buffer_before_minutes"), 0),
        buffer_after_minutes=_non_negative_int(raw.get("buffer_after_minutes"), 0),
        min_notice_minutes=_non_negative_int(raw.get("min_notice_minutes"), 0),
        max_horizon_days=_positive_int(raw.get("max_horizon_days"), 60),
        weekly_hours=_normalize_weekly_hours(raw.get("weekly_hours")),
    )
    return resolved


def compute_available_slots(
    *,
    schedule: ScheduleConfig,
    start_date: datetime,
    end_date: datetime,
    busy_intervals: list[dict[str, str]],
    now: datetime | None = None,
    max_slots: int | None = None,
) -> list[dict[str, str]]:
    """Return bookable slots between ``start_date`` and ``end_date`` (inclusive days).

    Args:
        schedule: Normalized schedule config.
        start_date / end_date: Range endpoints (any tz-aware datetime; only the
            calendar dates in ``schedule``'s timezone are used).
        busy_intervals: ``[{"start", "end"}]`` RFC 3339 busy blocks from free/busy.
        now: Reference "now" for minimum-notice / horizon (defaults to UTC now).
        max_slots: Optional cap on the number of returned slots.
    """
    tz = schedule.zoneinfo()
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)

    earliest = now_utc + timedelta(minutes=schedule.min_notice_minutes)
    horizon = now_utc + timedelta(days=schedule.max_horizon_days)

    busy = _parse_busy(busy_intervals)

    start_day = start_date.astimezone(tz).date()
    end_day = end_date.astimezone(tz).date()

    duration = timedelta(minutes=schedule.slot_duration_minutes)
    buffer_before = timedelta(minutes=schedule.buffer_before_minutes)
    buffer_after = timedelta(minutes=schedule.buffer_after_minutes)

    slots: list[dict[str, str]] = []
    current = start_day
    while current <= end_day:
        key = _WEEKDAY_KEYS[current.weekday()]
        for window_start, window_end in schedule.weekly_hours.get(key, []):
            cursor = datetime.combine(current, _parse_hhmm(window_start), tzinfo=tz)
            window_close = datetime.combine(current, _parse_hhmm(window_end), tzinfo=tz)
            while cursor + duration <= window_close:
                slot_start = cursor
                slot_end = cursor + duration
                cursor = cursor + duration

                start_utc = slot_start.astimezone(UTC)
                if start_utc < earliest or start_utc >= horizon:
                    continue

                buffered_start = start_utc - buffer_before
                buffered_end = slot_end.astimezone(UTC) + buffer_after
                if _overlaps_busy(buffered_start, buffered_end, busy):
                    continue

                slots.append(
                    {
                        "date": slot_start.strftime("%Y-%m-%d"),
                        "time": slot_start.strftime("%H:%M"),
                        "iso": slot_start.isoformat(),
                    }
                )
                if max_slots is not None and len(slots) >= max_slots:
                    return slots
        current = current + timedelta(days=1)

    return slots


# ── internals ───────────────────────────────────────────────────────


def _parse_busy(busy_intervals: list[dict[str, str]]) -> list[tuple[datetime, datetime]]:
    parsed: list[tuple[datetime, datetime]] = []
    for block in busy_intervals:
        start_raw = block.get("start")
        end_raw = block.get("end")
        if not start_raw or not end_raw:
            continue
        try:
            start = _parse_rfc3339(start_raw)
            end = _parse_rfc3339(end_raw)
        except ValueError:
            logger.warning("google_availability_bad_busy_block", start=start_raw, end=end_raw)
            continue
        parsed.append((start, end))
    return parsed


def _overlaps_busy(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    # Half-open overlap test: [start, end) intersects any [busy_start, busy_end).
    return any(start < busy_end and busy_start < end for busy_start, busy_end in busy)


def _parse_rfc3339(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _normalize_weekly_hours(raw: Any) -> dict[str, list[list[str]]]:
    if not isinstance(raw, dict):
        return {k: list(v) for k, v in _DEFAULT_WEEKLY_HOURS.items()}

    normalized: dict[str, list[list[str]]] = {k: [] for k in _WEEKDAY_KEYS}
    for key in _WEEKDAY_KEYS:
        windows = raw.get(key, [])
        if not isinstance(windows, list):
            continue
        for window in windows:
            pair = _coerce_window(window)
            if pair is not None:
                normalized[key].append([pair[0], pair[1]])
    return normalized


def _coerce_window(window: Any) -> tuple[str, str] | None:
    if isinstance(window, dict):
        start = window.get("start")
        end = window.get("end")
    elif isinstance(window, (list, tuple)) and len(window) == 2:
        start, end = window
    else:
        return None
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    # Validate HH:MM parses.
    try:
        _parse_hhmm(start)
        _parse_hhmm(end)
    except ValueError:
        return None
    return start, end


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(hour=int(hours), minute=int(minutes))


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
