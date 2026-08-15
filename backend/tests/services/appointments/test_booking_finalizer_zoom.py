"""Zoom-specific booking finalizer behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.models.appointment import Appointment, AppointmentStatus
from app.models.bookable_staff import BookableStaff
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.appointments.booking_finalizer import sync_appointment_external_events
from app.services.google_calendar import GoogleEvent
from app.services.zoom import ZoomError, ZoomMeeting

ZOOM_JOIN_URL = "https://us06web.zoom.us/j/12345678901?pwd=opaque"


def _records() -> tuple[Appointment, Contact, Workspace, BookableStaff]:
    workspace_id = uuid.uuid4()
    appointment = Appointment(
        workspace_id=workspace_id,
        contact_id=17,
        status=AppointmentStatus.SCHEDULED,
        service_type="video_call",
        scheduled_at=datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
        duration_minutes=30,
        sync_status="pending",
    )
    appointment.id = 42
    contact = Contact(
        id=17,
        workspace_id=workspace_id,
        first_name="Test",
        last_name="Lead",
        email="lead@example.com",
    )
    workspace = Workspace(
        id=workspace_id,
        name="Maxteriors",
        settings={"timezone": "America/New_York"},
    )
    staff = BookableStaff(
        workspace_id=workspace_id,
        user_id=77,
        name="Maxteriors",
        email="max@maxteriors.com",
    )
    return appointment, contact, workspace, staff


@pytest.mark.asyncio
async def test_zoom_link_is_saved_and_google_meet_is_not_requested() -> None:
    appointment, contact, workspace, staff = _records()
    db = AsyncMock()
    create_google_event = AsyncMock(
        return_value=GoogleEvent(
            event_id="google-event",
            html_link="https://calendar.google.com/event?eid=opaque",
            meet_link=None,
        )
    )
    with (
        patch("app.services.zoom.zoom_configured_for_user", new=AsyncMock(return_value=True)),
        patch(
            "app.services.zoom.create_meeting",
            new=AsyncMock(return_value=ZoomMeeting("12345678901", ZOOM_JOIN_URL)),
        ) as create_zoom,
        patch("app.services.google_calendar.create_event", new=create_google_event),
    ):
        await sync_appointment_external_events(
            db,
            appointment=appointment,
            contact=contact,
            workspace=workspace,
            staff=staff,
            log=Mock(),
        )

    create_zoom.assert_awaited_once()
    zoom_topic = create_zoom.await_args.kwargs["topic"]
    assert zoom_topic == "Maxteriors consultation"
    assert contact.full_name
    assert contact.full_name not in zoom_topic
    assert create_google_event.await_args.kwargs["conference"] is False
    assert create_google_event.await_args.kwargs["location"] == f"Zoom: {ZOOM_JOIN_URL}"
    assert appointment.meeting_url == ZOOM_JOIN_URL
    assert appointment.google_calendar_event_id == "google-event"
    assert appointment.sync_status == "synced"
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_zoom_failure_falls_back_to_google_meet() -> None:
    appointment, contact, workspace, staff = _records()
    db = AsyncMock()
    meet_url = "https://meet.google.com/abc-defg-hij"
    create_google_event = AsyncMock(
        return_value=GoogleEvent(
            event_id="google-event",
            html_link="https://calendar.google.com/event?eid=opaque",
            meet_link=meet_url,
        )
    )
    with (
        patch("app.services.zoom.zoom_configured_for_user", new=AsyncMock(return_value=True)),
        patch(
            "app.services.zoom.create_meeting",
            new=AsyncMock(side_effect=ZoomError("provider detail")),
        ),
        patch("app.services.google_calendar.create_event", new=create_google_event),
    ):
        await sync_appointment_external_events(
            db,
            appointment=appointment,
            contact=contact,
            workspace=workspace,
            staff=staff,
            log=Mock(),
        )

    assert create_google_event.await_args.kwargs["conference"] is True
    assert appointment.meeting_url == meet_url
    assert appointment.sync_status == "synced"
