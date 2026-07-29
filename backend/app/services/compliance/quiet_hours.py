"""Quiet-hours evaluation shared by outbound senders.

Every outbound path that is not a reply to a live conversation has to answer the
same question — "is it a reasonable hour where this person lives?" — and each one
that answers it privately is one more place a wrap-past-midnight window
(21:00 -> 08:00) can be got subtly wrong. This module owns that arithmetic once:

* clock strings are parsed permissively (``HH:MM`` / ``HH:MM:SS``), because they
  come from an operator-edited JSONB blob rather than a typed column;
* an unknown IANA zone degrades to UTC with a warning instead of raising, so a
  typo'd timezone cannot wedge a worker loop;
* a window whose start is after its end is read as wrapping past midnight, which
  is the shape every real "don't text at night" window takes.

A missing start *or* end means "no window configured", and the send proceeds —
the caller's own compliance gates (opt-out, consent) still apply.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import structlog

logger = structlog.get_logger()


def parse_clock(value: str | time | None) -> time | None:
    """Parse ``HH:MM``/``HH:MM:SS`` into a :class:`~datetime.time`, or None."""
    if isinstance(value, time):
        return value
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    if not 1 <= len(parts) <= 3:
        return None
    hour, minute, second = (parts + [0, 0])[:3]
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return time(hour, minute, second)


def resolve_zone(timezone_name: str | None) -> ZoneInfo:
    """Return the named zone, falling back to UTC when it cannot be loaded."""
    if not timezone_name:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("invalid_quiet_hours_timezone", timezone=timezone_name)
        return ZoneInfo("UTC")


def is_within_quiet_hours(
    start: str | time | None,
    end: str | time | None,
    *,
    timezone_name: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Return True when ``now`` falls inside the ``start``-``end`` local window.

    Windows that wrap past midnight (``21:00`` -> ``08:00``) are supported; the
    end bound is exclusive so a window ending at 08:00 permits an 08:00 send.
    """
    window_start = parse_clock(start)
    window_end = parse_clock(end)
    if window_start is None or window_end is None:
        return False

    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    local_time = reference.astimezone(resolve_zone(timezone_name)).time()

    if window_start <= window_end:
        return window_start <= local_time < window_end
    return local_time >= window_start or local_time < window_end


__all__ = ["is_within_quiet_hours", "parse_clock", "resolve_zone"]
