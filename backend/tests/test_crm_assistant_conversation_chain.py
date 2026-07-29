"""The recent-conversation result must expose the contact id for tool chaining."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.models.conversation import Conversation
from app.services.ai.crm_assistant._conversation_tools import ConversationAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext


async def test_recent_conversation_exposes_contact_id_and_truthful_count() -> None:
    workspace_id = uuid.uuid4()
    conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=771,
        workspace_phone="+14155550100",
        contact_phone="+14155550200",
        workspace_phone_hash="workspace-hash",
        contact_phone_hash="contact-hash",
        last_message_preview="Can you come Tuesday?",
        last_message_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        unread_count=1,
    )
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [conversation]
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows)
    db.scalar = AsyncMock(return_value=8)
    tools = ConversationAssistantTools(CRMToolContext(db=db, workspace_id=workspace_id, user_id=7))

    result = await tools.list_recent_conversations({"limit": 1})

    assert result["data"][0]["contact_id"] == 771
    assert result["data"][0]["id"] == str(conversation.id)
    assert result["returned"] == 1
    assert result["total"] == 8
    assert result["has_more"] is True


async def test_unlinked_conversation_reports_null_contact_id_honestly() -> None:
    workspace_id = uuid.uuid4()
    conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=None,
        workspace_phone="+14155550100",
        contact_phone="+14155550200",
        workspace_phone_hash="workspace-hash",
        contact_phone_hash="contact-hash",
        last_message_preview=None,
        last_message_at=None,
        unread_count=0,
    )
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [conversation]
    db = MagicMock()
    db.execute = AsyncMock(return_value=rows)
    db.scalar = AsyncMock(return_value=1)
    tools = ConversationAssistantTools(CRMToolContext(db=db, workspace_id=workspace_id, user_id=7))

    result = await tools.list_recent_conversations({})

    assert result["data"][0]["contact_id"] is None
