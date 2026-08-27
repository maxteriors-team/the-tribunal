"""PostgreSQL coverage for persisted SMS booking drafts."""

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from sqlalchemy import Text, delete, func, select, type_coerce

from app.core.encryption import hash_phone
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.conversation import Conversation, MessageChannel
from app.models.conversation_booking_draft import ConversationBookingDraft
from app.models.workspace import Workspace
from app.services.ai.text_tool_executor import TextToolExecutor

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


@pytest.fixture
async def workspace_id() -> AsyncIterator[uuid.UUID]:
    value = uuid.uuid4()
    yield value
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Workspace).where(Workspace.id == value))
        await db.commit()


async def test_prepare_booking_atomically_upserts_one_encrypted_draft(workspace_id) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            Workspace(
                id=workspace_id,
                name="Booking Draft",
                slug=f"booking-draft-{uuid.uuid4().hex[:8]}",
                settings={"timezone": "America/New_York"},
            )
        )
        await db.flush()
        contact = Contact(
            workspace_id=workspace_id,
            first_name="Draft",
            last_name="Lead",
            phone_number="+15125550123",
            phone_hash=hash_phone("+15125550123"),
            email="draft@example.com",
            status="new",
        )
        db.add(contact)
        await db.flush()
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact.id,
            workspace_phone="+15125550999",
            contact_phone="+15125550123",
            channel=MessageChannel.SMS.value,
        )
        db.add(conversation)
        await db.flush()
        executor = TextToolExecutor(
            agent=SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id),
            conversation=conversation,
            db=db,
            timezone="America/New_York",
        )

        first = await executor.execute(
            "prepare_booking",
            {
                "date": "2099-01-15",
                "time": "10:00",
                "duration_minutes": 30,
                "call_type": "phone_call",
            },
        )
        second = await executor.execute(
            "prepare_booking",
            {
                "date": "2099-01-15",
                "time": "11:00",
                "duration_minutes": 30,
                "call_type": "video_call",
            },
        )
        await db.commit()

        draft = await db.get(ConversationBookingDraft, conversation.id)
        count = await db.scalar(
            select(func.count())
            .select_from(ConversationBookingDraft)
            .where(ConversationBookingDraft.conversation_id == conversation.id)
        )
        raw_email = await db.scalar(
            select(type_coerce(ConversationBookingDraft.email, Text)).where(
                ConversationBookingDraft.conversation_id == conversation.id
            )
        )
        assert first["booking_draft_prepared"] is True
        assert second["booking_draft_prepared"] is True
        assert count == 1
        assert draft is not None
        assert draft.time.strftime("%H:%M") == "11:00"
        assert draft.call_type == "video_call"
        assert draft.email == "draft@example.com"
        assert raw_email != "draft@example.com"
        assert "Tuesday" not in draft.confirmation_text
        assert "Thursday, January 15, 2099" in draft.confirmation_text
