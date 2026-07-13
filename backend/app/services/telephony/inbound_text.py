"""Shared inbound text-message ingestion side effects."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_phone
from app.core.metrics import observe_sms_sent
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.agents import ensure_default_agent
from app.services.ai.text_agent import schedule_ai_response
from app.services.approval.command_processor_service import command_processor_service
from app.services.campaigns.conversation_syncer import CampaignConversationSyncer
from app.services.push_notifications import push_notification_service

logger = structlog.get_logger()


class CommandProcessor(Protocol):
    """Approval-command processor protocol."""

    async def try_process_command(
        self,
        *,
        db: AsyncSession,
        from_number: str,
        to_number: str,
        body: str,
    ) -> bool:
        """Return True when the inbound text was consumed as a command."""
        ...


class ConversationSyncer(Protocol):
    """Campaign-conversation sync protocol."""

    async def sync_conversation(
        self, db: AsyncSession, conversation: Conversation, log: Any | None = None
    ) -> Any:
        """Sync campaign-owned conversation settings."""
        ...


class ScheduleAIResponse(Protocol):
    """AI debounce scheduler protocol."""

    async def __call__(
        self,
        *,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        delay_ms: int,
    ) -> None:
        """Schedule a debounced AI text response."""
        ...


class PushNotificationService(Protocol):
    """Push notification service protocol."""

    async def send_to_workspace_members(
        self,
        db: AsyncSession,
        workspace_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> bool:
        """Send a push notification to workspace members."""
        ...


class OperatorChecker(Protocol):
    """Workspace operator lookup protocol."""

    async def __call__(
        self, db: AsyncSession, from_number: str, workspace_id: uuid.UUID
    ) -> User | None:
        """Return an operator user for this inbound number, if any."""
        ...


InboundMessageIngestor = Callable[[AsyncSession, "InboundTextEvent"], Awaitable[Message]]


@dataclass(slots=True, frozen=True)
class InboundTextEvent:
    """Normalized inbound text event."""

    provider_message_id: str
    from_number: str
    to_number: str
    body: str
    workspace_id: uuid.UUID
    channel: MessageChannel
    response_channel: str = "sms"


_conversation_syncer = CampaignConversationSyncer()


async def process_inbound_text_event(
    *,
    db: AsyncSession,
    event: InboundTextEvent,
    ingest_message: InboundMessageIngestor,
    log: Any,
    command_processor: CommandProcessor = command_processor_service,
    conversation_syncer: ConversationSyncer = _conversation_syncer,
    schedule_ai_response_fn: ScheduleAIResponse = schedule_ai_response,
    push_service: PushNotificationService = push_notification_service,
    check_operator_fn: OperatorChecker | None = None,
) -> Message | None:
    """Run the shared inbound text pipeline.

    Returns the ingested ``Message`` for normal contact replies. Returns ``None``
    when the text was consumed as an approval command or operator assistant input.
    """
    operator_checker = check_operator_fn or check_operator_by_phone

    is_command = await command_processor.try_process_command(
        db=db,
        from_number=event.from_number,
        to_number=event.to_number,
        body=event.body,
    )
    if is_command:
        log.info("processed_approval_command", from_number=event.from_number)
        return None

    operator_user = await operator_checker(db, event.from_number, event.workspace_id)
    if operator_user:
        log.info("detected_operator_sms", user_id=operator_user.id)
        from app.services.ai.crm_assistant import process_assistant_message

        await process_assistant_message(
            db=db,
            workspace_id=event.workspace_id,
            user_id=operator_user.id,
            message=event.body,
            response_channel=event.response_channel,
            sms_from_number=event.to_number,
            sms_to_number=event.from_number,
        )
        return None

    message = await ingest_message(db, event)
    await run_inbound_text_side_effects(
        db=db,
        message=message,
        event=event,
        log=log,
        conversation_syncer=conversation_syncer,
        schedule_ai_response_fn=schedule_ai_response_fn,
        push_service=push_service,
    )
    return message


async def run_inbound_text_side_effects(
    *,
    db: AsyncSession,
    message: Message,
    event: InboundTextEvent,
    log: Any,
    conversation_syncer: ConversationSyncer = _conversation_syncer,
    schedule_ai_response_fn: ScheduleAIResponse = schedule_ai_response,
    push_service: PushNotificationService = push_notification_service,
) -> None:
    """Run AI, drip, campaign, and notification side effects for an inbound text."""
    conversation = await _load_conversation(db, message.conversation_id)
    if conversation is not None:
        await _schedule_ai_if_enabled(
            db=db,
            conversation=conversation,
            message=message,
            event=event,
            log=log,
            conversation_syncer=conversation_syncer,
            schedule_ai_response_fn=schedule_ai_response_fn,
        )
        await _pause_drip_enrollments(
            db=db,
            conversation=conversation,
            workspace_id=event.workspace_id,
            log=log,
        )
        await _handle_campaign_reply(db=db, message=message, log=log)

    await _send_push_notification(
        db=db,
        message=message,
        body=event.body,
        workspace_id=event.workspace_id,
        push_service=push_service,
        log=log,
    )


async def persist_inbound_text_message(
    *,
    db: AsyncSession,
    provider_message_id: str,
    from_number: str,
    to_number: str,
    body: str,
    workspace_id: uuid.UUID,
    channel: MessageChannel,
    log: Any,
    conversation_channel: str | None = None,
) -> Message:
    """Persist an inbound text message with provider-neutral channel attribution."""
    stored_channel = conversation_channel or channel.value
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
            log.info("inbound_text_duplicate_ignored", message_id=str(existing_message.id))
            return existing_message

    conversation = await _get_or_create_text_conversation(
        db=db,
        workspace_phone=to_number,
        contact_phone=from_number,
        workspace_id=workspace_id,
        channel=stored_channel,
        log=log,
    )

    message = Message(
        conversation_id=conversation.id,
        provider_message_id=provider_message_id,
        direction="inbound",
        channel=channel,
        body=body,
        status="received",
    )
    db.add(message)
    observe_sms_sent(workspace_id, direction="inbound")

    conversation.last_message_preview = body[:255]
    conversation.last_message_at = datetime.now(UTC)
    conversation.last_message_direction = "inbound"
    conversation.unread_count += 1

    # Speed-to-lead SLA: anchor the lead's first inbound touch.
    from app.services.sla import mark_inbound_lead

    # Only the first inbound message makes this a "new lead"; capture it before
    # mark_inbound_lead stamps the anchor so we open a pipeline card once per
    # conversation instead of on every reply.
    is_first_inbound = conversation.first_inbound_at is None
    mark_inbound_lead(conversation)

    if conversation.contact_id:
        try:
            from app.services.contacts.engagement_score import record_engagement

            await record_engagement(db, conversation.contact_id)
        except Exception as exc:
            log.warning("engagement_update_failed", error=str(exc))

        if is_first_inbound:
            # Auto-open a pipeline card so the inbound-SMS lead lands on the
            # Opportunities board. Deduped + workspace-gated inside the helper.
            try:
                from app.services.opportunities import open_lead_opportunity

                contact = await db.get(Contact, conversation.contact_id)
                if contact is not None:
                    await open_lead_opportunity(db, workspace_id, contact, source="inbound_sms")
            except Exception as exc:
                log.warning("auto_pipeline_failed", error=str(exc))

    try:
        await db.commit()
    except IntegrityError:
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
            raise
        log.info("inbound_text_duplicate_race_ignored", message_id=str(existing_message.id))
        return existing_message

    await db.refresh(message)
    return message


async def _get_or_create_text_conversation(
    *,
    db: AsyncSession,
    workspace_phone: str,
    contact_phone: str,
    workspace_id: uuid.UUID,
    channel: str,
    log: Any,
) -> Conversation:
    result = await db.execute(
        select(Conversation).where(
            Conversation.workspace_id == workspace_id,
            Conversation.workspace_phone == workspace_phone,
            Conversation.contact_phone == contact_phone,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        if conversation.contact_id is None:
            contact = await _find_contact_by_phone(db, workspace_id, contact_phone)
            if contact is not None:
                conversation.contact_id = contact.id
                await db.commit()
        if conversation.assigned_agent_id is None:
            conversation.assigned_agent_id = await _resolve_existing_contact_agent_id(
                db,
                workspace_id,
                conversation.contact_id,
            )
            if conversation.assigned_agent_id is None:
                conversation.assigned_agent_id = await _resolve_default_agent_id(
                    db,
                    workspace_id,
                    workspace_phone,
                )
            if conversation.assigned_agent_id is not None:
                await db.commit()
        return conversation

    contact = await _find_contact_by_phone(db, workspace_id, contact_phone)
    assigned_agent_id = await _resolve_existing_contact_agent_id(
        db,
        workspace_id,
        contact.id if contact else None,
    )
    if assigned_agent_id is None:
        assigned_agent_id = await _resolve_default_agent_id(db, workspace_id, workspace_phone)

    conversation = Conversation(
        workspace_id=workspace_id,
        contact_id=contact.id if contact else None,
        workspace_phone=workspace_phone,
        contact_phone=contact_phone,
        channel=channel,
        assigned_agent_id=assigned_agent_id,
        ai_enabled=True,
    )
    db.add(conversation)
    await db.flush()
    log.info(
        "conversation_created",
        conversation_id=str(conversation.id),
        contact_id=contact.id if contact else None,
    )
    return conversation


async def _find_contact_by_phone(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_phone: str,
) -> Contact | None:
    from app.utils.phone import phone_lookup_variants

    variants = phone_lookup_variants(contact_phone)
    phone_hashes = [hash_phone(variant) for variant in variants]
    if not phone_hashes:
        return None
    result = await db.execute(
        select(Contact)
        .where(
            Contact.workspace_id == workspace_id,
            Contact.phone_hash.in_(phone_hashes),
        )
        .limit(1)
    )
    return result.scalars().first()


async def _resolve_existing_contact_agent_id(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_id: int | None,
) -> uuid.UUID | None:
    """Return an agent already assigned to another conversation for this contact."""
    if contact_id is None:
        return None

    result = await db.execute(
        select(Conversation.assigned_agent_id)
        .where(
            Conversation.workspace_id == workspace_id,
            Conversation.contact_id == contact_id,
            Conversation.channel.in_(("sms", "imessage")),
            Conversation.assigned_agent_id.isnot(None),
        )
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _resolve_default_agent_id(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    workspace_phone: str,
) -> uuid.UUID | None:
    """Return the agent that should own an inbound conversation for this number.

    Prefers an explicit :attr:`PhoneNumber.assigned_agent_id` when one is
    configured. When the number has no assigned agent, falls back to the
    workspace's default agent via :func:`ensure_default_agent` (auto-creating
    one from a template if none exists) so brand-new leads texting/calling the
    business number always get an AI responder instead of ``no_agent_assigned``.
    ``ensure_default_agent`` flushes but does not commit; the caller owns the
    transaction.
    """
    result = await db.execute(
        select(PhoneNumber.assigned_agent_id).where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.is_active.is_(True),
            (PhoneNumber.phone_number == workspace_phone)
            | (PhoneNumber.mac_relay_sender_id == workspace_phone),
        )
    )
    assigned_agent_id = result.scalar_one_or_none()
    if assigned_agent_id is not None:
        return assigned_agent_id

    default_agent = await ensure_default_agent(db, workspace_id)
    logger.info(
        "inbound_default_agent_fallback",
        workspace_id=str(workspace_id),
        agent_id=str(default_agent.id),
    )
    return default_agent.id


async def check_operator_by_phone(
    db: AsyncSession,
    from_number: str,
    workspace_id: uuid.UUID,
) -> User | None:
    """Check if the sender is a workspace member texting from their registered phone."""
    from app.utils.phone import phone_lookup_variants

    phone_hashes = [hash_phone(variant) for variant in phone_lookup_variants(from_number)]
    if not phone_hashes:
        return None

    result = await db.execute(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            User.phone_hash.in_(phone_hashes),
            WorkspaceMembership.workspace_id == workspace_id,
            User.is_active == True,  # noqa: E712
        )
    )
    user: User | None = result.scalar_one_or_none()
    return user


async def _load_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID | None,
) -> Conversation | None:
    if conversation_id is None:
        return None
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    return result.scalar_one_or_none()


async def _schedule_ai_if_enabled(
    *,
    db: AsyncSession,
    conversation: Conversation,
    message: Message,
    event: InboundTextEvent,
    log: Any,
    conversation_syncer: ConversationSyncer,
    schedule_ai_response_fn: ScheduleAIResponse,
) -> None:
    await conversation_syncer.sync_conversation(db, conversation, log)
    if not conversation.ai_enabled or conversation.ai_paused:
        return

    # Keep this delay short: it is only the debounce window for batching rapid
    # inbound texts. Agent-level human-like timing is applied after the AI has
    # generated the exact reply, so reply length can influence the final wait.
    delay_ms = settings.ai_response_delay_ms

    await schedule_ai_response_fn(
        conversation_id=message.conversation_id,
        workspace_id=event.workspace_id,
        delay_ms=delay_ms,
    )


async def _pause_drip_enrollments(
    *,
    db: AsyncSession,
    conversation: Conversation,
    workspace_id: uuid.UUID,
    log: Any,
) -> None:
    try:
        from app.services.reactivation.drip_runner import handle_inbound_reply

        if conversation.contact_id:
            await handle_inbound_reply(
                contact_id=conversation.contact_id,
                workspace_id=workspace_id,
                db=db,
            )
    except Exception as exc:
        log.exception("drip_pause_on_reply_failed", error=str(exc))


async def _handle_campaign_reply(*, db: AsyncSession, message: Message, log: Any) -> None:
    try:
        from app.services.campaigns.reply_handler import handle_campaign_reply

        await handle_campaign_reply(
            db=db,
            message=message,
            log=log,
        )
    except Exception as exc:
        log.exception("campaign_reply_handling_failed", error=str(exc))


async def _send_push_notification(
    *,
    db: AsyncSession,
    message: Message,
    body: str,
    workspace_id: uuid.UUID,
    push_service: PushNotificationService,
    log: Any,
) -> None:
    try:
        truncated_body = body[:100] + "..." if len(body) > 100 else body
        await push_service.send_to_workspace_members(
            db=db,
            workspace_id=str(workspace_id),
            title="New Message",
            body=truncated_body,
            data={
                "type": "message",
                "conversationId": str(message.conversation_id),
                "screen": f"/(tabs)/messages/{message.conversation_id}",
            },
            notification_type="message",
            channel_id="messages",
        )
    except Exception as exc:
        log.exception("push_notification_failed", error=str(exc))
