"""Workspace-scoped mirroring of verified Quo contact and message events."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageChannel,
    MessageDirection,
    MessageStatus,
)
from app.services.quo.client import QUO_HISTORICAL_API_VERSION, QuoApiError, QuoClient
from app.services.quo.reconciliation import (
    QuoMessageSnapshot,
    QuoReconciliationError,
    reconcile_quo_message,
)
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.webhooks.pipeline import WebhookDispatchResult
from app.services.webhooks.quo import QuoWebhookEvent
from app.utils.phone import normalize_phone_safe

QUO_PROVIDER = "quo"
_CONTACT_EVENTS = {"contact.updated", "contact.deleted"}
_MESSAGE_EVENTS = {
    "message.received",
    "message.queued",  # Synthetic historical events; Quo webhooks do not emit these.
    "message.sent",
    "message.delivered",
    "message.failed",
    "message.undelivered",
}
_VOICE_EVENTS = {
    "call.completed",
    "call.missed",
    "call.voicemail.completed",
    "call.transcript.completed",
    "call.summary.completed",
}
_CALL_LIFECYCLE_EVENTS = {"call.completed", "call.missed"}
_CALL_SUCCESS_STATUSES = {"answered", "forwarded", "ai-handled"}
_CALL_FAILURE_STATUSES = {"unanswered"}
_MAX_TRANSCRIPT_CHARS = 1_000_000
_MAX_SUMMARY_CHARS = 2_000
_MAX_CALL_DURATION_SECONDS = 7 * 24 * 60 * 60
_STATUS_BY_EVENT = {
    "message.received": MessageStatus.RECEIVED,
    "message.queued": MessageStatus.QUEUED,
    "message.sent": MessageStatus.SENT,
    "message.delivered": MessageStatus.DELIVERED,
    "message.failed": MessageStatus.FAILED,
    "message.undelivered": MessageStatus.FAILED,
}
_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_MAX_CONTACT_IDS = 10
_MAX_CONTACT_VALUES = 20
_MAX_MEDIA_ITEMS = 10


class QuoSyncError(ValueError):
    """A verified delivery cannot be mapped safely into the CRM."""


class QuoSyncService:
    """Mirror Quo resources without invoking Tribunal outbound or automation paths."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        workspace_id: uuid.UUID,
        organization_id: str,
        phone_number_id: str,
        phone_number: str,
        client: QuoClient,
    ) -> None:
        normalized_phone = normalize_phone_safe(phone_number)
        if not phone_number_id.strip() or len(phone_number_id) > 255 or normalized_phone is None:
            raise QuoSyncError("Quo selected phone number is unavailable")
        self.db = db
        self.workspace_id = workspace_id
        self.organization_id = organization_id
        self.phone_number_id = phone_number_id
        self.phone_number = normalized_phone
        self.client = client
        self._sender_display_names: dict[str, str] = {}

    async def process(self, event: QuoWebhookEvent, log: Any) -> WebhookDispatchResult:
        """Process only resources owned by this workspace's selected Quo line."""
        if event.organization_id != self.organization_id:
            raise QuoSyncError("Quo event organization mismatch")

        resource = event.data.get("resource")
        if not isinstance(resource, dict):
            raise QuoSyncError("Quo event resource is missing")

        if event.event_type in _CONTACT_EVENTS:
            log.info(
                "quo_standalone_contact_ignored",
                workspace_id=str(self.workspace_id),
            )
            return WebhookDispatchResult.ignored("standalone_contact_event")
        if event.event_type not in _MESSAGE_EVENTS | _VOICE_EVENTS:
            return WebhookDispatchResult.ignored("unsupported_event")

        context = event.data.get("context")
        resource_phone_number_id = resource.get("phoneNumberId")
        if not isinstance(resource_phone_number_id, str) and isinstance(context, dict):
            resource_phone_number_id = context.get("phoneNumberId")
        if not isinstance(resource_phone_number_id, str) or not resource_phone_number_id:
            log.info(
                "quo_line_event_ignored",
                workspace_id=str(self.workspace_id),
                reason="missing_phone_number_id",
            )
            return WebhookDispatchResult.ignored("missing_phone_number_id")
        if resource_phone_number_id != self.phone_number_id:
            log.info(
                "quo_line_event_ignored",
                workspace_id=str(self.workspace_id),
                reason="unselected_phone_number",
            )
            return WebhookDispatchResult.ignored("unselected_phone_number")

        if event.event_type in _MESSAGE_EVENTS:
            await self._upsert_message(event, resource)
        else:
            await self._upsert_voice_event(event, resource)
        return WebhookDispatchResult.processed()

    async def _upsert_contact_resource(
        self,
        resource: dict[str, Any],
        *,
        fallback_phone: str | None = None,
    ) -> Contact:
        external_id = _required_string(resource.get("id"), "Quo contact ID", 255)
        phones = _contact_phones(resource)
        if fallback_phone and fallback_phone not in phones:
            phones.append(fallback_phone)

        contact = await self._contact_by_external_ids([external_id])
        if contact is None:
            contact = await self._contact_by_phones(phones)

        identity = _contact_identity(resource)
        if contact is not None:
            _link_quo_contact(contact, external_id)
            _fill_blank_identity(contact, identity, phones)
            return contact

        if not phones:
            raise QuoSyncError("Quo contact has no valid E.164 phone number")

        contact = Contact(
            workspace_id=self.workspace_id,
            first_name=identity["first_name"] or "",
            last_name=identity["last_name"],
            email=identity["email"],
            phone_number=phones[0],
            company_name=identity["company_name"],
            source=QUO_PROVIDER,
            external_source=QUO_PROVIDER,
            external_id=external_id,
        )
        self.db.add(contact)
        await self.db.flush()
        return contact

    async def _upsert_message(
        self,
        event: QuoWebhookEvent,
        resource: dict[str, Any],
    ) -> None:
        resource_id = _required_string(resource.get("id"), "Quo message ID", 255)
        workspace_phone, contact_phone, direction = _message_participants(resource)
        if workspace_phone != self.phone_number:
            raise QuoSyncError("Quo message sender does not match the selected line")
        context = event.data.get("context")
        contact_ids = _contact_ids(context)

        contact, conversation = await self._resolve_contact_conversation(
            workspace_phone=workspace_phone,
            contact_phone=contact_phone,
            contact_ids=contact_ids,
            channel=MessageChannel.SMS,
        )
        occurred_at = _resource_timestamp(resource)
        candidate_status = _STATUS_BY_EVENT[event.event_type]
        body = _message_body(resource)
        provider_sender_user_id = (
            _bounded_string(resource.get("userId"), 255)
            if direction == MessageDirection.OUTBOUND
            else None
        )
        sender_display_name = (
            await self._sender_display_name(provider_sender_user_id)
            if provider_sender_user_id is not None
            else None
        )
        snapshot = QuoMessageSnapshot(
            provider_message_id=resource_id,
            conversation_id=conversation.id,
            direction=direction,
            sender=contact_phone if direction == MessageDirection.INBOUND else workspace_phone,
            recipient=workspace_phone if direction == MessageDirection.INBOUND else contact_phone,
            body=body,
            status=candidate_status,
            occurred_at=occurred_at,
            sent_at=(
                occurred_at
                if direction == MessageDirection.OUTBOUND
                and candidate_status
                in {MessageStatus.SENT, MessageStatus.FAILED, MessageStatus.DELIVERED}
                else None
            ),
            delivered_at=(
                event.created_at_datetime if candidate_status == MessageStatus.DELIVERED else None
            ),
            external_url=_quo_deep_link(event.data.get("links")),
            error_code=(
                event.event_type.removeprefix("message.")
                if candidate_status == MessageStatus.FAILED
                else None
            ),
            error_message=(
                "Quo reported message delivery failure"
                if candidate_status == MessageStatus.FAILED
                else None
            ),
            provider_sender_user_id=provider_sender_user_id,
            sender_display_name=sender_display_name,
        )
        try:
            reconciled = await reconcile_quo_message(
                self.db,
                workspace_id=self.workspace_id,
                conversation=conversation,
                snapshot=snapshot,
            )
        except QuoReconciliationError as exc:
            raise QuoSyncError(str(exc)) from None

        if not reconciled.created:
            return
        _advance_contact_engagement(contact, occurred_at)
        await self._update_sla(conversation)

        opt_out_manager = OptOutManager()
        is_opt_out, keyword = opt_out_manager.is_opt_out_keyword(body)
        definite_opt_out = bool(
            is_opt_out and keyword and body.strip().casefold() == keyword.casefold()
        )
        if direction == MessageDirection.INBOUND and definite_opt_out:
            contact.sms_consent_status = "opted_out"
            contact.sms_consent_source = "quo_webhook"
            contact.sms_consent_collected_at = event.created_at_datetime
            contact.sms_consent_notes = f"Opted out via Quo reply: {body[:100]}"
            await opt_out_manager.add_opt_out(
                workspace_id=self.workspace_id,
                phone_number=contact_phone,
                db=self.db,
                keyword=keyword,
                source_message_id=reconciled.message.id,
                commit=False,
            )

    async def _upsert_voice_event(
        self,
        event: QuoWebhookEvent,
        resource: dict[str, Any],
    ) -> None:
        call_id = _voice_activity_id(event.event_type, resource)
        # Validate provider-controlled call content before creating CRM rows.
        _voice_occurred_at(event, resource)
        _voice_duration(event.event_type, resource)
        _voice_status(event.event_type, resource)
        _voice_transcript(event.event_type, resource)
        if event.event_type == "call.summary.completed":
            _summary_body(resource)

        context = event.data.get("context")
        contact_ids = _contact_ids(context)
        workspace_phone, contact_phone, direction, fetched_contact = await self._voice_participants(
            resource, context, contact_ids
        )
        if workspace_phone != self.phone_number:
            raise QuoSyncError("Quo call sender does not match the selected line")
        contact, conversation = await self._resolve_contact_conversation(
            workspace_phone=workspace_phone,
            contact_phone=contact_phone,
            contact_ids=contact_ids,
            channel=MessageChannel.VOICE,
            fetched_contact=fetched_contact,
        )
        message, _created = await self._voice_message(
            event=event,
            resource=resource,
            call_id=call_id,
            conversation=conversation,
            direction=direction,
        )
        await self.db.flush()

        occurred_at = message.created_at
        self._update_conversation(
            conversation=conversation,
            message=message,
            occurred_at=occurred_at,
            # Imported calls must not trigger the SMS unread counter.
            created=False,
        )
        _advance_contact_engagement(contact, occurred_at)

    async def _voice_participants(
        self,
        resource: dict[str, Any],
        context_value: object,
        contact_ids: list[str],
    ) -> tuple[str, str, MessageDirection, dict[str, Any] | None]:
        context = context_value if isinstance(context_value, dict) else {}
        direction = _call_direction(resource, context)
        explicit = _explicit_call_participants(resource, direction)
        if explicit is not None:
            explicit_workspace, explicit_contact, explicit_direction = explicit
            return explicit_workspace, explicit_contact, explicit_direction, None

        grouped = _grouped_call_participants(context, direction)
        if grouped is not None:
            grouped_workspace, grouped_contact, grouped_direction = grouped
            return grouped_workspace, grouped_contact, grouped_direction, None

        participants = _call_participant_numbers(resource, context)
        contact_phone, fetched_contact = await self._matched_voice_contact_phone(
            contact_ids,
            participants,
        )
        if contact_phone is None:
            contact_phone = _fallback_contact_phone(participants, direction)

        workspace_phone = _other_participant(participants, contact_phone)
        if direction is None:
            direction = _enrichment_direction(resource, workspace_phone, contact_phone)
        return workspace_phone, contact_phone, direction, fetched_contact

    async def _matched_voice_contact_phone(
        self,
        contact_ids: list[str],
        participants: list[str],
    ) -> tuple[str | None, dict[str, Any] | None]:
        contact = await self._contact_by_external_ids(contact_ids)
        if contact is not None and contact.phone_number:
            candidate = normalize_phone_safe(contact.phone_number)
            if candidate in participants:
                return candidate, None

        for contact_id in contact_ids[:_MAX_CONTACT_IDS]:
            candidate_resource = await self.client.get_contact(contact_id)
            matching_phones = [
                phone for phone in _contact_phones(candidate_resource) if phone in participants
            ]
            if matching_phones:
                return matching_phones[0], candidate_resource
        return None, None

    async def _voice_message(
        self,
        *,
        event: QuoWebhookEvent,
        resource: dict[str, Any],
        call_id: str,
        conversation: Conversation,
        direction: MessageDirection,
    ) -> tuple[Message, bool]:
        result = await self.db.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.workspace_id == self.workspace_id,
                Message.source_provider == QUO_PROVIDER,
                Message.provider_message_id == call_id,
            )
            .with_for_update()
        )
        message = result.scalar_one_or_none()
        if message is not None and message.conversation_id != conversation.id:
            raise QuoSyncError("Quo call is bound to a different conversation")
        if message is not None and message.channel != MessageChannel.VOICE:
            raise QuoSyncError("Quo activity ID is already bound to a non-voice message")

        occurred_at = _voice_occurred_at(event, resource)
        duration = _voice_duration(event.event_type, resource)
        candidate_status = _voice_status(event.event_type, resource)
        candidate_body = _voice_body(event.event_type, resource, direction, duration)
        transcript = _voice_transcript(event.event_type, resource)
        deep_link = _quo_deep_link(event.data.get("links"))
        created = message is None

        if message is None:
            message = Message(
                conversation_id=conversation.id,
                channel=MessageChannel.VOICE,
                direction=direction,
                status=candidate_status,
                body=candidate_body,
                provider_message_id=call_id,
                source_provider=QUO_PROVIDER,
                external_url=deep_link,
                created_at=occurred_at,
                sent_at=occurred_at if direction == MessageDirection.OUTBOUND else None,
                duration_seconds=duration,
                is_voicemail=event.event_type == "call.voicemail.completed",
                transcript=transcript,
                error_code=(
                    _voice_failure_code(event.event_type, resource)
                    if event.event_type in _CALL_LIFECYCLE_EVENTS
                    and candidate_status == MessageStatus.FAILED
                    else None
                ),
                error_message=(
                    "Quo reported an unanswered call"
                    if event.event_type in _CALL_LIFECYCLE_EVENTS
                    and candidate_status == MessageStatus.FAILED
                    else None
                ),
            )
            self.db.add(message)
            return message, True

        message.source_provider = QUO_PROVIDER
        if message.external_url is None and deep_link:
            message.external_url = deep_link

        if (
            event.event_type in _CALL_LIFECYCLE_EVENTS
            and event.api_version == QUO_HISTORICAL_API_VERSION
        ):
            _apply_historical_voice_lifecycle(
                message,
                event_type=event.event_type,
                resource=resource,
                direction=direction,
                status=candidate_status,
                duration=duration,
                body=candidate_body,
                occurred_at=occurred_at,
            )
        elif event.event_type in _CALL_LIFECYCLE_EVENTS:
            _apply_voice_lifecycle(
                message,
                event_type=event.event_type,
                resource=resource,
                direction=direction,
                status=candidate_status,
                occurred_at=occurred_at,
                duration=duration,
                body=candidate_body,
            )
        elif event.event_type == "call.voicemail.completed":
            _apply_voicemail_enrichment(
                message,
                direction=direction,
                status=candidate_status,
                duration=duration,
                body=candidate_body,
                transcript=transcript,
            )
        elif event.event_type == "call.transcript.completed":
            _apply_transcript_enrichment(message, duration=duration, transcript=transcript)
        elif candidate_body != "Quo call summary" and _is_generated_voice_body(message.body):
            message.body = candidate_body

        return message, created

    async def _resolve_contact_conversation(
        self,
        *,
        workspace_phone: str,
        contact_phone: str,
        contact_ids: list[str],
        channel: MessageChannel,
        fetched_contact: dict[str, Any] | None = None,
    ) -> tuple[Contact, Conversation]:
        """Resolve both CRM rows inside this integration's workspace boundary."""
        contact = await self._contact_by_external_ids(contact_ids)
        if contact is None:
            contact = await self._contact_by_phones([contact_phone])
            if contact is not None and len(contact_ids) == 1:
                _link_quo_contact(contact, contact_ids[0])

        if contact is None and fetched_contact is None and contact_ids:
            fetched_contact = await self._fetch_matching_contact(contact_ids, contact_phone)
        if contact is None and fetched_contact is not None:
            contact = await self._upsert_contact_resource(
                fetched_contact,
                fallback_phone=contact_phone,
            )

        if contact is None:
            contact = Contact(
                workspace_id=self.workspace_id,
                first_name="",
                phone_number=contact_phone,
                source=QUO_PROVIDER,
                external_source=QUO_PROVIDER,
                external_id=contact_ids[0] if len(contact_ids) == 1 else None,
            )
            self.db.add(contact)
            await self.db.flush()

        conversation = await self._conversation(
            workspace_phone,
            contact_phone,
            contact,
            channel=channel,
        )
        return contact, conversation

    async def _contact_by_external_ids(self, external_ids: list[str]) -> Contact | None:
        if not external_ids:
            return None
        result = await self.db.execute(
            select(Contact)
            .where(
                Contact.workspace_id == self.workspace_id,
                Contact.external_source == QUO_PROVIDER,
                Contact.external_id.in_(external_ids),
            )
            .with_for_update()
        )
        contacts = {contact.external_id: contact for contact in result.scalars().all()}
        return next((contacts[item] for item in external_ids if item in contacts), None)

    async def _contact_by_phones(self, phones: list[str]) -> Contact | None:
        hashes = [hash_phone(phone) for phone in phones]
        if not hashes:
            return None
        result = await self.db.execute(
            select(Contact)
            .where(
                Contact.workspace_id == self.workspace_id,
                Contact.phone_hash.in_(hashes),
            )
            .order_by(Contact.id)
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _fetch_matching_contact(
        self,
        contact_ids: list[str],
        contact_phone: str,
    ) -> dict[str, Any] | None:
        for contact_id in contact_ids[:_MAX_CONTACT_IDS]:
            resource = await self.client.get_contact(contact_id)
            if contact_phone in _contact_phones(resource):
                return resource
        return None

    async def _conversation(
        self,
        workspace_phone: str,
        contact_phone: str,
        contact: Contact,
        *,
        channel: MessageChannel,
    ) -> Conversation:
        result = await self.db.execute(
            select(Conversation)
            .where(
                Conversation.workspace_id == self.workspace_id,
                Conversation.workspace_phone_hash == hash_phone(workspace_phone),
                Conversation.contact_phone_hash == hash_phone(contact_phone),
            )
            .with_for_update()
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(
                workspace_id=self.workspace_id,
                contact_id=contact.id,
                workspace_phone=workspace_phone,
                contact_phone=contact_phone,
                channel=channel.value,
                status=ConversationStatus.ACTIVE,
                ai_enabled=False,
                source_provider=QUO_PROVIDER,
            )
            self.db.add(conversation)
            await self.db.flush()
        else:
            conversation.contact_id = contact.id
            conversation.ai_enabled = False
            conversation.source_provider = QUO_PROVIDER
        return conversation

    async def _sender_display_name(self, provider_user_id: str) -> str:
        cached = self._sender_display_names.get(provider_user_id)
        if cached is not None:
            return cached
        try:
            resource = await self.client.get_user(provider_user_id)
        except QuoApiError:
            display_name = provider_user_id
        else:
            display_name = _quo_user_display_name(resource, fallback=provider_user_id)
        self._sender_display_names[provider_user_id] = display_name
        return display_name

    def _update_conversation(
        self,
        *,
        conversation: Conversation,
        message: Message,
        occurred_at: datetime,
        created: bool,
    ) -> None:
        conversation.source_provider = QUO_PROVIDER
        if conversation.last_message_at is None or occurred_at >= conversation.last_message_at:
            conversation.last_message_at = occurred_at
            conversation.last_message_preview = message.body[:500]
            conversation.last_message_direction = message.direction.value
            conversation.channel = message.channel.value
        if created and message.direction == MessageDirection.INBOUND:
            conversation.unread_count += 1

    async def _update_sla(self, conversation: Conversation) -> None:
        inbound_result = await self.db.execute(
            select(func.min(Message.created_at)).where(
                Message.conversation_id == conversation.id,
                Message.direction == MessageDirection.INBOUND,
            )
        )
        first_inbound = inbound_result.scalar_one_or_none()
        if first_inbound is None:
            return

        conversation.first_inbound_at = first_inbound
        outbound_at = func.coalesce(Message.sent_at, Message.created_at)
        outbound_result = await self.db.execute(
            select(func.min(outbound_at)).where(
                Message.conversation_id == conversation.id,
                Message.direction == MessageDirection.OUTBOUND,
                outbound_at >= first_inbound,
            )
        )
        first_response = outbound_result.scalar_one_or_none()
        if first_response is None:
            conversation.first_response_at = None
            conversation.first_response_seconds = None
            return
        conversation.first_response_at = first_response
        conversation.first_response_seconds = max(
            0,
            int((first_response - first_inbound).total_seconds()),
        )


def _apply_voice_lifecycle(
    message: Message,
    *,
    event_type: str,
    resource: dict[str, Any],
    direction: MessageDirection,
    status: MessageStatus,
    occurred_at: datetime,
    duration: int | None,
    body: str,
) -> None:
    message.direction = direction
    message.status = status
    message.created_at = occurred_at
    message.sent_at = occurred_at if direction == MessageDirection.OUTBOUND else None
    if duration is not None:
        message.duration_seconds = duration
    if _is_placeholder_voice_body(message.body):
        message.body = body
    if status == MessageStatus.FAILED:
        message.error_code = _voice_failure_code(event_type, resource)
        message.error_message = "Quo reported an unanswered call"
    else:
        message.error_code = None
        message.error_message = None


def _apply_historical_voice_lifecycle(
    message: Message,
    *,
    event_type: str,
    resource: dict[str, Any],
    direction: MessageDirection,
    status: MessageStatus,
    occurred_at: datetime,
    duration: int | None,
    body: str,
) -> None:
    """Fill missing call fields without overwriting a newer webhook enrichment."""
    if message.direction != direction:
        raise QuoSyncError("Quo call direction changed")
    if message.status == MessageStatus.INITIATED:
        message.status = status
    if message.sent_at is None and direction == MessageDirection.OUTBOUND:
        message.sent_at = occurred_at
    if message.duration_seconds is None:
        message.duration_seconds = duration
    if _is_placeholder_voice_body(message.body):
        message.body = body
    if message.status == MessageStatus.FAILED and message.error_code is None:
        message.error_code = _voice_failure_code(event_type, resource)
        message.error_message = "Quo reported an unanswered call"


def _apply_voicemail_enrichment(
    message: Message,
    *,
    direction: MessageDirection,
    status: MessageStatus,
    duration: int | None,
    body: str,
    transcript: str | None,
) -> None:
    message.is_voicemail = True
    if message.status == MessageStatus.INITIATED:
        message.status = status
        message.direction = direction
    if message.duration_seconds is None:
        message.duration_seconds = duration
    if message.transcript is None and transcript:
        message.transcript = transcript
    if _is_generated_voice_body(message.body):
        message.body = body


def _apply_transcript_enrichment(
    message: Message,
    *,
    duration: int | None,
    transcript: str | None,
) -> None:
    if transcript and (
        message.transcript is None
        or not message.transcript.lstrip().startswith("[")
        or len(transcript) >= len(message.transcript)
    ):
        message.transcript = transcript
    if message.duration_seconds is None:
        message.duration_seconds = duration


def _explicit_call_participants(
    resource: dict[str, Any],
    direction: MessageDirection | None,
) -> tuple[str, str, MessageDirection] | None:
    from_phone = _optional_e164(resource.get("from"), "Quo call sender")
    to_phone = _optional_e164(resource.get("to"), "Quo call recipient")
    if from_phone is None and to_phone is None:
        return None
    if from_phone is None or to_phone is None or direction is None:
        raise QuoSyncError("Quo call participants are invalid")
    if direction == MessageDirection.INBOUND:
        return to_phone, from_phone, direction
    return from_phone, to_phone, direction


def _grouped_call_participants(
    context: dict[str, Any],
    direction: MessageDirection | None,
) -> tuple[str, str, MessageDirection] | None:
    participants = context.get("participants")
    if not isinstance(participants, dict):
        return None
    if direction is None:
        raise QuoSyncError("Quo call direction is invalid")

    # simplification: one CRM voice item models a one-to-one call; reject
    # multi-party calls until the timeline supports multiple external contacts.
    workspace = participants.get("workspace")
    external = participants.get("external")
    if not isinstance(workspace, list) or len(workspace) != 1:
        raise QuoSyncError("Quo call participants are invalid")
    if not isinstance(external, list) or len(external) != 1:
        raise QuoSyncError("Quo call participants are invalid")

    workspace_phone = _optional_e164(workspace[0], "Quo workspace call participant")
    contact_phone = _optional_e164(external[0], "Quo external call participant")
    if workspace_phone is None or contact_phone is None or workspace_phone == contact_phone:
        raise QuoSyncError("Quo call participants are invalid")
    return workspace_phone, contact_phone, direction


def _fallback_contact_phone(
    participants: list[str],
    direction: MessageDirection | None,
) -> str:
    if direction == MessageDirection.OUTBOUND:
        return participants[-1]
    # simplification: enrichment payloads have no direction; Quo's first
    # participant is treated as external until a lifecycle event corrects it.
    return participants[0]


def _other_participant(participants: list[str], contact_phone: str) -> str:
    workspace_candidates = [phone for phone in participants if phone != contact_phone]
    if len(workspace_candidates) != 1:
        raise QuoSyncError("Quo call participants are ambiguous")
    return workspace_candidates[0]


def _enrichment_direction(
    resource: dict[str, Any],
    workspace_phone: str,
    contact_phone: str,
) -> MessageDirection:
    from_phone = _optional_e164(resource.get("fromPhoneNumber"), "Quo call source number")
    if from_phone is None or from_phone == contact_phone:
        return MessageDirection.INBOUND
    if from_phone == workspace_phone:
        return MessageDirection.OUTBOUND
    raise QuoSyncError("Quo call source number is not a participant")


def _voice_activity_id(event_type: str, resource: dict[str, Any]) -> str:
    if event_type in {"call.transcript.completed", "call.summary.completed"}:
        return _required_string(resource.get("callId"), "Quo call ID", 255)
    if event_type == "call.voicemail.completed" and resource.get("callId") is not None:
        return _required_string(resource.get("callId"), "Quo call ID", 255)
    return _required_string(resource.get("id"), "Quo call/activity ID", 255)


def _call_participant_numbers(
    resource: dict[str, Any],
    context: dict[str, Any],
) -> list[str]:
    values = resource.get("participants")
    if not isinstance(values, list):
        values = context.get("participants")
    if not isinstance(values, list) or len(values) != 2:
        raise QuoSyncError("Quo call participants are invalid")

    participants: list[str] = []
    for value in values:
        raw_phone = value.get("phoneNumber") if isinstance(value, dict) else value
        phone = _optional_e164(raw_phone, "Quo call participant")
        if phone is None or phone in participants:
            raise QuoSyncError("Quo call participants are invalid")
        participants.append(phone)
    return participants


def _call_direction(
    resource: dict[str, Any],
    context: dict[str, Any],
) -> MessageDirection | None:
    value = resource.get("direction")
    if value is None:
        value = context.get("direction")
    if value is None:
        return None
    if value == "incoming":
        return MessageDirection.INBOUND
    if value == "outgoing":
        return MessageDirection.OUTBOUND
    raise QuoSyncError("Quo call direction is invalid")


def _voice_occurred_at(event: QuoWebhookEvent, resource: dict[str, Any]) -> datetime:
    if resource.get("createdAt") is not None:
        return _resource_timestamp(resource)
    if event.event_type == "call.summary.completed":
        return event.created_at_datetime
    raise QuoSyncError("Quo call timestamp is missing")


def _voice_duration(event_type: str, resource: dict[str, Any]) -> int | None:
    if event_type in {"call.missed", "call.summary.completed"}:
        return None
    value = resource.get("duration")
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_CALL_DURATION_SECONDS
    ):
        raise QuoSyncError("Quo call duration is invalid")
    return value


def _voice_status(event_type: str, resource: dict[str, Any]) -> MessageStatus:
    if event_type == "call.completed":
        status = _required_string(resource.get("status"), "Quo call status", 50)
        if status in _CALL_SUCCESS_STATUSES:
            return MessageStatus.COMPLETED
        if status in _CALL_FAILURE_STATUSES:
            return MessageStatus.FAILED
        raise QuoSyncError("Quo call status is invalid")
    if event_type in {"call.missed", "call.voicemail.completed"}:
        return MessageStatus.FAILED
    return MessageStatus.INITIATED


def _voice_failure_code(event_type: str, resource: dict[str, Any]) -> str:
    if event_type == "call.missed":
        return "missed"
    return _required_string(resource.get("status"), "Quo call status", 50)


def _voice_body(
    event_type: str,
    resource: dict[str, Any],
    direction: MessageDirection,
    duration: int | None,
) -> str:
    if event_type == "call.summary.completed":
        return _summary_body(resource) or "Quo call summary"
    if event_type == "call.transcript.completed":
        return "Quo call transcript"

    direction_label = "Incoming" if direction == MessageDirection.INBOUND else "Outgoing"
    duration_label = f" · {_format_duration(duration)}" if duration is not None else ""
    if event_type == "call.voicemail.completed":
        return f"{direction_label} voicemail{duration_label}"
    if event_type == "call.missed":
        return f"{direction_label} call missed"

    provider_status = _required_string(resource.get("status"), "Quo call status", 50)
    status_label = {
        "answered": "answered",
        "unanswered": "unanswered",
        "forwarded": "forwarded",
        "ai-handled": "handled by Quo AI",
    }.get(provider_status)
    if status_label is None:
        raise QuoSyncError("Quo call status is invalid")
    return f"{direction_label} call {status_label}{duration_label}"


def _summary_body(resource: dict[str, Any]) -> str:
    summary = _string_list(resource.get("summary"), "Quo call summary")
    next_steps = _string_list(resource.get("nextSteps"), "Quo call next steps")
    body = " ".join(summary)
    if next_steps:
        body = (
            f"{body} Next steps: {'; '.join(next_steps)}"
            if body
            else (f"Next steps: {'; '.join(next_steps)}")
        )
    return body[:_MAX_SUMMARY_CHARS]


def _string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 100:
        raise QuoSyncError(f"{label} is invalid")
    values: list[str] = []
    for item in value:
        normalized = _strict_string(item, _MAX_SUMMARY_CHARS)
        if normalized is None:
            raise QuoSyncError(f"{label} is invalid")
        values.append(normalized)
    return values


def _voice_transcript(event_type: str, resource: dict[str, Any]) -> str | None:
    if event_type == "call.voicemail.completed":
        caption = resource.get("caption")
        if caption is None:
            return None
        normalized = _strict_string(caption, _MAX_TRANSCRIPT_CHARS)
        if normalized is None:
            raise QuoSyncError("Quo voicemail caption is invalid")
        return normalized
    if event_type != "call.transcript.completed":
        return None

    dialogue = resource.get("dialogue")
    if not isinstance(dialogue, list) or len(dialogue) > 10_000:
        raise QuoSyncError("Quo call transcript is invalid")
    normalized_dialogue: list[dict[str, Any]] = []
    for entry in dialogue:
        if not isinstance(entry, dict):
            raise QuoSyncError("Quo call transcript is invalid")
        identifier = _required_string(
            entry.get("identifier"),
            "Quo transcript speaker",
            255,
        )
        content = _required_string(
            entry.get("content"),
            "Quo transcript content",
            _MAX_TRANSCRIPT_CHARS,
        )
        start = _transcript_offset(entry.get("start"))
        end = _transcript_offset(entry.get("end"))
        if end < start:
            raise QuoSyncError("Quo call transcript timing is invalid")
        normalized_entry: dict[str, Any] = {
            "identifier": identifier,
            "content": content,
            "start": start,
            "end": end,
        }
        speaker_type = _strict_string(entry.get("speakerType"), 50)
        if speaker_type:
            normalized_entry["speakerType"] = speaker_type
        normalized_dialogue.append(normalized_entry)

    transcript = json.dumps(normalized_dialogue, separators=(",", ":"))
    if len(transcript) > _MAX_TRANSCRIPT_CHARS:
        raise QuoSyncError("Quo call transcript is too large")
    return transcript


def _transcript_offset(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise QuoSyncError("Quo call transcript timing is invalid")
    return value


def _format_duration(duration: int | None) -> str:
    if duration is None:
        return ""
    minutes, seconds = divmod(duration, 60)
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _is_placeholder_voice_body(body: str) -> bool:
    return body in {"Quo call transcript", "Quo call summary"}


def _is_generated_voice_body(body: str) -> bool:
    return _is_placeholder_voice_body(body) or body.startswith(
        ("Incoming call ", "Outgoing call ", "Incoming voicemail", "Outgoing voicemail")
    )


def _optional_e164(value: Any, label: str) -> str | None:
    if value is None:
        return None
    normalized = _normalize_e164(value)
    if normalized is None:
        raise QuoSyncError(f"{label} is invalid")
    return normalized


def _message_participants(
    resource: dict[str, Any],
) -> tuple[str, str, MessageDirection]:
    direction = resource.get("direction")
    sender = _normalize_e164(resource.get("senderIdentifier"))
    recipients_value = resource.get("recipientIdentifiers")
    if not isinstance(recipients_value, list) or len(recipients_value) != 1:
        raise QuoSyncError("Quo message participants are invalid")
    recipient = _normalize_e164(recipients_value[0])
    if sender is None or recipient is None:
        raise QuoSyncError("Quo message participants are invalid")
    if direction == "incoming":
        return recipient, sender, MessageDirection.INBOUND
    if direction == "outgoing":
        return sender, recipient, MessageDirection.OUTBOUND
    raise QuoSyncError("Quo message direction is invalid")


def _contact_ids(context: Any) -> list[str]:
    if not isinstance(context, dict):
        return []
    contacts = context.get("contacts")
    values = contacts.get("ids") if isinstance(contacts, dict) else None
    if not isinstance(values, list):
        values = context.get("contactIds")
    if not isinstance(values, list):
        return []
    ids: list[str] = []
    for value in values[:_MAX_CONTACT_IDS]:
        item = _strict_string(value, 255)
        if item and item not in ids:
            ids.append(item)
    return ids


def _contact_phones(resource: dict[str, Any]) -> list[str]:
    values = resource.get("phoneNumbers")
    phones: list[str] = []
    if isinstance(values, list):
        for value in values[:_MAX_CONTACT_VALUES]:
            normalized = _normalize_e164(value)
            if normalized and normalized not in phones:
                phones.append(normalized)
    return phones


def _contact_identity(resource: dict[str, Any]) -> dict[str, str | None]:
    emails = resource.get("emails")
    email = None
    if isinstance(emails, list):
        for item in emails[:_MAX_CONTACT_VALUES]:
            email = _bounded_string(item, 320)
            if email:
                break
    return {
        "first_name": _bounded_string(resource.get("firstName"), 100),
        "last_name": _bounded_string(resource.get("lastName"), 100),
        "email": email.lower() if email else None,
        "company_name": _bounded_string(resource.get("company"), 255),
    }


def _link_quo_contact(contact: Contact, external_id: str) -> None:
    if not contact.external_source and not contact.external_id:
        contact.external_source = QUO_PROVIDER
        contact.external_id = external_id
    elif contact.external_source == QUO_PROVIDER and not contact.external_id:
        contact.external_id = external_id
    if not contact.source:
        contact.source = QUO_PROVIDER


def _fill_blank_identity(
    contact: Contact,
    identity: dict[str, str | None],
    phones: list[str],
) -> None:
    for field in ("first_name", "last_name", "email", "company_name"):
        current = getattr(contact, field)
        value = identity[field]
        if (current is None or not current.strip()) and value:
            setattr(contact, field, value)
    if not contact.phone_number.strip() and phones:
        contact.phone_number = phones[0]


def _message_body(resource: dict[str, Any]) -> str:
    body = _bounded_string(resource.get("text"), 1_000_000) or ""
    media = resource.get("media")
    labels: list[str] = []
    if isinstance(media, list):
        for item in media[:_MAX_MEDIA_ITEMS]:
            if not isinstance(item, dict) or not _bounded_string(item.get("url"), 2048):
                continue
            media_type = _bounded_string(item.get("type"), 100) or "attachment"
            labels.append(f"[Quo attachment: {media_type}]")
    return "\n\n".join(part for part in (body, "\n".join(labels)) if part)


def _quo_deep_link(links: Any) -> str | None:
    if not isinstance(links, dict):
        return None
    deep_link = _strict_string(links.get("quo"), 2048) or _strict_string(
        links.get("deepLink"), 2048
    )
    if not deep_link:
        return None
    parsed = urlparse(deep_link)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname != "my.quo.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    return deep_link


def _resource_timestamp(resource: dict[str, Any]) -> datetime:
    value = _required_string(resource.get("createdAt"), "Quo resource timestamp", 64)
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QuoSyncError("Quo resource timestamp is invalid") from None
    if timestamp.tzinfo is None:
        raise QuoSyncError("Quo resource timestamp lacks a timezone")
    return timestamp.astimezone(UTC)


def _advance_contact_engagement(contact: Contact, occurred_at: datetime) -> None:
    if contact.last_engaged_at is None or occurred_at > contact.last_engaged_at:
        contact.last_engaged_at = occurred_at


def _normalize_e164(value: Any) -> str | None:
    raw = _bounded_string(value, 64)
    if not raw:
        return None
    normalized = normalize_phone_safe(raw)
    return normalized if normalized and _E164_RE.fullmatch(normalized) else None


def _required_string(value: Any, label: str, limit: int) -> str:
    normalized = _strict_string(value, limit)
    if not normalized:
        raise QuoSyncError(f"{label} is missing or invalid")
    return normalized


def _strict_string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > limit:
        return None
    return normalized


def _quo_user_display_name(resource: Any, *, fallback: str) -> str:
    if not isinstance(resource, dict):
        return fallback
    parts = [
        value
        for key in ("firstName", "lastName")
        if (value := _strict_string(resource.get(key), 255)) is not None
    ]
    full_name = " ".join(parts)
    if full_name and len(full_name) <= 255:
        return full_name
    return _strict_string(resource.get("email"), 255) or fallback


def _bounded_string(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized[:limit]
