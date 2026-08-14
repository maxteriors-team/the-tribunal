"""Lifecycle tests for combined Google Calendar and Zoom synchronization."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models.bookable_staff import BookableStaff
from app.services.appointments.external_sync import (
    delete_external_events,
    update_external_events,
)
from app.services.zoom import ZoomError


def _appointment() -> SimpleNamespace:
    appointment = SimpleNamespace(
        id=42,
        bookable_staff_id="staff-id",
        meeting_url="https://us06web.zoom.us/j/12345678901?pwd=opaque",
        google_calendar_event_id="google-event-id",
        scheduled_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
        duration_minutes=30,
        sync_status="synced",
        sync_error=None,
        last_synced_at=None,
    )
    appointment.bookable_staff = BookableStaff(user_id=77)
    return appointment


@pytest.mark.asyncio
async def test_reschedule_updates_zoom_and_google() -> None:
    appointment = _appointment()
    db = AsyncMock()
    log = Mock()
    with (
        patch("app.services.zoom.update_meeting", new=AsyncMock()) as update_zoom,
        patch("app.services.google_calendar.update_event_time", new=AsyncMock()) as update_google,
    ):
        await update_external_events(
            db,
            appointment=appointment,
            workspace=SimpleNamespace(settings={"timezone": "America/New_York"}),
            log=log,
        )

    update_zoom.assert_awaited_once_with(
        meeting_id="12345678901",
        starts_at=appointment.scheduled_at,
        duration_minutes=30,
        timezone="America/New_York",
    )
    update_google.assert_awaited_once_with(
        db,
        user_id=77,
        event_id="google-event-id",
        starts_at=appointment.scheduled_at,
        duration_minutes=30,
        timezone="America/New_York",
    )
    assert appointment.sync_status == "synced"
    assert appointment.sync_error is None
    assert appointment.last_synced_at is not None


@pytest.mark.asyncio
async def test_reschedule_records_zoom_failure_after_google_succeeds() -> None:
    appointment = _appointment()
    db = AsyncMock()
    with (
        patch(
            "app.services.zoom.update_meeting",
            new=AsyncMock(side_effect=ZoomError("provider detail")),
        ),
        patch("app.services.google_calendar.update_event_time", new=AsyncMock()),
    ):
        await update_external_events(
            db,
            appointment=appointment,
            workspace=SimpleNamespace(settings={"timezone": "America/New_York"}),
            log=Mock(),
        )

    assert appointment.sync_status == "failed"
    assert appointment.sync_error == "Zoom meeting update failed"
    assert "provider detail" not in appointment.sync_error


@pytest.mark.asyncio
async def test_cancellation_deletes_zoom_and_google() -> None:
    appointment = _appointment()
    db = AsyncMock()
    with (
        patch("app.services.zoom.delete_meeting", new=AsyncMock()) as delete_zoom,
        patch("app.services.google_calendar.delete_event", new=AsyncMock()) as delete_google,
    ):
        await delete_external_events(db, appointment=appointment, log=Mock())

    delete_zoom.assert_awaited_once_with(meeting_id="12345678901")
    delete_google.assert_awaited_once_with(
        db,
        user_id=77,
        event_id="google-event-id",
    )
    assert appointment.sync_status == "cancelled"
    assert appointment.sync_error is None
