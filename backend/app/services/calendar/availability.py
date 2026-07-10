"""Local availability slot engine.

Computes free appointment start-times from a workspace's weekly business
hours minus its existing CRM appointments. This is the self-contained
replacement for the external Cal.com availability API — the CRM is the single
source of truth for scheduling.

Pure and side-effect free: callers load the weekly schedule + busy intervals
(existing ``scheduled`` appointments) from the database and pass them in, which
keeps this module trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# date.weekday(): Monday=0 … Sunday=6. Index maps a weekday number to the keys
# accepted in a stored ``business_hours`` schedule (full name + 3-letter form).
_WEEKDAY_ALIASES: tuple[tuple[str, str], ...] = (
    ("monday", "mon"),
    ("tuesday", "tue"),
    ("wednesday", "wed"),
    ("thursday", "thu"),
    ("friday", "fri"),
    ("saturday", "sat"),
    ("sunday", "sun"),
)

# Sensible fallback when a workspace has not configured business hours (there is
# no UI/seed for them yet, so most workspaces have an empty schedule): weekdays
# 9am–5pm, closed weekends. Without this, agents would offer zero slots.
_DEFAULT_OPEN = time(9, 0)
_DEFAULT_CLOSE = time(17, 0)


@dataclass(frozen=True)
class DayHours:
    """Opening hours for a single weekday."""

    enabled: bool
    open: time
    close: time


@dataclass(frozen=True)
class BusyInterval:
    """A tz-aware [start, end) interval that blocks slots (an existing appt)."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class Slot:
    """A single bookable start-time."""

    date: str  # YYYY-MM-DD (local)
    time: str  # HH:MM 24-hour (local)
    iso: str  # ISO-8601 with tz offset


def _default_week() -> dict[int, DayHours]:
    """Weekdays 9–5, weekends closed."""
    week: dict[int, DayHours] = {}
    for weekday in range(7):
        is_weekend = weekday >= 5
        week[weekday] = DayHours(
            enabled=not is_weekend,
            open=_DEFAULT_OPEN,
            close=_DEFAULT_CLOSE,
        )
    return week


def _parse_time(value: Any, fallback: time) -> time:
    """Parse an ``"HH:MM"`` string, falling back on malformed input."""
    if isinstance(value, str):
        try:
            hour, _, minute = value.partition(":")
            return time(int(hour), int(minute or 0))
        except (ValueError, TypeError):
            return fallback
    return fallback


def parse_schedule(business_hours: dict[str, Any] | None) -> dict[int, DayHours]:
    """Build a weekday→hours map from a stored ``business_hours`` setting.

    ``business_hours`` shape (see ``BusinessHoursSettings``)::

        {"is_24_7": bool, "schedule": {"<day>": {"enabled", "open", "close"}}}

    Falls back to the default week when the setting is missing or empty, and to
    per-day defaults for any day absent from an otherwise-populated schedule.
    """
    if not business_hours:
        return _default_week()

    if business_hours.get("is_24_7"):
        return {
            weekday: DayHours(enabled=True, open=time(0, 0), close=time(23, 59))
            for weekday in range(7)
        }

    raw_schedule = business_hours.get("schedule") or {}
    if not isinstance(raw_schedule, dict) or not raw_schedule:
        return _default_week()

    # Normalize keys to lowercase for alias matching.
    normalized = {
        str(key).strip().lower(): value
        for key, value in raw_schedule.items()
        if isinstance(value, dict)
    }

    week: dict[int, DayHours] = {}
    defaults = _default_week()
    for weekday, aliases in enumerate(_WEEKDAY_ALIASES):
        entry = next((normalized[a] for a in aliases if a in normalized), None)
        if entry is None:
            week[weekday] = defaults[weekday]
            continue
        week[weekday] = DayHours(
            enabled=bool(entry.get("enabled", True)),
            open=_parse_time(entry.get("open"), _DEFAULT_OPEN),
            close=_parse_time(entry.get("close"), _DEFAULT_CLOSE),
        )
    return week


def _overlaps_busy(start: datetime, end: datetime, busy: list[BusyInterval]) -> bool:
    """True when [start, end) intersects any busy interval."""
    return any(interval.start < end and start < interval.end for interval in busy)


def compute_available_slots(
    *,
    schedule: dict[int, DayHours],
    tz: ZoneInfo,
    start_date: date,
    end_date: date,
    busy: list[BusyInterval],
    slot_minutes: int = 30,
    now: datetime | None = None,
    max_slots: int = 15,
) -> list[Slot]:
    """Return open start-times between ``start_date`` and ``end_date`` inclusive.

    A slot is offered when it fits entirely within that weekday's open hours,
    is not in the past (relative to ``now``), and does not overlap a busy
    interval. Days are walked in order and generation stops at ``max_slots``.
    """
    if slot_minutes <= 0 or start_date > end_date:
        return []

    step = timedelta(minutes=slot_minutes)
    current = now.astimezone(tz) if now is not None else datetime.now(tz)

    slots: list[Slot] = []
    day = start_date
    while day <= end_date:
        hours = schedule.get(day.weekday())
        if hours is None or not hours.enabled or hours.close <= hours.open:
            day += timedelta(days=1)
            continue

        cursor = datetime.combine(day, hours.open, tzinfo=tz)
        day_close = datetime.combine(day, hours.close, tzinfo=tz)
        while cursor + step <= day_close:
            slot_end = cursor + step
            if cursor >= current and not _overlaps_busy(cursor, slot_end, busy):
                slots.append(
                    Slot(
                        date=day.isoformat(),
                        time=cursor.strftime("%H:%M"),
                        iso=cursor.isoformat(),
                    )
                )
                if len(slots) >= max_slots:
                    return slots
            cursor += step
        day += timedelta(days=1)

    return slots
