"""Appointment reminder template rendering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.services.calendar import reminder_service
from app.services.calendar.reminder_service import render_reminder_body


def test_anytime_reminder_renders_date_without_placeholder_hour() -> None:
    appointment = Appointment(
        id=42,
        contact_id=1,
        scheduled_at=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
        anytime=True,
        duration_minutes=30,
    )
    contact = Contact(id=1, workspace_id=uuid.uuid4(), first_name="Greg", last_name="Bartlett")
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        settings={"timezone": "America/New_York"},
    )

    body = render_reminder_body(
        "Hi {first_name}, your appointment is {appointment_datetime} ({appointment_time}).",
        contact,
        appointment,
        workspace,
        None,
    )

    assert body == "Hi Greg, your appointment is Tuesday, August 18 at any time (any time)."
    assert "12:00 PM" not in body


@pytest.mark.asyncio
async def test_anytime_email_forwards_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    send_email = AsyncMock(return_value=True)
    monkeypatch.setattr(reminder_service, "send_appointment_reminder_email", send_email)
    appointment = Appointment(
        id=42,
        contact_id=1,
        scheduled_at=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
        anytime=True,
        duration_minutes=30,
    )
    contact = Contact(
        id=1,
        workspace_id=uuid.uuid4(),
        first_name="Greg",
        last_name="Bartlett",
        email="greg@example.com",
    )
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        settings={"timezone": "America/New_York"},
    )

    assert await reminder_service.send_appointment_reminder_email_for(
        appointment, workspace, contact, None
    )
    assert send_email.await_args.kwargs["anytime"] is True
