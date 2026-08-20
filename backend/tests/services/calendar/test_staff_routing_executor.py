"""End-to-end-ish test that the booking tool routes through staff assignment.

Exercises ``VoiceToolExecutor.execute("book_appointment", ...)`` for a
round-robin agent and asserts the booking is created against the *selected
staff member* (surfaced in the tool result and ``assigned_staff``). Booking is
local, then synchronized to the selected rep's Google Calendar.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

import app.db.session as db_session_module
from app.services.ai import base_tool_executor
from app.services.ai.tool_executor import VoiceToolExecutor


class _FakeStaff:
    def __init__(self, name: str, count: int = 0) -> None:
        self.id = uuid.uuid4()
        self.name = name
        self.user_id = 1
        self.skills: list[str] = []
        self.is_active = True
        self.priority = 0
        self.assignment_count = count
        self.last_assigned_at: datetime | None = None


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, pool: list[Any]) -> None:
        self._pool = pool

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None

    async def execute(self, _query: Any) -> _FakeResult:
        return _FakeResult(self._pool)

    def add(self, _obj: Any) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, _obj: Any) -> None:
        pass

    async def flush(self) -> None:
        pass


class _FakeBookingService:
    """Captures the workspace it was constructed for; books locally."""

    captured_workspace_id: uuid.UUID | None = None

    def __init__(self, workspace_id: uuid.UUID, timezone: str = "UTC", **_kwargs: Any) -> None:
        _FakeBookingService.captured_workspace_id = workspace_id

    async def book_appointment(self, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            success=True,
            error=None,
            alternative_slots=[],
        )

    async def close(self) -> None:
        pass


def _agent(strategy: str = "round_robin") -> Any:
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        assignment_strategy=strategy,
    )


@pytest.mark.parametrize(
    "confirmation_args",
    [{}, {"customer_confirmed": False}],
    ids=["missing", "false"],
)
@pytest.mark.asyncio
async def test_book_appointment_rejects_unconfirmed_before_assignment(
    confirmation_args: dict[str, bool],
) -> None:
    executor = VoiceToolExecutor(agent=_agent())

    result = await executor.execute(
        "book_appointment",
        {
            "date": "2099-01-15",
            "time": "14:00",
            "email": "caller@example.com",
            **confirmation_args,
        },
    )

    assert result["success"] is False
    assert result["error"] == "Explicit customer confirmation is required before booking"
    assert "exact date, time, timezone, duration, and invite email" in result["message"]
    assert executor.assigned_staff is None


@pytest.mark.asyncio
async def test_confirmed_booking_rechecks_and_rejects_new_google_conflict() -> None:
    _FakeBookingService.captured_workspace_id = None
    staff = _FakeStaff("Busy Rep")
    executor = VoiceToolExecutor(agent=_agent())

    with (
        patch.object(
            db_session_module,
            "AsyncSessionLocal",
            return_value=_FakeSession([staff]),
        ),
        patch.object(base_tool_executor, "BookingService", _FakeBookingService),
        patch(
            "app.services.google_calendar.is_time_available",
            return_value=False,
        ) as availability_recheck,
    ):
        result = await executor.execute(
            "book_appointment",
            {
                "date": "2099-01-15",
                "time": "14:00",
                "email": "caller@example.com",
                "customer_confirmed": True,
            },
        )

    assert result == {
        "success": False,
        "error": "That time is no longer available",
        "message": "Please offer another available time",
    }
    availability_recheck.assert_awaited_once()
    assert _FakeBookingService.captured_workspace_id is None


@pytest.mark.asyncio
async def test_book_appointment_routes_to_selected_staff() -> None:
    _FakeBookingService.captured_workspace_id = None
    # Bob has fewer assignments -> round-robin should pick Bob.
    pool = [
        _FakeStaff("Alice", count=3),
        _FakeStaff("Bob", count=0),
    ]

    agent = _agent()
    executor = VoiceToolExecutor(agent=agent)

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=_FakeSession(pool)),
        patch.object(base_tool_executor, "BookingService", _FakeBookingService),
        patch(
            "app.services.google_calendar.is_time_available",
            return_value=True,
        ),
    ):
        result = await executor.execute(
            "book_appointment",
            {
                "date": "2099-01-15",
                "time": "14:00",
                "email": "caller@example.com",
                "customer_confirmed": True,
            },
        )

    assert result["success"] is True
    # Booked locally for the agent's workspace, routed to the selected staff.
    assert _FakeBookingService.captured_workspace_id == agent.workspace_id
    assert executor.assigned_staff is not None
    assert executor.assigned_staff["name"] == "Bob"
    assert "Bob" in result["message"]


@pytest.mark.asyncio
async def test_default_agent_routes_to_team_enabled_staff() -> None:
    """The Team toggle creates a real booking assignment, not a display-only link."""
    staff = _FakeStaff("Terry Tech")
    agent = _agent("single")
    executor = VoiceToolExecutor(agent=agent)

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=_FakeSession([staff])),
        patch.object(base_tool_executor, "BookingService", _FakeBookingService),
        patch(
            "app.services.google_calendar.is_time_available",
            return_value=True,
        ),
    ):
        result = await executor.execute(
            "book_appointment",
            {
                "date": "2099-01-15",
                "time": "14:00",
                "email": "caller@example.com",
                "customer_confirmed": True,
            },
        )

    assert result["success"] is True
    assert executor.assigned_staff is not None
    assert executor.assigned_staff["name"] == "Terry Tech"
    assert executor.assigned_staff_id() == staff.id
