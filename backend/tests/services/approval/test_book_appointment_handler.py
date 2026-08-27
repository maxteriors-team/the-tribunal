"""Regression tests for the approved ``book_appointment`` handler.

``BookingService`` validates a slot while ``finalize_booking`` creates the CRM
appointment and mirrors it to Google. The live tool executors invoke that finalizer
in their ``post_booking_success`` hook, which the approval path never runs, so
an approved booking used to report success and land on no calendar.

These tests also pin the timezone: the ``date``/``time`` the model supplies are
wall-clock in the workspace's zone, not UTC.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.conversation_booking_draft import (
    BookingDraftCallType,
    ConversationBookingDraft,
)
from app.models.pending_action import PendingAction
from app.models.workspace import Workspace
from app.services.approval.approval_gate_service import (
    ApprovalGateService,
    BookAppointmentActionHandler,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

NEW_YORK = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def workspace_id():
    """A workspace torn down (cascading) after the test.

    The handler commits through the shared finalizer, so rows outlive a rollback
    and have to be deleted explicitly.
    """
    ws_id = uuid.uuid4()
    yield ws_id
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Workspace).where(Workspace.id == ws_id))
        await db.commit()


async def _workspace(
    db, ws_id: uuid.UUID, *, timezone: str | None = "America/New_York"
) -> Workspace:
    ws = Workspace(
        id=ws_id,
        name="Booking",
        slug=f"booking-{uuid.uuid4().hex[:8]}",
        settings={"timezone": timezone} if timezone else {},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Dana",
        last_name="Reyes",
        email="dana@example.com",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        status="new",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _conversation(db, workspace_id: uuid.UUID, contact_id: int) -> Conversation:
    conversation = Conversation(
        workspace_id=workspace_id,
        contact_id=contact_id,
        channel="sms",
        workspace_phone=f"+1512555{uuid.uuid4().int % 10000:04d}",
        contact_phone=f"+1512444{uuid.uuid4().int % 10000:04d}",
    )
    db.add(conversation)
    await db.flush()
    return conversation


def _action(
    workspace_id: uuid.UUID,
    payload: dict,
    context: dict,
) -> PendingAction:
    return PendingAction(
        workspace_id=workspace_id,
        action_type="book_appointment",
        action_payload=payload,
        description="Book the customer in",
        context=context,
        status="approved",
    )


async def test_approved_booking_creates_appointment_row(workspace_id) -> None:
    """An approved booking must land in ``appointments`` — that is the calendar."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        contact = await _contact(db, workspace.id)
        conversation = await _conversation(db, workspace.id, contact.id)

        action = _action(
            workspace.id,
            {"date": "2099-06-10", "time": "14:00", "email": "dana@example.com"},
            {"source": "text_conversation", "conversation_id": str(conversation.id)},
        )

        result = await BookAppointmentActionHandler().execute(db, action)

        assert result["status"] == "booked"
        rows = (
            (await db.execute(select(Appointment).where(Appointment.workspace_id == workspace.id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].contact_id == contact.id
        assert rows[0].status == AppointmentStatus.SCHEDULED


async def test_approved_booking_uses_workspace_timezone_not_utc(workspace_id) -> None:
    """2 PM in a New York workspace is 18:00 UTC, not 14:00 UTC."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        contact = await _contact(db, workspace.id)
        conversation = await _conversation(db, workspace.id, contact.id)

        action = _action(
            workspace.id,
            {"date": "2099-06-10", "time": "14:00"},
            {"source": "text_conversation", "conversation_id": str(conversation.id)},
        )

        result = await BookAppointmentActionHandler().execute(db, action)

        appointment = (
            (await db.execute(select(Appointment).where(Appointment.workspace_id == workspace.id)))
            .scalars()
            .one()
        )
        local = appointment.scheduled_at.astimezone(NEW_YORK)
        assert (local.hour, local.minute) == (14, 0)
        # EDT on 2099-06-10 → UTC-4.
        assert appointment.scheduled_at.astimezone(UTC).hour == 18
        assert result["timezone"] == "America/New_York"


async def test_booking_resolves_contact_from_voice_call_context(workspace_id) -> None:
    """Voice actions carry ``call_id``; the contact is found via the call message."""
    from app.models.conversation import Message

    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        contact = await _contact(db, workspace.id)
        conversation = await _conversation(db, workspace.id, contact.id)
        call_control_id = f"call-{uuid.uuid4().hex[:10]}"
        db.add(
            Message(
                conversation_id=conversation.id,
                direction="outbound",
                channel="voice",
                body="AI call",
                provider_message_id=call_control_id,
            )
        )
        await db.flush()

        action = _action(
            workspace.id,
            {"date": "2099-06-10", "time": "09:30"},
            {"source": "voice_call", "call_id": call_control_id},
        )

        result = await BookAppointmentActionHandler().execute(db, action)

        assert result["status"] == "booked"
        appointment = (
            (await db.execute(select(Appointment).where(Appointment.workspace_id == workspace.id)))
            .scalars()
            .one()
        )
        assert appointment.contact_id == contact.id


async def test_unresolvable_contact_reports_error_instead_of_phantom_booking(workspace_id) -> None:
    """No contact means no appointment — and the action must not claim success."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        action = _action(
            workspace.id,
            {"date": "2099-06-10", "time": "14:00"},
            {"source": "text_conversation"},
        )

        result = await BookAppointmentActionHandler().execute(db, action)

        assert result["error"] == "contact_not_found"
        rows = (
            (await db.execute(select(Appointment).where(Appointment.workspace_id == workspace.id)))
            .scalars()
            .all()
        )
        assert rows == []


async def test_approved_sms_booking_rejects_a_replaced_confirmation_draft(
    workspace_id,
) -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        contact = await _contact(db, workspace.id)
        conversation = await _conversation(db, workspace.id, contact.id)
        prepared_at = datetime.now(UTC)
        db.add(
            ConversationBookingDraft(
                conversation_id=conversation.id,
                workspace_id=workspace.id,
                date=datetime(2099, 6, 10).date(),
                time=datetime(2099, 6, 10, 14).time(),
                timezone="America/New_York",
                duration_minutes=30,
                call_type=BookingDraftCallType.PHONE_CALL,
                email="dana@example.com",
                confirmation_text="Original summary",
                prepared_at=prepared_at,
            )
        )
        await db.flush()
        action = _action(
            workspace.id,
            {
                "date": "2099-06-10",
                "time": "14:00",
                "email": "dana@example.com",
                "duration_minutes": 30,
                "call_type": "phone_call",
                "booking_draft_prepared_at": (prepared_at - timedelta(seconds=1)).isoformat(),
            },
            {"source": "text_conversation", "conversation_id": str(conversation.id)},
        )

        result = await BookAppointmentActionHandler().execute(db, action)

        assert result["error"] == "booking_draft_changed"
        appointments = (
            (await db.execute(select(Appointment).where(Appointment.workspace_id == workspace.id)))
            .scalars()
            .all()
        )
        assert appointments == []


async def test_approved_sms_booking_consumes_the_confirmed_draft(workspace_id, monkeypatch) -> None:
    def discard_notification(coroutine, **_kwargs) -> None:
        coroutine.close()

    monkeypatch.setattr(
        "app.services.appointments.booking_finalizer.spawn_background_task",
        discard_notification,
    )
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        contact = await _contact(db, workspace.id)
        conversation = await _conversation(db, workspace.id, contact.id)
        prepared_at = datetime.now(UTC)
        draft = ConversationBookingDraft(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            date=datetime(2099, 6, 11).date(),
            time=datetime(2099, 6, 11, 14).time(),
            timezone="America/New_York",
            duration_minutes=30,
            call_type=BookingDraftCallType.VIDEO_CALL,
            email="dana@example.com",
            confirmation_text="Confirmed summary",
            prepared_at=prepared_at,
        )
        db.add(draft)
        await db.flush()
        action = _action(
            workspace.id,
            {
                "date": "2099-06-11",
                "time": "14:00",
                "email": "dana@example.com",
                "duration_minutes": 30,
                "call_type": "video_call",
                "booking_draft_prepared_at": prepared_at.isoformat(),
            },
            {"source": "text_conversation", "conversation_id": str(conversation.id)},
        )

        result = await BookAppointmentActionHandler().execute(db, action)

        assert result["status"] == "booked"
        appointment = await db.scalar(
            select(Appointment).where(Appointment.workspace_id == workspace.id)
        )
        assert appointment is not None
        assert appointment.service_type == "video_call"
        assert await db.get(ConversationBookingDraft, conversation.id) is None


async def test_handler_error_marks_action_failed_not_executed(workspace_id) -> None:
    """A handler error must not leave the action looking like it succeeded."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, workspace_id)
        action = _action(
            workspace.id,
            {"date": "not-a-date", "time": "14:00"},
            {"source": "text_conversation"},
        )
        db.add(action)
        await db.flush()

        result = await ApprovalGateService().execute_approved_action(db, action)

        assert result["error"] == "contact_not_found"
        assert action.status == "failed"
