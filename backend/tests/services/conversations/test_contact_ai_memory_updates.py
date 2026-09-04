"""Completed human SMS replies refresh durable contact AI memory."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.conversation import Message, MessageDirection, MessageStatus
from app.services.conversations.conversation_service import ConversationService


@pytest.mark.asyncio
async def test_successful_human_sms_reply_refreshes_contact_memory() -> None:
    workspace_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    message_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        workspace_id=workspace_id,
        contact_phone="+15555550100",
        workspace_phone="+15555550101",
        source_provider=None,
    )
    sent_message = Message(
        id=message_id,
        conversation_id=conversation_id,
        direction=MessageDirection.OUTBOUND,
        body="Thanks for confirming.",
        status=MessageStatus.SENT,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    service = ConversationService(db)
    provider = MagicMock()
    provider.send_message = AsyncMock(return_value=sent_message)
    provider.close = AsyncMock()

    with (
        patch.object(
            service, "_get_conversation", new=AsyncMock(return_value=conversation)
        ),
        patch(
            "app.services.conversations.conversation_service.provider_for_conversation",
            return_value="telnyx",
        ),
        patch(
            "app.services.conversations.conversation_service.get_text_message_provider",
            return_value=provider,
        ),
        patch(
            "app.services.ai.contact_ai_memory_service.refresh_contact_ai_memory_from_sms",
            new=AsyncMock(return_value=True),
        ) as refresh_memory,
    ):
        result = await service.send_message(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            body="Thanks for confirming.",
            sender_user_id=73,
            sender_display_name="Morgan Operator",
        )

    assert result is sent_message
    assert provider.send_message.await_args.kwargs["sender_user_id"] == 73
    assert provider.send_message.await_args.kwargs["sender_display_name"] == "Morgan Operator"
    refresh_memory.assert_awaited_once_with(
        db,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        completed_message_id=message_id,
    )
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_followup_forwards_authenticated_sender_snapshot() -> None:
    workspace_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=conversation_id,
        workspace_id=workspace_id,
        contact_phone="+15555550100",
        workspace_phone="+15555550101",
        channel="sms",
        source_provider=None,
        followup_count_sent=0,
        followup_enabled=False,
        followup_max_count=3,
        followup_delay_hours=24,
        last_followup_at=None,
        next_followup_at=None,
    )
    sent_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation_id,
        direction=MessageDirection.OUTBOUND,
        body="Following up",
        status=MessageStatus.SENT,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    service = ConversationService(db)
    provider = MagicMock()
    provider.send_message = AsyncMock(return_value=sent_message)
    provider.close = AsyncMock()

    with (
        patch.object(
            service, "_get_conversation", new=AsyncMock(return_value=conversation)
        ),
        patch(
            "app.services.conversations.conversation_service.get_text_message_provider",
            return_value=provider,
        ),
    ):
        result = await service.send_followup(
            conversation_id=conversation_id,
            workspace_id=workspace_id,
            message="Following up",
            sender_user_id=73,
            sender_display_name="Morgan Operator",
        )

    assert result.message_id == str(sent_message.id)
    assert provider.send_message.await_args.kwargs["sender_user_id"] == 73
    assert provider.send_message.await_args.kwargs["sender_display_name"] == "Morgan Operator"
