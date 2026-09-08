"""Unit coverage for the calendar's manual job-reminder operation."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.workspace import Workspace
from app.services.jobs import JobService


@pytest.mark.asyncio
async def test_send_reminder_delegates_to_shared_stock_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = Workspace(id=uuid.uuid4(), name="Maxteriors Lighting")
    contact = Contact(
        id=42,
        workspace_id=workspace.id,
        first_name="Helen",
        phone_number="+15125550142",
    )
    job = Job(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        contact_id=contact.id,
        contact=contact,
        title="Scheduled visit",
        status=JobStatus.SCHEDULED,
        scheduled_start=datetime.now(UTC) + timedelta(days=1),
        scheduled_end=datetime.now(UTC) + timedelta(days=1, hours=2),
    )
    service = JobService(AsyncMock())
    load = AsyncMock(return_value=job)
    sender = AsyncMock(
        return_value={"success": True, "message": "Reminder sent", "sent_to": "***-***-0142"}
    )
    monkeypatch.setattr(service, "_load", load)
    monkeypatch.setattr("app.services.calendar.reminder_service.send_job_reminder", sender)

    result = await service.send_reminder(
        job.id,
        workspace.id,
        workspace,
        sender_user_id=17,
        sender_display_name="Calendar Staff",
    )

    assert result["success"] is True
    assert sender.await_args.kwargs["job"] is job
    assert sender.await_args.kwargs["contact"] is contact
    assert sender.await_args.kwargs["sender_user_id"] == 17
    assert sender.await_args.kwargs["sender_display_name"] == "Calendar Staff"


@pytest.mark.asyncio
async def test_send_reminder_rejects_past_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = Workspace(id=uuid.uuid4(), name="Maxteriors Lighting")
    contact = Contact(id=42, workspace_id=workspace.id, first_name="Helen")
    job = Job(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        contact_id=contact.id,
        contact=contact,
        title="Past visit",
        status=JobStatus.SCHEDULED,
        scheduled_start=datetime.now(UTC) - timedelta(hours=2),
        scheduled_end=datetime.now(UTC) - timedelta(hours=1),
    )
    service = JobService(AsyncMock())
    monkeypatch.setattr(service, "_load", AsyncMock(return_value=job))

    with pytest.raises(HTTPException) as excinfo:
        await service.send_reminder(job.id, workspace.id, workspace)

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "Reminders can only be sent for upcoming jobs"
