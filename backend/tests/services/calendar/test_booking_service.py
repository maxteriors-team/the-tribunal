"""Tests for the self-contained BookingService.

Verifies availability is computed from workspace business hours minus busy CRM
appointments, and that booking is local (no external ids), using an injected
fake session factory so no database is required.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.services.calendar.booking import BookingService

TZ = ZoneInfo("America/New_York")


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _RowsResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    """Returns queued results in call order: business hours, then busy rows."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, _query: Any) -> Any:
        return self._results.pop(0)


def _factory(results: list[Any]) -> Any:
    return lambda: _FakeSession(results)


@pytest.mark.asyncio
async def test_check_availability_uses_business_hours_and_busy_set() -> None:
    # Wednesday 2026-07-15, business hours 9–11, one 9:30–10:00 appointment busy.
    settings = {
        "business_hours": {
            "schedule": {"wednesday": {"enabled": True, "open": "09:00", "close": "11:00"}}
        }
    }
    busy_rows = [(datetime(2026, 7, 15, 9, 30, tzinfo=TZ), 30)]
    service = BookingService(
        uuid.uuid4(),
        timezone="America/New_York",
        session_factory=_factory([_ScalarResult(settings), _RowsResult(busy_rows)]),
    )

    # Pin ``now`` to midnight of the test day so no morning slot is filtered as
    # past — the assertion must not depend on the wall-clock time of the run.
    result = await service.check_availability(
        "2026-07-15", "2026-07-15", now=datetime(2026, 7, 15, 0, 0, tzinfo=TZ)
    )

    assert result.success is True
    times = [s.time for s in result.slots]
    # 9:30 is blocked by the busy appointment; 9:00, 10:00, 10:30 remain.
    assert times == ["09:00", "10:00", "10:30"]


@pytest.mark.asyncio
async def test_check_availability_defaults_when_no_business_hours() -> None:
    # No settings row -> default Mon–Fri 9–5. 2026-07-15 is a Wednesday.
    service = BookingService(
        uuid.uuid4(),
        session_factory=_factory([_ScalarResult(None), _RowsResult([])]),
    )
    # Pin ``now`` to midnight so the first slots aren't dropped as past.
    result = await service.check_availability(
        "2026-07-15", max_slots=3, now=datetime(2026, 7, 15, 0, 0, tzinfo=TZ)
    )
    assert result.success is True
    assert [s.time for s in result.slots] == ["09:00", "09:30", "10:00"]


@pytest.mark.asyncio
async def test_check_availability_rejects_bad_date() -> None:
    service = BookingService(uuid.uuid4(), session_factory=_factory([]))
    result = await service.check_availability("not-a-date")
    assert result.success is False
    assert "Invalid date" in (result.error or "")


@pytest.mark.asyncio
async def test_book_appointment_is_local_with_no_external_ids() -> None:
    service = BookingService(uuid.uuid4(), session_factory=_factory([]))
    result = await service.book_appointment(
        date_str="2026-07-15",
        time_str="14:00",
        email="a@b.com",
        contact_name="Alice",
    )
    assert result.success is True
    assert result.booking_uid is None
    assert result.booking_id is None


@pytest.mark.asyncio
async def test_book_appointment_pre_validate_offers_alternatives_when_taken() -> None:
    # Requested 09:30 but it's busy; pre_validate should fail with alternatives.
    settings = {
        "business_hours": {
            "schedule": {"wednesday": {"enabled": True, "open": "09:00", "close": "11:00"}}
        }
    }
    busy_rows = [(datetime(2026, 7, 15, 9, 30, tzinfo=TZ), 30)]
    service = BookingService(
        uuid.uuid4(),
        session_factory=_factory([_ScalarResult(settings), _RowsResult(busy_rows)]),
    )
    result = await service.book_appointment(
        date_str="2026-07-15",
        time_str="09:30",
        email="a@b.com",
        contact_name="Alice",
        pre_validate=True,
        # Pin ``now`` to midnight so the morning slots aren't filtered as past
        # regardless of the wall-clock time the suite runs at.
        now=datetime(2026, 7, 15, 0, 0, tzinfo=TZ),
    )
    assert result.success is False
    assert result.alternative_slots
    assert "09:30" not in [s.time for s in result.alternative_slots]
