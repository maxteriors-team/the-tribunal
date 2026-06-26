"""Contact service - business logic orchestration layer."""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.services.contacts.ai_state_service import (
    ContactAIStateService,
    preferred_provider_for_phone,
    sender_address_for_phone,
)
from app.services.contacts.bulk_service import ContactBulkService
from app.services.contacts.contact_repository import (
    create_contact as repo_create_contact,
)
from app.services.contacts.contact_repository import (
    delete_contact as repo_delete_contact,
)
from app.services.contacts.contact_repository import get_contact_by_id
from app.services.contacts.contact_repository import (
    update_contact as repo_update_contact,
)
from app.services.contacts.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
)
from app.services.contacts.query_service import ContactQueryService
from app.services.contacts.timeline_service import ContactTimelineService
from app.services.telephony.text_provider import get_text_message_provider

logger = structlog.get_logger()


class ContactService:
    """High-level contact service for orchestrating business logic."""

    def __init__(self, db: AsyncSession):
        """Initialize the contact service.

        Args:
            db: Database session
        """
        self.db = db
        self.log = logger.bind(service="contact")

    async def list_contacts(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
        search: str | None = None,
        sort_by: str | None = None,
        **filter_kwargs: Any,
    ) -> dict[str, Any]:
        """High-level contact listing with filters."""
        return await ContactQueryService(self.db).list_contacts(
            workspace_id=workspace_id,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            search=search,
            sort_by=sort_by,
            **filter_kwargs,
        )

    async def list_contact_ids(
        self,
        workspace_id: uuid.UUID,
        status_filter: str | None = None,
        search: str | None = None,
        **filter_kwargs: Any,
    ) -> dict[str, Any]:
        """Get all contact IDs matching filters (for Select All functionality)."""
        return await ContactQueryService(self.db).list_contact_ids(
            workspace_id=workspace_id,
            status_filter=status_filter,
            search=search,
            **filter_kwargs,
        )

    async def get_contact(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
    ) -> Contact:
        """Get a specific contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID

        Returns:
            Contact object

        Raises:
            ContactNotFoundError: If contact not found
        """
        contact = await get_contact_by_id(contact_id, workspace_id, self.db)

        if contact is None:
            raise ContactNotFoundError()

        return contact

    async def create_contact(
        self,
        workspace_id: uuid.UUID,
        first_name: str,
        last_name: str | None = None,
        email: str | None = None,
        phone_number: str | None = None,
        company_name: str | None = None,
        contact_status: str = "new",
        tags: list[str] | None = None,
        notes: str | None = None,
        source: str | None = None,
        important_dates: dict[str, Any] | None = None,
        attribution_fields: dict[str, Any] | None = None,
    ) -> Contact:
        """Create a new contact.

        Args:
            workspace_id: The workspace UUID
            first_name: First name
            last_name: Last name
            email: Email address
            phone_number: Phone number
            company_name: Company name
            contact_status: Contact status
            tags: List of tags
            notes: Additional notes
            source: Source of contact
            important_dates: Important dates (birthday, anniversary, custom)
            attribution_fields: Structured lead-source attribution values

        Returns:
            Created contact
        """
        return await repo_create_contact(
            workspace_id=workspace_id,
            db=self.db,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone_number=phone_number,
            company_name=company_name,
            status=contact_status,
            tags=tags,
            notes=notes,
            source=source,
            important_dates=important_dates,
            attribution_fields=attribution_fields,
        )

    async def update_contact(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        update_data: dict[str, Any],
    ) -> Contact:
        """Update a contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID
            update_data: Dictionary of fields to update

        Returns:
            Updated contact

        Raises:
            ContactNotFoundError: If contact not found
        """
        contact = await self.get_contact(contact_id, workspace_id)
        return await repo_update_contact(contact, self.db, update_data)

    async def delete_contact(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
    ) -> None:
        """Delete a contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID

        Raises:
            ContactNotFoundError: If contact not found
        """
        contact = await self.get_contact(contact_id, workspace_id)
        await repo_delete_contact(contact, self.db)

    async def bulk_delete_contacts(
        self,
        contact_ids: list[int],
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Delete multiple contacts at once.

        Args:
            contact_ids: List of contact IDs
            workspace_id: The workspace UUID

        Returns:
            Dict with deleted, failed, errors counts

        Raises:
            ContactValidationError: If no contact IDs provided
        """
        return await ContactBulkService(self.db).bulk_delete_contacts(contact_ids, workspace_id)

    async def bulk_update_status(
        self,
        contact_ids: list[int],
        workspace_id: uuid.UUID,
        new_status: str,
    ) -> dict[str, Any]:
        """Update the status of multiple contacts at once.

        Args:
            contact_ids: List of contact IDs
            workspace_id: The workspace UUID
            new_status: The new status to set

        Returns:
            Dict with updated, failed, errors counts

        Raises:
            ContactValidationError: If no contact IDs provided
        """
        return await ContactBulkService(self.db).bulk_update_status(
            contact_ids,
            workspace_id,
            new_status,
        )

    async def get_contact_timeline(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get the conversation timeline for a contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID
            limit: Maximum items to return

        Returns:
            List of timeline items

        Raises:
            ContactNotFoundError: If contact not found
        """
        return await ContactTimelineService(self.db).get_contact_timeline(
            contact_id=contact_id,
            workspace_id=workspace_id,
            limit=limit,
        )

    async def send_message(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        message_body: str,
        from_number: str | None = None,
    ) -> Any:
        """Send a configured text-channel message to a contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID
            message_body: Message text
            from_number: Optional specific phone number to send from

        Returns:
            Created message object

        Raises:
            ContactNotFoundError: If contact not found
            ContactValidationError: If contact has no phone number
            ContactPhoneNotConfiguredError: If text messaging is not configured
        """
        # Get contact
        contact = await self.get_contact(contact_id, workspace_id)

        if not contact.phone_number:
            raise ContactValidationError("Contact does not have a phone number")

        # Get workspace phone number for sending
        workspace_phone = await self._get_workspace_phone(workspace_id, from_number)

        sms_service = get_text_message_provider(preferred_provider_for_phone(workspace_phone))
        try:
            message = await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=sender_address_for_phone(workspace_phone),
                body=message_body,
                db=self.db,
                workspace_id=workspace_id,
                phone_number_id=workspace_phone.id,
            )
            return message
        finally:
            await sms_service.close()

    async def toggle_ai(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        enabled: bool,
    ) -> dict[str, Any]:
        """Toggle AI for a contact's conversation.

        Finds an existing conversation for the contact or creates one if needed.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID
            enabled: Whether to enable AI

        Returns:
            Dict with ai_enabled and conversation_id

        Raises:
            ContactNotFoundError: If contact not found
            ContactValidationError: If contact has no phone number
        """
        return await ContactAIStateService(self.db).toggle_ai(
            contact_id=contact_id,
            workspace_id=workspace_id,
            enabled=enabled,
        )

    async def assign_agent(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None,
    ) -> dict[str, Any]:
        """Assign an AI agent to a contact's active text conversation."""
        return await ContactAIStateService(self.db).assign_agent(
            contact_id=contact_id,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

    async def _get_or_create_contact_conversation(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
    ) -> Conversation:
        """Find or create the most relevant conversation for contact-level settings."""
        return await ContactAIStateService(self.db).get_or_create_contact_conversation(
            contact_id,
            workspace_id,
        )

    async def _get_workspace_phone(
        self,
        workspace_id: uuid.UUID,
        from_number: str | None = None,
    ) -> PhoneNumber:
        """Get workspace phone number for sending messages.

        Args:
            workspace_id: The workspace UUID
            from_number: Optional specific phone number to use

        Returns:
            PhoneNumber object

        Raises:
            ContactValidationError: If specified phone number not found
            ContactPhoneNotConfiguredError: If no SMS-enabled phone number available
        """
        return await ContactAIStateService(self.db).get_workspace_phone(workspace_id, from_number)
