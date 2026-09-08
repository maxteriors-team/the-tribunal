"""Appointment reminder template rendering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import MessageStatus
from app.models.field_service import Job
from app.models.workspace import Workspace
from app.services.calendar import reminder_service
from app.services.calendar.reminder_service import render_job_reminder_body, render_reminder_body


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
async def test_manual_appointment_key_changes_after_reschedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    appointment = Appointment(
        id=42,
        contact_id=1,
        scheduled_at=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
        anytime=False,
        duration_minutes=30,
    )
    contact = Contact(id=1, workspace_id=workspace_id, first_name="Greg")
    workspace = Workspace(id=workspace_id, name="Maxteriors Lighting")
    delivery = AsyncMock(
        return_value={
            "success": True,
            "message": "Reminder already sent for this schedule",
            "sent_to": "***-***-0142",
            "already_sent": True,
        }
    )
    monkeypatch.setattr(reminder_service, "_send_sms_reminder", delivery)
    db = AsyncMock()

    await reminder_service.send_appointment_reminder(db, appointment, workspace, contact, None)
    first_key = delivery.await_args.kwargs["idempotency_key"]
    appointment.scheduled_at += timedelta(days=1)
    await reminder_service.send_appointment_reminder(db, appointment, workspace, contact, None)

    assert delivery.await_args.kwargs["idempotency_key"] != first_key
    db.execute.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_job_reminder_uses_stock_customer_copy_in_workspace_timezone() -> None:
    workspace_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=1,
        title="Lighting installation",
        scheduled_start=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
    )
    contact = Contact(id=1, workspace_id=workspace_id, first_name="Greg", last_name="Bartlett")
    workspace = Workspace(
        id=workspace_id,
        name="Maxteriors Lighting",
        settings={"timezone": "America/New_York"},
    )

    assert render_job_reminder_body(job, contact, workspace) == (
        "Hi Greg, this is a reminder of your scheduled visit with Maxteriors Lighting "
        "on Tuesday, August 18 at 12:00 PM. Reply here if you need to make changes."
    )


@pytest.mark.asyncio
async def test_job_reminder_sends_stock_copy_with_staff_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=1,
        title="Caller-controlled title is not included",
        scheduled_start=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
    )
    contact = Contact(
        id=1,
        workspace_id=workspace_id,
        first_name="Greg",
        phone_number="+15125550142",
    )
    workspace = Workspace(
        id=workspace_id,
        name="Maxteriors Lighting",
        settings={"timezone": "America/New_York"},
    )
    sms = MagicMock()
    sms.send_message = AsyncMock(return_value=MagicMock(id=uuid.uuid4(), status=MessageStatus.SENT))
    sms.close = AsyncMock()
    sms_factory = MagicMock(return_value=sms)
    monkeypatch.setattr(reminder_service.settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(
        reminder_service._opt_out_manager,
        "check_opt_out",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        reminder_service,
        "resolve_from_number",
        AsyncMock(return_value="+15125550999"),
    )
    idempotency = AsyncMock(return_value=SimpleNamespace(should_skip=False, existing_message=None))
    monkeypatch.setattr(reminder_service, "resolve_message_idempotency", idempotency)
    monkeypatch.setattr(reminder_service, "TelnyxSMSService", sms_factory)
    db = AsyncMock()

    result = await reminder_service.send_job_reminder(
        db,
        job,
        workspace,
        contact,
        sender_user_id=17,
        sender_display_name="Calendar Staff",
    )

    assert result == {
        "success": True,
        "message": "Reminder sent",
        "sent_to": "***-***-0142",
        "already_sent": False,
    }
    send = sms.send_message.await_args.kwargs
    assert send["to_number"] == "+15125550142"
    assert send["from_number"] == "+15125550999"
    assert send["sender_user_id"] == 17
    assert send["sender_display_name"] == "Calendar Staff"
    assert "Caller-controlled" not in send["body"]
    first_key = send["idempotency_key"]

    existing = MagicMock(id=uuid.uuid4(), status=MessageStatus.SENT)
    idempotency.return_value = SimpleNamespace(should_skip=True, existing_message=existing)
    replay = await reminder_service.send_job_reminder(db, job, workspace, contact)
    assert replay == {
        "success": True,
        "message": "Reminder already sent for this schedule",
        "sent_to": "***-***-0142",
        "already_sent": True,
    }
    assert sms.send_message.await_count == 1

    job.scheduled_start += timedelta(days=1)
    idempotency.return_value = SimpleNamespace(should_skip=False, existing_message=None)
    await reminder_service.send_job_reminder(db, job, workspace, contact)
    assert sms.send_message.await_count == 2
    assert sms.send_message.await_args.kwargs["idempotency_key"] != first_key
    assert sms.close.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("consent_status", "global_opt_out"),
    [("unknown", True), ("opted_out", False)],
)
async def test_job_reminder_honors_any_sms_opt_out(
    monkeypatch: pytest.MonkeyPatch,
    consent_status: str,
    global_opt_out: bool,
) -> None:
    workspace_id = uuid.uuid4()
    job = Job(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=1,
        title="Visit",
        scheduled_start=datetime(2026, 8, 18, 16, 0, tzinfo=UTC),
    )
    contact = Contact(
        id=1,
        workspace_id=workspace_id,
        first_name="Greg",
        phone_number="+15125550142",
        sms_consent_status=consent_status,
    )
    workspace = Workspace(id=workspace_id, name="Maxteriors Lighting")
    sms_factory = MagicMock()
    monkeypatch.setattr(reminder_service.settings, "telnyx_api_key", "test-key")
    monkeypatch.setattr(
        reminder_service._opt_out_manager,
        "check_opt_out",
        AsyncMock(return_value=global_opt_out),
    )
    monkeypatch.setattr(reminder_service, "TelnyxSMSService", sms_factory)

    result = await reminder_service.send_job_reminder(AsyncMock(), job, workspace, contact)

    assert result == {
        "success": False,
        "message": "Contact has opted out of SMS",
        "sent_to": None,
    }
    sms_factory.assert_not_called()


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
