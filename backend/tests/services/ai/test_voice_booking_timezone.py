"""Regression tests for the timezone a voice booking is stored at.

The ``date``/``time`` the model passes to ``book_appointment`` are wall-clock in
the agent's timezone — that is the zone ``BookingService`` generated the offered
slots in. Stamping them UTC shifts every voice booking by the UTC offset, so a
customer who agreed to 2 PM lands on the calendar at 10 AM.
"""

from __future__ import annotations

import uuid
from datetime import UTC
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, select

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.appointment import Appointment
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.workspace import Workspace
from app.services.ai.base_tool_executor import BaseToolExecutor
from app.services.ai.tool_executor import VoiceToolExecutor

NEW_YORK = ZoneInfo("America/New_York")


def test_get_timezone_falls_back_to_new_york_for_garbage() -> None:
    executor = BaseToolExecutor(agent=SimpleNamespace(), timezone="Not/AZone")
    assert executor._get_timezone() == NEW_YORK


def test_get_timezone_honours_configured_zone() -> None:
    executor = BaseToolExecutor(agent=SimpleNamespace(), timezone="America/Denver")
    assert executor._get_timezone() == ZoneInfo("America/Denver")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_voice_booking_stored_in_agent_timezone_not_utc() -> None:
    """A 2 PM Eastern booking must persist as 18:00 UTC, not 14:00 UTC."""
    await engine.dispose()
    try:
        async with AsyncSessionLocal() as db:
            workspace = Workspace(
                id=uuid.uuid4(),
                name="Voice TZ",
                slug=f"voice-tz-{uuid.uuid4().hex[:8]}",
                settings={"timezone": "America/New_York"},
            )
            db.add(workspace)
            await db.flush()

            phone = f"+1512555{uuid.uuid4().int % 10000:04d}"
            contact = Contact(
                workspace_id=workspace.id,
                first_name="Sam",
                phone_number=phone,
                phone_hash=hash_phone(phone),
                status="new",
            )
            db.add(contact)
            await db.flush()

            conversation = Conversation(
                workspace_id=workspace.id,
                contact_id=contact.id,
                channel="voice",
                workspace_phone=f"+1512333{uuid.uuid4().int % 10000:04d}",
                contact_phone=phone,
            )
            db.add(conversation)
            await db.flush()

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
            await db.commit()

        executor = VoiceToolExecutor(
            agent=SimpleNamespace(id=None, workspace_id=workspace.id),
            timezone="America/New_York",
            call_control_id=call_control_id,
            workspace_id=workspace.id,
        )
        await executor.post_booking_success(
            SimpleNamespace(booking_uid=None, booking_id=None),
            "2099-06-10",
            "14:00",
            "sam@example.com",
            30,
            None,
        )

        async with AsyncSessionLocal() as db:
            appointment = (
                (
                    await db.execute(
                        select(Appointment).where(Appointment.workspace_id == workspace.id)
                    )
                )
                .scalars()
                .one()
            )
            local = appointment.scheduled_at.astimezone(NEW_YORK)
            assert (local.hour, local.minute) == (14, 0)
            # EDT on 2099-06-10 → UTC-4.
            assert appointment.scheduled_at.astimezone(UTC).hour == 18

        # The executor commits through its own session, so tear the fixture data
        # down explicitly (workspace delete cascades to the rest).
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Workspace).where(Workspace.id == workspace.id))
            await db.commit()
    finally:
        await engine.dispose()
