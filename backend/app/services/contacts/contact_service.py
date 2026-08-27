"""Contact service - business logic orchestration layer."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
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
from app.services.exceptions import ServiceUnavailableError
from app.services.messaging.media_storage import MMSStorageError
from app.services.messaging.outbound_media import (
    OutboundImageValidationError,
    OutboundMedia,
    store_outbound_image,
)
from app.services.telephony.text_provider import MacRelayMessageService, get_text_message_provider

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
        profile_fields: dict[str, Any] | None = None,
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
            profile_fields: Mailing-address + avatar column values

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
            profile_fields=profile_fields,
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

    async def append_contact_note(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        note: str,
        author_name: str,
    ) -> Contact:
        """Append one internal note without overwriting concurrent client history."""
        result = await self.db.execute(
            select(Contact)
            .where(Contact.id == contact_id, Contact.workspace_id == workspace_id)
            .with_for_update()
        )
        contact = result.scalar_one_or_none()
        if contact is None:
            raise ContactNotFoundError()

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        entry = f"[{timestamp}] {author_name}: {note}"
        existing = (contact.notes or "").rstrip()
        notes = f"{existing}\n\n{entry}" if existing else entry
        return await repo_update_contact(contact, self.db, {"notes": notes})

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
        conversation_id: uuid.UUID | None = None,
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
            conversation_id=conversation_id,
        )

    async def send_message(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        message_body: str,
        from_number: str | None = None,
        image_data_url: str | None = None,
        sender_user_id: int | None = None,
        sender_display_name: str | None = None,
    ) -> Any:
        """Send a configured text-channel message to a contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID
            message_body: Message text
            from_number: Optional specific phone number to send from
            image_data_url: Optional validated image attachment

        Returns:
            Created message object

        Raises:
            ContactNotFoundError: If contact not found
            ContactValidationError: If contact or attachment is invalid
            ContactPhoneNotConfiguredError: If text messaging is not configured
        """
        contact = await self.get_contact(contact_id, workspace_id)
        if not contact.phone_number:
            raise ContactValidationError("Contact does not have a phone number")

        workspace_phone = await self._get_workspace_phone(workspace_id, from_number)
        sms_service = get_text_message_provider(
            preferred_provider_for_phone(workspace_phone),
            mac_relay_service=workspace_phone.mac_relay_service,
        )
        try:
            media: tuple[OutboundMedia, ...] = ()
            if image_data_url is not None:
                if not workspace_phone.supports_mms:
                    raise ContactValidationError("The selected sending number does not support MMS")
                if isinstance(sms_service, MacRelayMessageService):
                    raise ContactValidationError(
                        "Image attachments require a Telnyx-enabled sending number"
                    )
                try:
                    media = (
                        await store_outbound_image(
                            workspace_id=workspace_id,
                            data_url=image_data_url,
                        ),
                    )
                except OutboundImageValidationError as exc:
                    raise ContactValidationError(str(exc)) from exc
                except MMSStorageError as exc:
                    raise ServiceUnavailableError(
                        "Image attachments are temporarily unavailable"
                    ) from exc

            return await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=sender_address_for_phone(workspace_phone),
                body=message_body,
                db=self.db,
                workspace_id=workspace_id,
                phone_number_id=workspace_phone.id,
                media=media,
                sender_user_id=sender_user_id,
                sender_display_name=sender_display_name,
            )
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
