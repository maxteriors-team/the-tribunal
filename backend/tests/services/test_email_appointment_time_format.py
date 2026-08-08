"""Appointment times in owner notifications must render in the workspace zone.

``appointments.scheduled_at`` is a UTC-normalised ``timestamptz``. The booked
notification used to ``strftime`` it directly with a hardcoded " UTC" suffix, so
an Eastern operator was emailed a time four or five hours off their own calendar.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.email import format_local_datetime


def test_utc_value_is_converted_to_eastern() -> None:
    # 18:00 UTC on a summer day is 2:00 PM EDT.
    value = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
    assert format_local_datetime(value, "America/New_York") == "Wednesday, June 10 at 2:00 PM EDT"


def test_winter_value_uses_est_label() -> None:
    value = datetime(2026, 1, 14, 19, 0, tzinfo=UTC)
    assert (
        format_local_datetime(value, "America/New_York") == "Wednesday, January 14 at 2:00 PM EST"
    )


def test_other_zones_are_honoured() -> None:
    value = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
    assert format_local_datetime(value, "America/Denver") == "Wednesday, June 10 at 12:00 PM MDT"


def test_naive_value_is_treated_as_utc() -> None:
    naive = datetime(2026, 6, 10, 18, 0)
    aware = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
    assert format_local_datetime(naive, "America/New_York") == format_local_datetime(
        aware, "America/New_York"
    )


def test_missing_or_bad_timezone_falls_back_to_eastern() -> None:
    value = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
    assert format_local_datetime(value, None) == "Wednesday, June 10 at 2:00 PM EDT"
    assert format_local_datetime(value, "Not/AZone") == "Wednesday, June 10 at 2:00 PM EDT"


def test_never_labels_a_converted_time_as_utc() -> None:
    value = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
    assert "UTC" not in format_local_datetime(value, "America/New_York")
