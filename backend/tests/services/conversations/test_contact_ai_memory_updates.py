"""Completed human SMS replies refresh durable contact AI memory."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    )
    sent_message = SimpleNamespace(id=message_id)
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    service = ConversationService(db)
    service._get_conversation = AsyncMock(return_value=conversation)  # type: ignore[method-assign]

    provider = MagicMock()
    provider.send_message = AsyncMock(return_value=sent_message)
    provider.close = AsyncMock()

    with (
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
        )

    assert result is sent_message
    refresh_memory.assert_awaited_once_with(
        db,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        completed_message_id=message_id,
    )
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()
