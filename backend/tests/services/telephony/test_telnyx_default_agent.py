"""Tests for inbound SMS default-agent resolution.

``TelnyxSMSService._resolve_default_agent_id`` guarantees a brand-new (or
legacy agent-less) inbound SMS conversation is owned by an agent so the AI
responder does not log ``no_agent_assigned`` and stay silent:

- When the receiving ``PhoneNumber`` has an explicit ``assigned_agent_id`` it is
  preferred and no default agent is provisioned.
- Otherwise it falls back to ``ensure_default_agent`` (which auto-creates a
  workspace default agent from a template when none exists).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.conversation import Conversation
from app.services.telephony.telnyx import TelnyxSMSService


class TestResolveDefaultAgentId:
    """The resolver prefers a phone-pinned agent, else the workspace default."""

    async def test_prefers_explicit_phone_number_agent(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        workspace_id = uuid.uuid4()
        phone_agent_id = uuid.uuid4()

        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=phone_agent_id)
        db.execute = AsyncMock(return_value=result)

        with patch(
            "app.services.telephony.telnyx.ensure_default_agent",
            new=AsyncMock(),
        ) as ensure_mock:
            resolved = await svc._resolve_default_agent_id(
                db, workspace_id, "+12485930266"
            )

        assert resolved == phone_agent_id
        ensure_mock.assert_not_awaited()

    async def test_falls_back_to_workspace_default_agent(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        workspace_id = uuid.uuid4()
        default_agent_id = uuid.uuid4()

        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)  # phone has no agent
        db.execute = AsyncMock(return_value=result)

        default_agent = MagicMock(id=default_agent_id)
        with patch(
            "app.services.telephony.telnyx.ensure_default_agent",
            new=AsyncMock(return_value=default_agent),
        ) as ensure_mock:
            resolved = await svc._resolve_default_agent_id(
                db, workspace_id, "+12485930266"
            )

        assert resolved == default_agent_id
        ensure_mock.assert_awaited_once_with(db, workspace_id)


class TestConversationDefaultAgentAssignment:
    """The inbound conversation path invokes the resolver for new and legacy rows."""

    async def test_repairs_existing_agentless_conversation(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        workspace_id = uuid.uuid4()
        default_agent_id = uuid.uuid4()
        conversation = MagicMock(
            spec=Conversation,
            contact_id=123,
            assigned_agent_id=None,
        )

        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=conversation)
        db.execute = AsyncMock(return_value=result)
        db.commit = AsyncMock()

        with patch.object(
            svc,
            "_resolve_default_agent_id",
            new=AsyncMock(return_value=default_agent_id),
        ) as resolve_mock:
            resolved = await svc._get_or_create_conversation(
                db,
                workspace_phone="+12485930266",
                contact_phone="+12488406109",
                workspace_id=workspace_id,
            )

        assert resolved is conversation
        assert conversation.assigned_agent_id == default_agent_id
        resolve_mock.assert_awaited_once_with(db, workspace_id, "+12485930266")
        db.commit.assert_awaited_once()

    async def test_assigns_default_agent_to_new_conversation(self) -> None:
        svc = TelnyxSMSService(api_key="k")
        workspace_id = uuid.uuid4()
        default_agent_id = uuid.uuid4()

        db = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        db.execute = AsyncMock(return_value=result)
        db.add = MagicMock()
        db.flush = AsyncMock()

        with (
            patch.object(svc, "_find_contact_by_phone", new=AsyncMock(return_value=None)),
            patch.object(
                svc,
                "_resolve_default_agent_id",
                new=AsyncMock(return_value=default_agent_id),
            ) as resolve_mock,
        ):
            conversation = await svc._get_or_create_conversation(
                db,
                workspace_phone="+12485930266",
                contact_phone="+12488406109",
                workspace_id=workspace_id,
            )

        assert conversation.assigned_agent_id == default_agent_id
        assert conversation.ai_enabled is True
        resolve_mock.assert_awaited_once_with(db, workspace_id, "+12485930266")
        db.add.assert_called_once_with(conversation)
        db.flush.assert_awaited_once()
