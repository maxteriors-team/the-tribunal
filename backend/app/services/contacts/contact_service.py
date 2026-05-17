"""Contact service - business logic orchestration layer."""

import uuid
from math import ceil
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.phone_number import PhoneNumber
from app.schemas.contact import ContactWithConversationResponse
from app.schemas.tag import TagResponse
from app.services.contacts.contact_repository import (
    bulk_delete_contacts,
    bulk_update_status,
    get_contact_by_id,
    list_contact_ids,
    list_contacts_paginated,
)
from app.services.contacts.contact_repository import (
    create_contact as repo_create_contact,
)
from app.services.contacts.contact_repository import (
    delete_contact as repo_delete_contact,
)
from app.services.contacts.contact_repository import (
    get_contact_timeline as repo_get_contact_timeline,
)
from app.services.contacts.contact_repository import (
    update_contact as repo_update_contact,
)
from app.services.contacts.exceptions import (
    ContactNotFoundError,
    ContactPhoneNotConfiguredError,
    ContactValidationError,
)
from app.services.telephony.telnyx import TelnyxSMSService
from app.utils.phone import normalize_phone_safe

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
        rows, total = await list_contacts_paginated(
            workspace_id=workspace_id,
            db=self.db,
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            search=search,
            sort_by=sort_by,
            **filter_kwargs,
        )

        # Build response with conversation data
        items = []
        for row in rows:
            contact = row[0]  # Contact object
            contact_data = ContactWithConversationResponse.model_validate(contact)
            contact_data.unread_count = row[1] or 0
            contact_data.last_message_at = row[2]
            contact_data.last_message_direction = row[3]
            # Populate tag objects from loaded relationship
            if hasattr(contact, "contact_tags") and contact.contact_tags:
                contact_data.tag_objects = [
                    TagResponse.model_validate(ct.tag)
                    for ct in contact.contact_tags
                    if ct.tag is not None
                ]
            items.append(contact_data)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": ceil(total / page_size) if total > 0 else 1,
        }

    async def list_contact_ids(
        self,
        workspace_id: uuid.UUID,
        status_filter: str | None = None,
        search: str | None = None,
        **filter_kwargs: Any,
    ) -> dict[str, Any]:
        """Get all contact IDs matching filters (for Select All functionality)."""
        ids, total = await list_contact_ids(
            workspace_id=workspace_id,
            db=self.db,
            status_filter=status_filter,
            search=search,
            **filter_kwargs,
        )

        return {
            "ids": ids,
            "total": total,
        }

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
        if not contact_ids:
            raise ContactValidationError("No contact IDs provided")

        deleted, errors = await bulk_delete_contacts(
            contact_ids=contact_ids,
            workspace_id=workspace_id,
            db=self.db,
        )

        return {
            "deleted": deleted,
            "failed": len(errors),
            "errors": errors,
        }

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
        if not contact_ids:
            raise ContactValidationError("No contact IDs provided")

        updated, errors = await bulk_update_status(
            contact_ids=contact_ids,
            workspace_id=workspace_id,
            new_status=new_status,
            db=self.db,
        )

        return {
            "updated": updated,
            "failed": len(errors),
            "errors": errors,
        }

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
        # Verify contact exists
        await self.get_contact(contact_id, workspace_id)

        return await repo_get_contact_timeline(
            contact_id=contact_id,
            workspace_id=workspace_id,
            db=self.db,
            limit=limit,
        )

    async def send_message(
        self,
        contact_id: int,
        workspace_id: uuid.UUID,
        message_body: str,
        from_number: str | None = None,
        telnyx_api_key: str | None = None,
    ) -> Any:
        """Send an SMS message to a contact.

        Args:
            contact_id: The contact ID
            workspace_id: The workspace UUID
            message_body: Message text
            from_number: Optional specific phone number to send from
            telnyx_api_key: Telnyx API key

        Returns:
            Created message object

        Raises:
            ContactNotFoundError: If contact not found
            ContactValidationError: If contact has no phone number
            ContactPhoneNotConfiguredError: If SMS service not configured
        """
        # Get contact
        contact = await self.get_contact(contact_id, workspace_id)

        if not contact.phone_number:
            raise ContactValidationError("Contact does not have a phone number")

        # Get workspace phone number for sending
        workspace_phone = await self._get_workspace_phone(workspace_id, from_number)

        # Check for Telnyx API key
        if not telnyx_api_key:
            raise ContactPhoneNotConfiguredError("SMS service not configured")

        # Send message via Telnyx (this creates/gets conversation automatically)
        sms_service = TelnyxSMSService(telnyx_api_key)
        try:
            message = await sms_service.send_message(
                to_number=contact.phone_number,
                from_number=workspace_phone.phone_number,
                body=message_body,
                db=self.db,
                workspace_id=workspace_id,
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
        # Get contact
        contact = await self.get_contact(contact_id, workspace_id)

        if not contact.phone_number:
            raise ContactValidationError("Contact does not have a phone number")

        # Normalize the contact phone number for matching
        normalized_contact_phone = (
            normalize_phone_safe(contact.phone_number) or contact.phone_number
        )

        # Try to find existing conversation by contact_id first (get most recent)
        conv_result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                Conversation.contact_id == contact_id,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )
        conversation = conv_result.scalars().first()

        # If not found by contact_id, try finding by phone number
        if conversation is None:
            conv_result = await self.db.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    or_(
                        Conversation.contact_phone == contact.phone_number,
                        Conversation.contact_phone == normalized_contact_phone,
                    ),
                )
                .order_by(Conversation.updated_at.desc())
                .limit(1)
            )
            conversation = conv_result.scalars().first()

            # If found by phone, link it to this contact
            if conversation is not None:
                conversation.contact_id = contact_id

        # If still no conversation, create one
        if conversation is None:
            # Get a workspace phone number
            workspace_phone = await self._get_workspace_phone(workspace_id, None)

            # Create conversation
            conversation = Conversation(
                workspace_id=workspace_id,
                contact_id=contact_id,
                workspace_phone=workspace_phone.phone_number,
                contact_phone=normalized_contact_phone,
                channel="sms",
                ai_enabled=enabled,
            )
            self.db.add(conversation)
        else:
            # Update existing conversation
            conversation.ai_enabled = enabled

        await self.db.commit()
        await self.db.refresh(conversation)

        return {
            "ai_enabled": conversation.ai_enabled,
            "conversation_id": conversation.id,
        }

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
        if from_number:
            # Use the specified phone number
            phone_result = await self.db.execute(
                select(PhoneNumber).where(
                    PhoneNumber.workspace_id == workspace_id,
                    PhoneNumber.phone_number == from_number,
                    PhoneNumber.sms_enabled.is_(True),
                    PhoneNumber.is_active.is_(True),
                )
            )
            workspace_phone = phone_result.scalar_one_or_none()
            if workspace_phone is None:
                raise ContactValidationError("Specified phone number not found or not SMS-enabled")
        else:
            # Use the first available SMS-enabled phone number
            phone_result = await self.db.execute(
                select(PhoneNumber)
                .where(
                    PhoneNumber.workspace_id == workspace_id,
                    PhoneNumber.sms_enabled.is_(True),
                    PhoneNumber.is_active.is_(True),
                )
                .limit(1)
            )
            workspace_phone = phone_result.scalar_one_or_none()
            if workspace_phone is None:
                raise ContactPhoneNotConfiguredError(
                    "No SMS-enabled phone number configured for this workspace"
                )

        return workspace_phone
