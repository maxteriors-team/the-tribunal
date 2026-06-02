"""Contact-level AI conversation state service."""

import uuid
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.services.contacts.contact_repository import get_contact_by_id
from app.services.contacts.exceptions import (
    ContactNotFoundError,
    ContactPhoneNotConfiguredError,
    ContactValidationError,
)
from app.utils.phone import normalize_phone_safe

logger = structlog.get_logger()


def preferred_provider_for_phone(phone_number: PhoneNumber) -> str | None:
    """Keep contact sends on the sender identity's configured transport."""
    if phone_number.imessage_enabled:
        return "mac_relay"
    return None


def sender_address_for_phone(phone_number: PhoneNumber) -> str:
    """Return the provider-facing sender identity for a phone row."""
    if phone_number.imessage_enabled and phone_number.mac_relay_sender_id:
        return phone_number.mac_relay_sender_id
    return phone_number.phone_number


class ContactAIStateService:
    """Manage contact conversation AI state and assigned agent."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(service="contact_ai_state")

    async def toggle_ai(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        enabled: bool,
    ) -> dict[str, Any]:
        """Toggle AI for a contact's active text conversation."""
        conversation = await self.get_or_create_contact_conversation(contact_id, workspace_id)
        conversation.ai_enabled = enabled

        await self.db.commit()
        await self.db.refresh(conversation)

        return {
            "ai_enabled": conversation.ai_enabled,
            "conversation_id": conversation.id,
        }

    async def assign_agent(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """Assign an AI agent to a contact's active text conversation."""
        conversation = await self.get_or_create_contact_conversation(contact_id, workspace_id)

        if agent_id is not None:
            agent = await get_workspace_owned(
                self.db,
                Agent,
                agent_id,
                workspace_id,
                Agent.is_active.is_(True),
            )
            if agent is None:
                raise ContactValidationError("Agent not found or inactive")

        conversation.assigned_agent_id = agent_id
        conversation.ai_enabled = agent_id is not None
        await self.db.commit()
        await self.db.refresh(conversation)

        return {
            "assigned_agent_id": conversation.assigned_agent_id,
            "ai_enabled": conversation.ai_enabled,
            "conversation_id": conversation.id,
        }

    async def get_or_create_contact_conversation(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
    ) -> Conversation:
        """Find or create the most relevant conversation for contact-level settings."""
        contact = await self.get_contact(contact_id, workspace_id)
        if not contact.phone_number:
            raise ContactValidationError("Contact does not have a phone number")

        normalized_contact_phone = (
            normalize_phone_safe(contact.phone_number) or contact.phone_number
        )

        conversation = await self._find_contact_conversation(
            contact_id=contact_id,
            workspace_id=workspace_id,
            contact_phone=contact.phone_number,
            normalized_contact_phone=normalized_contact_phone,
        )
        if conversation is not None:
            return conversation

        workspace_phone = await self.get_workspace_phone(workspace_id, None)
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact_id,
            workspace_phone=sender_address_for_phone(workspace_phone),
            contact_phone=normalized_contact_phone,
            channel="imessage" if workspace_phone.imessage_enabled else "sms",
            ai_enabled=True,
        )
        self.db.add(conversation)
        await self.db.flush()
        return conversation

    async def get_workspace_phone(
        self,
        workspace_id: uuid.UUID,
        from_number: str | None = None,
    ) -> PhoneNumber:
        """Get a workspace phone number for text sending or conversation creation."""
        if from_number:
            phone_result = await self.db.execute(
                select_workspace_owned(
                    PhoneNumber,
                    workspace_id,
                    PhoneNumber.phone_number == from_number,
                    PhoneNumber.sms_enabled.is_(True),
                    PhoneNumber.is_active.is_(True),
                )
            )
            workspace_phone = phone_result.scalar_one_or_none()
            if workspace_phone is None:
                raise ContactValidationError("Specified phone number not found or not SMS-enabled")
            return workspace_phone

        phone_result = await self.db.execute(
            select_workspace_owned(
                PhoneNumber,
                workspace_id,
                PhoneNumber.sms_enabled.is_(True),
                PhoneNumber.is_active.is_(True),
            )
            .order_by(PhoneNumber.imessage_enabled.desc(), PhoneNumber.created_at)
            .limit(1)
        )
        workspace_phone = phone_result.scalar_one_or_none()
        if workspace_phone is None:
            raise ContactPhoneNotConfiguredError(
                "No SMS-enabled phone number configured for this workspace"
            )

        return workspace_phone

    async def get_contact(self, contact_id: int, workspace_id: uuid.UUID) -> Contact:
        """Fetch a workspace-scoped contact or raise a contact-specific 404."""
        contact = await get_contact_by_id(contact_id, workspace_id, self.db)
        if contact is None:
            raise ContactNotFoundError()
        return contact

    async def _find_contact_conversation(
        self,
        *,
        contact_id: int,
        workspace_id: uuid.UUID,
        contact_phone: str,
        normalized_contact_phone: str,
    ) -> Conversation | None:
        """Find the latest text conversation by contact ID or phone."""
        conv_result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact_id,
                Conversation.channel.in_(("sms", "imessage")),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        conversation = conv_result.scalars().first()
        if conversation is not None:
            return conversation

        conv_result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.channel.in_(("sms", "imessage")),
                or_(
                    Conversation.contact_phone == contact_phone,
                    Conversation.contact_phone == normalized_contact_phone,
                ),
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        conversation = conv_result.scalars().first()
        if conversation is not None:
            conversation.contact_id = contact_id

        return conversation
