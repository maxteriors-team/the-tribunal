"""Unit tests for the Google availability slot engine."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.services.calendar.google.availability import (
    compute_available_slots,
    resolve_schedule_config,
)

# A Wednesday.
WED = datetime(2099, 1, 14, tzinfo=ZoneInfo("America/New_York"))
# Reference "now" far before the window so min-notice never trims (unless tested).
NOW = datetime(2099, 1, 1, 12, 0, tzinfo=UTC)


def _schedule(**overrides: object):
    base: dict[str, object] = {
        "timezone": "America/New_York",
        "slot_duration_minutes": 30,
        "weekly_hours": {
            "mon": [["09:00", "11:00"]],
            "tue": [["09:00", "11:00"]],
            "wed": [["09:00", "11:00"]],
            "thu": [["09:00", "11:00"]],
            "fri": [["09:00", "11:00"]],
            "sat": [],
            "sun": [],
        },
    }
    base.update(overrides)
    return resolve_schedule_config(base)


def test_generates_slots_across_working_window() -> None:
    slots = compute_available_slots(
        schedule=_schedule(),
        start_date=WED,
        end_date=WED,
        busy_intervals=[],
        now=NOW,
    )
    # 09:00-11:00, 30-min slots -> 09:00, 09:30, 10:00, 10:30 (10:30-11:00 fits).
    assert [s["time"] for s in slots] == ["09:00", "09:30", "10:00", "10:30"]
    assert all(s["date"] == "2099-01-14" for s in slots)
    # ISO carries the local offset (EST = -05:00 in January).
    assert slots[0]["iso"].endswith("-05:00")


def test_busy_block_removes_overlapping_slot() -> None:
    # Busy 09:30-10:00 EST == 14:30-15:00 UTC.
    slots = compute_available_slots(
        schedule=_schedule(),
        start_date=WED,
        end_date=WED,
        busy_intervals=[{"start": "2099-01-14T14:30:00Z", "end": "2099-01-14T15:00:00Z"}],
        now=NOW,
    )
    assert [s["time"] for s in slots] == ["09:00", "10:00", "10:30"]


def test_buffer_after_blocks_adjacent_slot() -> None:
    # Busy 10:00-10:15 EST with a 15-min after-buffer knocks out the 09:30 slot
    # (09:30-10:00 + 15m buffer touches the busy block).
    slots = compute_available_slots(
        schedule=_schedule(buffer_after_minutes=15),
        start_date=WED,
        end_date=WED,
        busy_intervals=[{"start": "2099-01-14T15:00:00Z", "end": "2099-01-14T15:15:00Z"}],
        now=NOW,
    )
    times = [s["time"] for s in slots]
    assert "09:30" not in times
    assert "10:00" not in times  # directly overlaps busy
    assert "09:00" in times


def test_min_notice_trims_near_term_slots() -> None:
    # "now" is 09:05 EST on the target day; 3h notice removes 09:00-11:00 entirely.
    now = datetime(2099, 1, 14, 14, 5, tzinfo=UTC)  # 09:05 EST
    slots = compute_available_slots(
        schedule=_schedule(min_notice_minutes=180),
        start_date=WED,
        end_date=WED,
        busy_intervals=[],
        now=now,
    )
    assert slots == []


def test_weekend_has_no_slots() -> None:
    saturday = datetime(2099, 1, 17, tzinfo=ZoneInfo("America/New_York"))
    slots = compute_available_slots(
        schedule=_schedule(),
        start_date=saturday,
        end_date=saturday,
        busy_intervals=[],
        now=NOW,
    )
    assert slots == []


def test_max_slots_caps_output() -> None:
    slots = compute_available_slots(
        schedule=_schedule(),
        start_date=WED,
        end_date=WED,
        busy_intervals=[],
        now=NOW,
        max_slots=2,
    )
    assert len(slots) == 2


def test_resolve_defaults_apply_for_none() -> None:
    cfg = resolve_schedule_config(None, default_timezone="America/Chicago")
    assert cfg.timezone == "America/Chicago"
    assert cfg.slot_duration_minutes == 30
    assert cfg.weekly_hours["sat"] == []
    assert cfg.weekly_hours["mon"] == [["09:00", "17:00"]]


def test_invalid_config_values_fall_back() -> None:
    cfg = resolve_schedule_config(
        {"slot_duration_minutes": "oops", "min_notice_minutes": -5, "max_horizon_days": 0}
    )
    assert cfg.slot_duration_minutes == 30
    assert cfg.min_notice_minutes == 0
    assert cfg.max_horizon_days == 60
