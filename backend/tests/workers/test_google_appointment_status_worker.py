"""Unit tests for the time-based Google appointment completion gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.workers.google_appointment_status_worker import appointment_is_due

NOW = datetime(2099, 1, 14, 18, 0, tzinfo=UTC)
GRACE = timedelta(minutes=15)


def test_due_when_end_plus_grace_has_passed() -> None:
    # 30-min appt ended 16:30; +15m grace = 16:45 < 18:00 now -> due.
    start = datetime(2099, 1, 14, 16, 0, tzinfo=UTC)
    assert appointment_is_due(start, 30, NOW, GRACE) is True


def test_not_due_inside_grace_window() -> None:
    # Ends 17:50, +15m grace = 18:05 > 18:00 now -> not due.
    start = datetime(2099, 1, 14, 17, 20, tzinfo=UTC)
    assert appointment_is_due(start, 30, NOW, GRACE) is False


def test_not_due_for_future_appointment() -> None:
    start = datetime(2099, 1, 14, 19, 0, tzinfo=UTC)
    assert appointment_is_due(start, 30, NOW, GRACE) is False
