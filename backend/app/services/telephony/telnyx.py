"""Telnyx SMS service for sending and receiving messages."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_phone
from app.core.metrics import (
    latency_ms_timer,
    observe_sms_sent,
    telnyx_api_latency_ms,
)
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel, MessageStatus
from app.services.idempotency import (
    find_message_by_idempotency_key,
    idempotency_headers,
    resolve_message_idempotency,
)
from app.services.messaging.link_shortener import shorten_urls_in_text
from app.services.providers.http import (
    AsyncProviderHTTPClient,
    ProviderHTTPError,
    ProviderRetryPolicy,
)
from app.utils.phone import normalize_phone_e164, phone_lookup_variants
from app.utils.pii import mask_phone

logger = structlog.get_logger()


TELNYX_RETRY_POLICY = ProviderRetryPolicy(
    max_attempts=3,
    initial_backoff_seconds=1.0,
    max_backoff_seconds=10.0,
)


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

    def __init__(
        self,
        api_key: str,
        *,
        message_channel: MessageChannel = MessageChannel.SMS,
        conversation_channel: str = MessageChannel.SMS.value,
        service_name: str = "telnyx_sms",
        provider_payload_type: str = "SMS",
    ) -> None:
        """Initialize SMS service.

        Args:
            api_key: Telnyx API key
            message_channel: Channel stored on created message rows.
            conversation_channel: Channel stored on newly created conversations.
            service_name: Structured-log service label.
            provider_payload_type: Telnyx message type payload value.
        """
        self.api_key = api_key
        self.message_channel = message_channel
        self.conversation_channel = conversation_channel
        self.provider_payload_type = provider_payload_type
        self._client: httpx.AsyncClient | None = None
        self._provider_client: AsyncProviderHTTPClient | None = None
        self.logger = logger.bind(service=service_name)

    def _build_provider_client(
        self,
        raw_client: httpx.AsyncClient | None = None,
    ) -> AsyncProviderHTTPClient:
        """Build the shared provider HTTP client for Telnyx."""
        return AsyncProviderHTTPClient(
            provider="telnyx",
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            retry_policy=TELNYX_RETRY_POLICY,
            logger=self.logger,
            client=raw_client,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create the raw HTTP client.

        Kept for subclasses and tests that still interact with httpx directly;
        migrated Telnyx methods use :attr:`provider_client` instead.
        """
        if self._client is None:
            self._provider_client = self._build_provider_client()
            self._client = self._provider_client.raw_client
        return self._client

    @property
    def provider_client(self) -> AsyncProviderHTTPClient:
        """Get or create the shared provider HTTP client."""
        if self._provider_client is None:
            self._provider_client = self._build_provider_client(raw_client=self._client)
            self._client = self._provider_client.raw_client
        return self._provider_client

    async def close(self) -> None:
        """Close HTTP client."""
        provider_client = self._provider_client
        raw_client = self._client
        self._provider_client = None
        self._client = None
        if provider_client is not None:
            await provider_client.aclose()
            if not provider_client.owns_client and raw_client is not None:
                await raw_client.aclose()
            return
        if raw_client is not None:
            await raw_client.aclose()

    async def _find_message_by_idempotency_key(
        self,
        db: AsyncSession,
        idempotency_key: uuid.UUID | None,
    ) -> Message | None:
        """Return an existing outbound message for an idempotency key."""
        return await find_message_by_idempotency_key(db, idempotency_key)

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
        idempotency_key: uuid.UUID | None = None,
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
            idempotency_key: Optional stable UUID for crash-safe retries.
                Workers compute this from a domain entity (e.g. appointment
                + offset, campaign_contact) so a crash between row insert
                and the Telnyx call is recoverable on retry. If a Message
                already exists for this key it is returned unchanged. The
                key is also sent to Telnyx as the ``X-Idempotency-Key``
                header. If omitted, a fresh UUID is generated and the call
                is effectively non-idempotent across retries.

        Returns:
            Created (or pre-existing) Message record.
        """
        # Normalize outbound addresses before persistence/provider handoff.
        to_number = self._normalize_outbound_to(to_number)
        from_number = self._normalize_outbound_from(from_number)

        log = self.logger.bind(to=to_number, from_=from_number)

        # Idempotency: if a Message row already exists for this key, this is
        # a retry of a previous attempt that successfully wrote the row. If
        # the prior attempt also reached Telnyx (status != QUEUED) we return
        # immediately — the SMS was already sent. If the row exists but the
        # send never happened (still QUEUED), we resume the send rather than
        # inserting a duplicate row, reusing the existing message id.
        idempotency_state = await resolve_message_idempotency(db, idempotency_key)
        if idempotency_state.should_skip and idempotency_state.existing_message is not None:
            existing = idempotency_state.existing_message
            log.info(
                "text_send_idempotent_skip",
                idempotency_key=str(idempotency_key),
                message_id=str(existing.id),
                status=existing.status,
            )
            return existing

        log.info(
            "sending_text_message",
            channel=self.message_channel.value,
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )

        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            db=db,
            workspace_phone=from_number,
            contact_phone=to_number,
            workspace_id=workspace_id,
        )

        # Either resume the half-finished QUEUED row from a prior attempt or
        # create a fresh one. Either way ``effective_key`` is the value we
        # send to Telnyx, ensuring the provider also rejects duplicates.
        effective_key = idempotency_state.effective_key

        message = idempotency_state.existing_message

        if message is None:
            message = Message(
                conversation_id=conversation.id,
                direction="outbound",
                channel=self.message_channel,
                body=body,
                status="queued",
                agent_id=agent_id,
                is_ai=agent_id is not None,
                from_phone_number_id=phone_number_id,
                idempotency_key=effective_key,
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

        # Send via Telnyx. _post_message handles retry on 5xx/network errors;
        # 4xx (bad request, invalid number, auth) raises immediately and is
        # mapped to MessageStatus.FAILED below.
        try:
            payload = self._build_message_payload(
                to_number=to_number,
                from_number=from_number,
                body=body,
                idempotency_key=effective_key,
            )
            response_data = await self._post_message(payload, idempotency_key=effective_key)
            data = response_data.get("data", {})
            message.provider_message_id = data.get("id")
            message.status = MessageStatus.SENT
            message.sent_at = datetime.now(UTC)
            observe_sms_sent(workspace_id, direction="outbound")
            log.info("text_message_sent", message_id=message.provider_message_id)
        except ProviderHTTPError as e:
            message.status = MessageStatus.FAILED
            message.error_message = e.message
            log.error(
                "text_send_failed",
                status_code=e.status_code,
                error=e.message,
                error_code=e.code,
                retryable=e.retryable,
            )
        except Exception as e:
            message.status = MessageStatus.FAILED
            message.error_message = str(e)
            log.exception("text_send_exception", error=str(e))

        # Update conversation
        conversation.last_message_preview = body[:255]
        conversation.last_message_at = datetime.now(UTC)
        conversation.last_message_direction = "outbound"

        await db.commit()
        await db.refresh(message)

        return message

    def _normalize_outbound_to(self, to_number: str) -> str:
        """Normalize an outbound recipient address for this provider."""
        return normalize_phone_e164(to_number)

    def _normalize_outbound_from(self, from_number: str) -> str:
        """Normalize an outbound sender address for this provider."""
        return normalize_phone_e164(from_number)

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

        # Idempotency: Telnyx retries inbound webhooks on non-2xx responses
        # (and occasionally on transient network issues). If we've already
        # ingested this provider_message_id, return the existing Message
        # without incrementing counters or re-firing AI/push.
        if provider_message_id:
            existing_result = await db.execute(
                select(Message)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(
                    Message.provider_message_id == provider_message_id,
                    Conversation.workspace_id == workspace_id,
                )
            )
            existing_message = existing_result.scalar_one_or_none()
            if existing_message is not None:
                log.info(
                    "inbound_sms_duplicate_ignored",
                    message_id=str(existing_message.id),
                )
                return existing_message

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
            channel=self.message_channel,
            body=body,
            status="received",
        )
        db.add(message)
        observe_sms_sent(workspace_id, direction="inbound")

        # Update conversation
        conversation.last_message_preview = body[:255]
        conversation.last_message_at = datetime.now(UTC)
        conversation.last_message_direction = "inbound"
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

        try:
            await db.commit()
        except IntegrityError:
            # Race: a concurrent webhook delivery for the same
            # provider_message_id committed first. Roll back our duplicate
            # work (including the unread_count increment) and return the
            # row that already won.
            await db.rollback()
            existing_result = await db.execute(
                select(Message)
                .join(Conversation, Message.conversation_id == Conversation.id)
                .where(
                    Message.provider_message_id == provider_message_id,
                    Conversation.workspace_id == workspace_id,
                )
            )
            existing_message = existing_result.scalar_one_or_none()
            if existing_message is None:
                # Constraint fired but we can't find the row — re-raise so
                # the webhook returns non-2xx and Telnyx retries.
                raise
            log.info(
                "inbound_sms_duplicate_race_ignored",
                message_id=str(existing_message.id),
            )
            return existing_message

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
    ) -> tuple[Message | None, str | None]:
        """Update message delivery status.

        Args:
            db: Database session
            provider_message_id: Telnyx message ID
            status: New status
            error_code: Optional Telnyx error code
            error_message: Optional error message

        Returns:
            Tuple of (updated message, previous status). Both are None if the
            message could not be found. ``previous_status`` is the status the
            message held before this call applied any change, allowing callers
            to detect duplicate/redelivered Telnyx webhooks (where the message
            is already in the same terminal state).
        """
        result = await db.execute(
            select(Message).where(Message.provider_message_id == provider_message_id)
        )
        message = result.scalar_one_or_none()

        if not message:
            self.logger.warning("message_not_found", provider_message_id=provider_message_id)
            return None, None

        # Capture the prior status BEFORE we mutate so callers can decide
        # whether this webhook represents a real state transition.
        previous_status = message.status

        # Map Telnyx status to our status
        status_map: dict[str, MessageStatus] = {
            "queued": MessageStatus.QUEUED,
            "sending": MessageStatus.SENDING,
            "sent": MessageStatus.SENT,
            "delivered": MessageStatus.DELIVERED,
            "delivery_failed": MessageStatus.FAILED,
            "sending_failed": MessageStatus.FAILED,
        }

        message.status = status_map.get(status, MessageStatus(status))

        # Store error info if provided
        if error_code:
            message.error_code = error_code
        if error_message:
            message.error_message = error_message

        # Set delivered timestamp only on the first transition into delivered
        # so duplicate webhooks don't bump the timestamp forward.
        if message.status == MessageStatus.DELIVERED and message.delivered_at is None:
            message.delivered_at = datetime.now(UTC)

        await db.commit()
        await db.refresh(message)

        self.logger.info(
            "message_status_updated",
            message_id=str(message.id),
            status=message.status,
            previous_status=previous_status,
            error_code=error_code,
        )

        return message, previous_status

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
                contact = await self._find_contact_by_phone(db, workspace_id, contact_phone)
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
            sample_phones = [f"{c.phone_number} ({c.full_name})" for c in sample_contacts]
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
            channel=self.conversation_channel,
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

        phone_hashes = [hash_phone(variant) for variant in variants]
        result = await db.execute(
            select(Contact)
            .where(
                Contact.workspace_id == workspace_id,
                Contact.phone_hash.in_(phone_hashes),
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

    def _build_message_payload(
        self,
        *,
        to_number: str,
        from_number: str,
        body: str,
        idempotency_key: uuid.UUID,
    ) -> dict[str, str]:
        """Build provider payload for a Telnyx text message."""
        return {
            "to": to_number,
            "from": from_number,
            "text": body,
            "type": self.provider_payload_type,
        }

    async def _post_message(
        self,
        payload: dict[str, str],
        idempotency_key: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """POST to /messages with shared retry/error handling.

        If ``idempotency_key`` is provided, it is sent as the
        ``X-Idempotency-Key`` HTTP header. Telnyx echoes this header back on
        retry-safe deduplication so the provider also rejects duplicates if
        the provider client re-issues the request after a transient failure.

        Raises a typed ``ProviderHTTPError`` subclass on 4xx, exhausted 5xx,
        invalid JSON, or persistent network failures. The caller maps these
        to a failed Message row.
        """
        headers = idempotency_headers(idempotency_key) or None
        with latency_ms_timer(telnyx_api_latency_ms):
            data = await self.provider_client.post_json("/messages", json=payload, headers=headers)
        self.logger.info("telnyx_response", status_code=200)
        return data

    async def _get_phone_numbers(self) -> dict[str, Any]:
        return await self.provider_client.get_json("/phone_numbers")

    async def _get_available_phone_numbers(
        self, params: dict[str, str | int | bool]
    ) -> dict[str, Any]:
        return await self.provider_client.get_json("/available_phone_numbers", params=params)

    async def _post_number_order(self, phone_number: str) -> dict[str, Any]:
        return await self.provider_client.post_json(
            "/number_orders",
            json={"phone_numbers": [{"phone_number": phone_number}]},
        )

    async def _delete_phone_number(self, phone_number_id: str) -> None:
        await self.provider_client.delete(f"/phone_numbers/{phone_number_id}")

    async def _patch_phone_number(self, phone_number_id: str, payload: dict[str, str]) -> None:
        await self.provider_client.patch(
            f"/phone_numbers/{phone_number_id}",
            json=payload,
        )

    async def list_phone_numbers(self) -> list[PhoneNumberInfo]:
        """List all Telnyx phone numbers."""
        self.logger.info("listing_phone_numbers")

        numbers = []
        data = await self._get_phone_numbers()

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

        data = await self._get_available_phone_numbers(params)

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
        self.logger.info("purchasing_phone_number", phone_number=mask_phone(phone_number))

        order_data = await self._post_number_order(phone_number)

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
            await self._delete_phone_number(phone_number_id)
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

            await self._patch_phone_number(phone_number_id, payload)
            return True
        except Exception as e:
            self.logger.exception("configure_failed", id=phone_number_id, error=str(e))
            return False
