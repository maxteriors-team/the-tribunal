"""Telnyx SMS service for sending and receiving messages."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.services.messaging.link_shortener import shorten_urls_in_text
from app.utils.phone import normalize_phone_e164, phone_lookup_variants

logger = structlog.get_logger()


@dataclass
class PhoneNumberInfo:
    """Phone number information from Telnyx."""

    id: str
    phone_number: str
    friendly_name: str | None = None
    capabilities: dict[str, Any] | None = None


class TelnyxSMSService:
    """SMS service for Telnyx messaging.

    Handles:
    - Sending SMS messages
    - Managing conversations
    - Processing inbound messages
    - Tracking delivery status
    """

    BASE_URL = "https://api.telnyx.com/v2"

    def __init__(self, api_key: str) -> None:
        """Initialize SMS service.

        Args:
            api_key: Telnyx API key
        """
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self.logger = logger.bind(service="telnyx_sms")

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def send_message(
        self,
        to_number: str,
        from_number: str,
        body: str,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
        phone_number_id: uuid.UUID | None = None,
    ) -> Message:
        """Send an SMS message and store it.

        Args:
            to_number: Recipient phone number (E.164)
            from_number: Sender phone number (E.164)
            body: Message content
            db: Database session
            workspace_id: Workspace ID
            agent_id: Optional agent ID if sent by AI
            campaign_id: Optional campaign ID if part of campaign
            phone_number_id: Optional phone number ID for tracking

        Returns:
            Created Message record
        """
        # Normalize phone numbers to E.164 format
        to_number = normalize_phone_e164(to_number)
        from_number = normalize_phone_e164(from_number)

        log = self.logger.bind(to=to_number, from_=from_number)
        log.info("sending_sms")

        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            db=db,
            workspace_phone=from_number,
            contact_phone=to_number,
            workspace_id=workspace_id,
        )

        # Create message record (flush first so short links can reference its id)
        message = Message(
            conversation_id=conversation.id,
            direction="outbound",
            channel="sms",
            body=body,
            status="queued",
            agent_id=agent_id,
            is_ai=agent_id is not None,
            from_phone_number_id=phone_number_id,
        )
        db.add(message)
        await db.flush()

        body = await shorten_urls_in_text(
            body,
            workspace_id=workspace_id,
            contact_id=conversation.contact_id,
            campaign_id=campaign_id,
            message_id=message.id,
            db=db,
            base_url=settings.public_base_url,
        )
        message.body = body

        # Send via Telnyx
        try:
            payload: dict[str, str] = {
                "to": to_number,
                "from": from_number,
                "text": body,
                "type": "SMS",
            }

            response = await self.client.post("/messages", json=payload)
            try:
                response_data = response.json()
            except (ValueError, TypeError):
                log.error("telnyx_invalid_json", status_code=response.status_code)
                response_data = {"errors": [{"detail": "Invalid JSON response"}]}

            log.info(
                "telnyx_response",
                status_code=response.status_code,
            )

            if response.status_code in (200, 202):
                data = response_data.get("data", {})
                message.provider_message_id = data.get("id")
                message.status = "sent"
                message.sent_at = datetime.now(UTC)
                log.info("sms_sent", message_id=message.provider_message_id)
            else:
                errors = response_data.get("errors", [])
                first_error = errors[0] if errors else {}
                error_msg = first_error.get("detail") if first_error else response.text
                message.status = "failed"
                log.error("sms_send_failed", error=error_msg)

        except Exception as e:
            message.status = "failed"
            log.exception("sms_send_exception", error=str(e))

        # Update conversation
        conversation.last_message_preview = body[:255]
        conversation.last_message_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(message)

        return message

    async def process_inbound_message(
        self,
        db: AsyncSession,
        provider_message_id: str,
        from_number: str,
        to_number: str,
        body: str,
        workspace_id: uuid.UUID,
    ) -> Message:
        """Process an inbound SMS message.

        Args:
            db: Database session
            provider_message_id: Telnyx message ID
            from_number: Sender's phone number
            to_number: Our phone number
            body: Message content
            workspace_id: Workspace ID

        Returns:
            Created Message record
        """
        log = self.logger.bind(
            provider_message_id=provider_message_id,
            from_=from_number,
            to=to_number,
        )
        log.info("processing_inbound_sms")

        # Get or create conversation (swap from/to for inbound)
        conversation = await self._get_or_create_conversation(
            db=db,
            workspace_phone=to_number,  # Our number
            contact_phone=from_number,  # Their number
            workspace_id=workspace_id,
        )

        # Create message record
        message = Message(
            conversation_id=conversation.id,
            provider_message_id=provider_message_id,
            direction="inbound",
            channel="sms",
            body=body,
            status="received",
        )
        db.add(message)

        # Update conversation
        conversation.last_message_preview = body[:255]
        conversation.last_message_at = datetime.now(UTC)
        conversation.unread_count += 1

        # NOTE: Opt-out detection has been moved to process_inbound_with_ai()
        # where we use AI classification to distinguish between:
        # - Genuine opt-outs: "STOP", "Unsubscribe", "Stop texting me"
        # - False positives: "I think you should quit", "Don't quit on me"
        # This runs in parallel during the debounce delay, adding no latency.

        if conversation.contact_id:
            try:
                from app.services.contacts.engagement_score import record_engagement

                await record_engagement(db, conversation.contact_id)
            except Exception as e:
                log.warning("engagement_update_failed", error=str(e))

        await db.commit()
        await db.refresh(message)

        log.info("inbound_sms_processed", message_id=str(message.id))
        return message

    async def update_message_status(
        self,
        db: AsyncSession,
        provider_message_id: str,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> Message | None:
        """Update message delivery status.

        Args:
            db: Database session
            provider_message_id: Telnyx message ID
            status: New status
            error_code: Optional Telnyx error code
            error_message: Optional error message

        Returns:
            Updated message or None if not found
        """
        result = await db.execute(
            select(Message).where(Message.provider_message_id == provider_message_id)
        )
        message = result.scalar_one_or_none()

        if not message:
            self.logger.warning("message_not_found", provider_message_id=provider_message_id)
            return None

        # Map Telnyx status to our status
        status_map = {
            "queued": "queued",
            "sending": "sending",
            "sent": "sent",
            "delivered": "delivered",
            "delivery_failed": "failed",
            "sending_failed": "failed",
        }

        message.status = status_map.get(status, status)

        # Store error info if provided
        if error_code:
            message.error_code = error_code
        if error_message:
            message.error_message = error_message

        # Set delivered timestamp
        if message.status == "delivered":
            message.delivered_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(message)

        self.logger.info(
            "message_status_updated",
            message_id=str(message.id),
            status=message.status,
            error_code=error_code,
        )

        return message

    async def _get_or_create_conversation(
        self,
        db: AsyncSession,
        workspace_phone: str,
        contact_phone: str,
        workspace_id: uuid.UUID,
    ) -> Conversation:
        """Get or create a conversation for the given phone numbers.

        Args:
            db: Database session
            workspace_phone: Our phone number
            contact_phone: Contact's phone number
            workspace_id: Workspace ID

        Returns:
            Existing or new conversation
        """
        # Look for existing conversation by exact normalized match
        result = await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.workspace_phone == workspace_phone,
                Conversation.contact_phone == contact_phone,
            )
        )
        conversation = result.scalar_one_or_none()

        if conversation:
            # If conversation exists but has no contact_id, try to link one now
            if not conversation.contact_id:
                contact = await self._find_contact_by_phone(
                    db, workspace_id, contact_phone
                )
                if contact:
                    conversation.contact_id = contact.id
                    await db.commit()
            return conversation

        # Try to find contact by phone number (use first() in case of duplicates)
        contact = await self._find_contact_by_phone(db, workspace_id, contact_phone)

        log = self.logger.bind(
            workspace_phone=workspace_phone,
            contact_phone=contact_phone,
            contact_found=contact is not None,
        )

        if contact:
            log.info(
                "contact_found_by_phone",
                contact_id=contact.id,
                contact_name=contact.full_name,
                contact_email=contact.email,
                contact_phone_in_db=contact.phone_number,
            )
        else:
            # Log sample contacts in workspace to help debug phone format mismatch
            from sqlalchemy import func as sa_func

            count_result = await db.execute(
                select(sa_func.count()).where(Contact.workspace_id == workspace_id)
            )
            total_contacts = count_result.scalar() or 0
            sample_result = await db.execute(
                select(Contact).where(Contact.workspace_id == workspace_id).limit(5)
            )
            sample_contacts = sample_result.scalars().all()
            sample_phones = [
                f"{c.phone_number} ({c.full_name})" for c in sample_contacts
            ]
            log.warning(
                "contact_not_found_by_phone",
                looking_for_phone=contact_phone,
                total_contacts_in_workspace=total_contacts,
                sample_contact_phones=sample_phones,
            )

        # Create new conversation
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact.id if contact else None,
            workspace_phone=workspace_phone,
            contact_phone=contact_phone,
            channel="sms",
            ai_enabled=True,  # Default to AI enabled
        )
        db.add(conversation)
        await db.flush()

        self.logger.info(
            "conversation_created",
            conversation_id=str(conversation.id),
            contact_id=contact.id if contact else None,
        )

        return conversation

    async def _find_contact_by_phone(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        contact_phone: str,
    ) -> Contact | None:
        """Find a contact by phone number with flexible format matching.

        Generates the canonical format variants of ``contact_phone`` (E.164,
        national, international, RFC3966, raw digits, and the NANP 10-digit
        subscriber form) and issues a single indexed ``IN (...)`` lookup so
        legacy rows stored in non-E.164 formats still match without a full
        table scan.

        Args:
            db: Database session
            workspace_id: Workspace ID
            contact_phone: Phone number to search for (should already be normalized)

        Returns:
            Contact if found, None otherwise
        """
        # Generate the small set of canonical variants the stored phone could be
        # in (E.164, national, international, RFC3966, digits-only, NANP 10-digit)
        # and resolve in a single indexed IN-list lookup. This keeps the inbound
        # SMS path O(1) on the indexed phone_number column instead of O(n) over
        # every contact in the workspace.
        variants = phone_lookup_variants(contact_phone)
        if not variants:
            return None

        result = await db.execute(
            select(Contact)
            .where(
                Contact.workspace_id == workspace_id,
                Contact.phone_number.in_(variants),
            )
            .limit(1)
        )
        contact = result.scalars().first()
        if contact and contact.phone_number != contact_phone:
            self.logger.info(
                "contact_found_via_phone_variant",
                stored_phone=contact.phone_number,
                lookup_phone=contact_phone,
                contact_id=contact.id,
            )
        return contact

    async def list_phone_numbers(self) -> list[PhoneNumberInfo]:
        """List all Telnyx phone numbers."""
        self.logger.info("listing_phone_numbers")

        numbers = []
        response = await self.client.get("/phone_numbers")
        response.raise_for_status()
        data = response.json()

        for number in data.get("data", []):
            numbers.append(
                PhoneNumberInfo(
                    id=number.get("id", ""),
                    phone_number=number.get("phone_number", ""),
                    friendly_name=number.get("connection_name"),
                    capabilities={
                        "voice": True,
                        "sms": number.get("messaging_profile_id") is not None,
                    },
                )
            )

        self.logger.info("phone_numbers_listed", count=len(numbers))
        return numbers

    async def search_phone_numbers(
        self,
        country: str = "US",
        area_code: str | None = None,
        contains: str | None = None,
        limit: int = 10,
    ) -> list[PhoneNumberInfo]:
        """Search for available Telnyx phone numbers."""
        self.logger.info(
            "searching_phone_numbers",
            country=country,
            area_code=area_code,
            contains=contains,
        )

        params: dict[str, str | int | bool] = {
            "filter[country_code]": country,
            "filter[features]": "voice",
            "filter[limit]": limit,
        }
        if area_code:
            params["filter[national_destination_code]"] = area_code
        if contains:
            params["filter[phone_number][contains]"] = contains

        response = await self.client.get("/available_phone_numbers", params=params)
        response.raise_for_status()
        data = response.json()

        numbers = []
        for number in data.get("data", []):
            region_info = number.get("region_information", [])
            first_region = region_info[0] if region_info else {}
            numbers.append(
                PhoneNumberInfo(
                    id="",  # Not purchased yet
                    phone_number=number.get("phone_number", ""),
                    friendly_name=first_region.get("region_name") if first_region else None,
                    capabilities={
                        "voice": "voice" in number.get("features", []),
                        "sms": "sms" in number.get("features", []),
                    },
                )
            )

        self.logger.info("phone_numbers_found", count=len(numbers))
        return numbers

    async def purchase_phone_number(self, phone_number: str) -> PhoneNumberInfo:
        """Purchase a Telnyx phone number."""
        self.logger.info("purchasing_phone_number", phone_number=phone_number)

        response = await self.client.post(
            "/number_orders",
            json={"phone_numbers": [{"phone_number": phone_number}]},
        )
        response.raise_for_status()
        order_data = response.json()

        phone_numbers = order_data.get("data", {}).get("phone_numbers", [])
        if not phone_numbers:
            raise ValueError("No phone number returned from order")

        number_data = phone_numbers[0]
        self.logger.info("phone_number_purchased", id=number_data.get("id"))

        return PhoneNumberInfo(
            id=number_data.get("id", ""),
            phone_number=number_data.get("phone_number", phone_number),
            friendly_name=None,
            capabilities={"voice": True, "sms": True},
        )

    async def release_phone_number(self, phone_number_id: str) -> bool:
        """Release a Telnyx phone number."""
        self.logger.info("releasing_phone_number", id=phone_number_id)

        try:
            response = await self.client.delete(f"/phone_numbers/{phone_number_id}")
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.exception("release_failed", id=phone_number_id, error=str(e))
            return False

    async def configure_phone_number(
        self,
        phone_number_id: str,
        connection_id: str | None = None,
        messaging_profile_id: str | None = None,
    ) -> bool:
        """Configure a phone number with connection or messaging profile."""
        self.logger.info(
            "configuring_phone_number",
            id=phone_number_id,
            connection_id=connection_id,
            messaging_profile_id=messaging_profile_id,
        )

        try:
            payload: dict[str, str] = {}
            if connection_id:
                payload["connection_id"] = connection_id
            if messaging_profile_id:
                payload["messaging_profile_id"] = messaging_profile_id

            response = await self.client.patch(
                f"/phone_numbers/{phone_number_id}",
                json=payload,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.exception("configure_failed", id=phone_number_id, error=str(e))
            return False
