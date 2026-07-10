"""Unit tests for the Google Calendar -> appointment status differ."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import structlog

from app.models.appointment import AppointmentStatus
from app.services.calendar.google import sync as sync_module

LOG = structlog.get_logger()


class _FakeResult:
    def __init__(self, obj: Any) -> None:
        self._obj = obj

    def scalar_one_or_none(self) -> Any:
        return self._obj


class _FakeDB:
    def __init__(self, appointment: Any) -> None:
        self._appointment = appointment

    async def execute(self, *_args: Any, **_kwargs: Any) -> _FakeResult:
        return _FakeResult(self._appointment)


def _appointment(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": 1,
        "status": AppointmentStatus.SCHEDULED,
        "scheduled_at": datetime(2099, 1, 14, 14, 0, tzinfo=UTC),
        "external_event_id": "evt_1",
        "calendar_provider": "google",
        "sync_status": "pending",
        "last_synced_at": None,
        "reminder_sent_at": datetime(2099, 1, 13, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_cancelled_event_marks_appointment_cancelled() -> None:
    appt = _appointment()
    db = _FakeDB(appt)
    changed = await sync_module._apply_event_change(
        db, "ws", {"id": "evt_1", "status": "cancelled"}, LOG
    )
    assert changed is True
    assert appt.status == AppointmentStatus.CANCELLED
    assert appt.sync_status == "synced"


@pytest.mark.asyncio
async def test_cancelled_event_ignored_when_already_terminal() -> None:
    appt = _appointment(status=AppointmentStatus.COMPLETED)
    db = _FakeDB(appt)
    changed = await sync_module._apply_event_change(
        db, "ws", {"id": "evt_1", "status": "cancelled"}, LOG
    )
    assert changed is False
    assert appt.status == AppointmentStatus.COMPLETED


@pytest.mark.asyncio
async def test_reschedule_updates_time_and_rearms_reminders() -> None:
    appt = _appointment()
    db = _FakeDB(appt)
    event = {
        "id": "evt_1",
        "status": "confirmed",
        "start": {"dateTime": "2099-01-14T16:00:00Z"},
    }
    changed = await sync_module._apply_event_change(db, "ws", event, LOG)
    assert changed is True
    assert appt.scheduled_at == datetime(2099, 1, 14, 16, 0, tzinfo=UTC)
    assert appt.reminder_sent_at is None


@pytest.mark.asyncio
async def test_unchanged_start_is_noop() -> None:
    appt = _appointment()
    db = _FakeDB(appt)
    event = {
        "id": "evt_1",
        "status": "confirmed",
        "start": {"dateTime": "2099-01-14T14:00:00Z"},
    }
    changed = await sync_module._apply_event_change(db, "ws", event, LOG)
    assert changed is False


@pytest.mark.asyncio
async def test_unknown_event_returns_false() -> None:
    db = _FakeDB(None)
    changed = await sync_module._apply_event_change(
        db, "ws", {"id": "nope", "status": "cancelled"}, LOG
    )
    assert changed is False


class _FakeClient:
    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.calls: list[dict[str, Any]] = []

    async def list_events(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self._pages[len(self.calls) - 1]


@pytest.mark.asyncio
async def test_fetch_changes_paginates_and_returns_sync_token() -> None:
    client = _FakeClient(
        [
            {"items": [{"id": "a"}], "nextPageToken": "p2"},
            {"items": [{"id": "b"}], "nextSyncToken": "SYNC2"},
        ]
    )
    events, token = await sync_module._fetch_changes(client, "SYNC1")  # type: ignore[arg-type]
    assert [e["id"] for e in events] == ["a", "b"]
    assert token == "SYNC2"
    # Incremental fetch uses the sync token, not timeMin.
    assert client.calls[0]["sync_token"] == "SYNC1"
    assert client.calls[0]["time_min_iso"] is None
