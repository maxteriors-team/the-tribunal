"""Tests for contact AI-state service."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.services.contacts.ai_state_service import (
    ContactAIStateService,
    preferred_provider_for_phone,
    sender_address_for_phone,
)
from app.services.contacts.exceptions import ContactValidationError


class _ScalarResult:
    """Minimal async-session execute result for scalar_one_or_none/scalars().first()."""

    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        return self.value

    def scalars(self) -> "_ScalarResult":
        return self

    def first(self) -> object | None:
        return self.value


class TestContactAIStateService:
    """AI state behavior extracted from ContactService."""

    def test_sender_provider_helpers_prefer_mac_relay_identity(self) -> None:
        telnyx_phone = PhoneNumber(phone_number="+15551234567", imessage_enabled=False)
        relay_phone = PhoneNumber(
            phone_number="+15557654321",
            imessage_enabled=True,
            mac_relay_sender_id="imessage:agent@example.com",
        )

        assert preferred_provider_for_phone(telnyx_phone) is None
        assert sender_address_for_phone(telnyx_phone) == "+15551234567"
        assert preferred_provider_for_phone(relay_phone) == "mac_relay"
        assert sender_address_for_phone(relay_phone) == "imessage:agent@example.com"

    async def test_toggle_ai_updates_existing_conversation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        workspace_id = uuid.uuid4()
        conversation = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            contact_id=7,
            workspace_phone="+15550000000",
            contact_phone="+14155551234",
            channel="sms",
            ai_enabled=True,
        )
        service = ContactAIStateService(AsyncMock())
        monkeypatch.setattr(
            service,
            "get_or_create_contact_conversation",
            AsyncMock(return_value=conversation),
        )

        result = await service.toggle_ai(7, workspace_id, enabled=False)

        assert result == {"ai_enabled": False, "conversation_id": conversation.id}
        assert conversation.ai_enabled is False
        service.db.commit.assert_awaited_once()
        service.db.refresh.assert_awaited_once_with(conversation)

    async def test_assign_agent_validates_active_workspace_agent(self) -> None:
        workspace_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        conversation = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            contact_id=7,
            workspace_phone="+15550000000",
            contact_phone="+14155551234",
            channel="sms",
            ai_enabled=False,
        )
        agent = Agent(id=agent_id, workspace_id=workspace_id, name="Agent", is_active=True)
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(agent))
        service = ContactAIStateService(db)
        service.get_or_create_contact_conversation = AsyncMock(return_value=conversation)  # type: ignore[method-assign]

        result = await service.assign_agent(7, workspace_id, agent_id)

        assert result == {
            "assigned_agent_id": agent_id,
            "ai_enabled": True,
            "conversation_id": conversation.id,
        }
        assert conversation.assigned_agent_id == agent_id
        assert conversation.ai_enabled is True
        db.execute.assert_awaited_once()
        compiled = str(
            db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "workspace_id" in compiled
        assert workspace_id.hex in compiled
        assert "is_active" in compiled
        db.commit.assert_awaited_once()
        db.refresh.assert_awaited_once_with(conversation)

    async def test_assign_agent_rejects_missing_agent(self) -> None:
        workspace_id = uuid.uuid4()
        conversation = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            contact_id=7,
            workspace_phone="+15550000000",
            contact_phone="+14155551234",
            channel="sms",
        )
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_ScalarResult(None))
        service = ContactAIStateService(db)
        service.get_or_create_contact_conversation = AsyncMock(return_value=conversation)  # type: ignore[method-assign]

        with pytest.raises(ContactValidationError, match="Agent not found or inactive"):
            await service.assign_agent(7, workspace_id, uuid.uuid4())
        compiled = str(
            db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "workspace_id" in compiled
        assert workspace_id.hex in compiled
        db.commit.assert_not_awaited()

    async def test_get_or_create_links_existing_phone_conversation(self) -> None:
        workspace_id = uuid.uuid4()
        contact = Contact(
            id=11,
            workspace_id=workspace_id,
            first_name="Alice",
            phone_number="(415) 555-1234",
            status="new",
        )
        existing = Conversation(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            workspace_phone="+15550000000",
            contact_phone="+14155551234",
            channel="sms",
            updated_at=datetime.now(UTC),
        )
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_ScalarResult(None), _ScalarResult(existing)])
        service = ContactAIStateService(db)
        service.get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]

        result = await service.get_or_create_contact_conversation(11, workspace_id)

        assert result is existing
        assert existing.contact_id == 11
        db.flush.assert_not_awaited()

    async def test_get_or_create_creates_text_conversation_from_workspace_phone(self) -> None:
        workspace_id = uuid.uuid4()
        contact = Contact(
            id=12,
            workspace_id=workspace_id,
            first_name="Alice",
            phone_number="4155551234",
            status="new",
        )
        workspace_phone = PhoneNumber(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            phone_number="+15550000000",
            sms_enabled=True,
            is_active=True,
            imessage_enabled=True,
            mac_relay_sender_id="imessage:sender@example.com",
        )
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_ScalarResult(None), _ScalarResult(None)])
        db.add = MagicMock()
        service = ContactAIStateService(db)
        service.get_contact = AsyncMock(return_value=contact)  # type: ignore[method-assign]
        service.get_workspace_phone = AsyncMock(return_value=workspace_phone)  # type: ignore[method-assign]

        conversation = await service.get_or_create_contact_conversation(12, workspace_id)

        assert conversation.workspace_id == workspace_id
        assert conversation.contact_id == 12
        assert conversation.workspace_phone == "imessage:sender@example.com"
        assert conversation.contact_phone == "+14155551234"
        assert conversation.channel == "imessage"
        assert conversation.ai_enabled is True
        db.add.assert_called_once_with(conversation)
        db.flush.assert_awaited_once()
