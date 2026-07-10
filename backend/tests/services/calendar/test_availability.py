"""Tests for the local availability slot engine.

Covers schedule parsing (defaults, 24/7, aliased keys) and slot generation
against business hours minus busy CRM appointments.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.services.calendar.availability import (
    BusyInterval,
    DayHours,
    compute_available_slots,
    parse_schedule,
)

TZ = ZoneInfo("America/New_York")


class TestParseSchedule:
    def test_missing_setting_defaults_to_weekdays_nine_to_five(self) -> None:
        week = parse_schedule(None)
        # Monday (0) … Friday (4) open 9–5, weekends closed.
        for weekday in range(5):
            assert week[weekday] == DayHours(enabled=True, open=time(9, 0), close=time(17, 0))
        assert week[5].enabled is False
        assert week[6].enabled is False

    def test_empty_schedule_falls_back_to_default(self) -> None:
        assert parse_schedule({"is_24_7": False, "schedule": {}}) == parse_schedule(None)

    def test_is_24_7_opens_every_day(self) -> None:
        week = parse_schedule({"is_24_7": True})
        assert all(week[d].enabled for d in range(7))
        assert week[2].open == time(0, 0)

    def test_full_name_and_abbreviated_keys_both_parse(self) -> None:
        week = parse_schedule(
            {
                "schedule": {
                    "monday": {"enabled": True, "open": "08:00", "close": "12:00"},
                    "tue": {"enabled": False, "open": "09:00", "close": "17:00"},
                }
            }
        )
        assert week[0] == DayHours(enabled=True, open=time(8, 0), close=time(12, 0))
        assert week[1].enabled is False
        # Days absent from the schedule keep per-day defaults (Wed weekday=2 open).
        assert week[2] == DayHours(enabled=True, open=time(9, 0), close=time(17, 0))

    def test_malformed_time_falls_back(self) -> None:
        week = parse_schedule({"schedule": {"monday": {"enabled": True, "open": "oops"}}})
        assert week[0].open == time(9, 0)


class TestComputeAvailableSlots:
    def test_generates_half_hour_slots_within_hours(self) -> None:
        # Wednesday 2026-07-15, 9–11 => 9:00, 9:30, 10:00, 10:30 (10:30+30=11:00 fits).
        schedule = {2: DayHours(enabled=True, open=time(9, 0), close=time(11, 0))}
        slots = compute_available_slots(
            schedule=schedule,
            tz=TZ,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            busy=[],
            slot_minutes=30,
            now=datetime(2026, 7, 1, 0, 0, tzinfo=TZ),
        )
        assert [s.time for s in slots] == ["09:00", "09:30", "10:00", "10:30"]
        assert slots[0].date == "2026-07-15"
        assert slots[0].iso.startswith("2026-07-15T09:00:00")

    def test_disabled_day_yields_nothing(self) -> None:
        schedule = {2: DayHours(enabled=False, open=time(9, 0), close=time(17, 0))}
        slots = compute_available_slots(
            schedule=schedule,
            tz=TZ,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            busy=[],
            now=datetime(2026, 7, 1, tzinfo=TZ),
        )
        assert slots == []

    def test_busy_appointment_blocks_overlapping_slots(self) -> None:
        # A 9:30–10:00 appointment removes the 9:30 slot but leaves 9:00 and 10:00.
        schedule = {2: DayHours(enabled=True, open=time(9, 0), close=time(11, 0))}
        busy = [
            BusyInterval(
                start=datetime(2026, 7, 15, 9, 30, tzinfo=TZ),
                end=datetime(2026, 7, 15, 10, 0, tzinfo=TZ),
            )
        ]
        slots = compute_available_slots(
            schedule=schedule,
            tz=TZ,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            busy=busy,
            slot_minutes=30,
            now=datetime(2026, 7, 1, tzinfo=TZ),
        )
        assert [s.time for s in slots] == ["09:00", "10:00", "10:30"]

    def test_past_slots_are_excluded(self) -> None:
        schedule = {2: DayHours(enabled=True, open=time(9, 0), close=time(11, 0))}
        slots = compute_available_slots(
            schedule=schedule,
            tz=TZ,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            busy=[],
            slot_minutes=30,
            now=datetime(2026, 7, 15, 9, 45, tzinfo=TZ),
        )
        # 9:00 and 9:30 are in the past; only 10:00 and 10:30 remain.
        assert [s.time for s in slots] == ["10:00", "10:30"]

    def test_max_slots_caps_output(self) -> None:
        schedule = {2: DayHours(enabled=True, open=time(9, 0), close=time(17, 0))}
        slots = compute_available_slots(
            schedule=schedule,
            tz=TZ,
            start_date=date(2026, 7, 15),
            end_date=date(2026, 7, 15),
            busy=[],
            slot_minutes=30,
            now=datetime(2026, 7, 1, tzinfo=TZ),
            max_slots=3,
        )
        assert len(slots) == 3

    def test_default_schedule_skips_weekend(self) -> None:
        # 2026-07-18 is a Saturday, 2026-07-20 a Monday.
        schedule = parse_schedule(None)
        slots = compute_available_slots(
            schedule=schedule,
            tz=TZ,
            start_date=date(2026, 7, 18),
            end_date=date(2026, 7, 20),
            busy=[],
            now=datetime(2026, 7, 1, tzinfo=TZ),
        )
        assert slots, "Monday should produce slots"
        assert all(s.date == "2026-07-20" for s in slots)
