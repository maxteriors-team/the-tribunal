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
from app.core.encryption import hash_phone, hash_value
from app.core.metrics import observe_sms_sent
from app.core.roles import WorkspaceRole
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageChannel
from app.models.phone_number import PhoneNumber
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.agents import get_default_agent
from app.services.ai.text_agent import schedule_ai_response
from app.services.approval.command_processor_service import command_processor_service
from app.services.campaigns.conversation_syncer import CampaignConversationSyncer
from app.services.push_notifications import push_notification_service
from app.services.telephony.inbound_types import InboundMessageIngestResult

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


InboundMessageIngestor = Callable[
    [AsyncSession, "InboundTextEvent"],
    Awaitable[InboundMessageIngestResult],
]


@dataclass(slots=True, frozen=True)
class InboundTextEvent:
    """Normalized inbound text event, optionally carrying provider media."""

    provider_message_id: str
    from_number: str
    to_number: str
    body: str
    workspace_id: uuid.UUID
    channel: MessageChannel
    response_channel: str = "sms"
    media_count: int = 0
    media_preview: str | None = None
    # Meta Page-Scoped ID for Messenger/Instagram DMs. When set, ``from_number``
    # and ``to_number`` hold Meta object IDs rather than phone numbers, and the
    # thread is keyed on this PSID instead of a phone pair.
    messenger_psid: str | None = None
    messenger_display_name: str | None = None
    #: End of Meta's 24h standard messaging window, refreshed by this message.
    messenger_window_expires_at: datetime | None = None


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

    # Media-only events have no text to interpret as a command or operator
    # assistant prompt, but still need normal contact-message ingestion.
    #
    # DMs are excluded from both privileged paths on purpose: a PSID is not a
    # phone number, so approval-command and operator lookups would be hashing an
    # unrelated identifier against user phone hashes. A numeric PSID that
    # happened to collide with a staff member's digits would hand a stranger the
    # CRM assistant, which is not a risk worth carrying for a lookup that can
    # never legitimately match.
    if event.body.strip() and event.messenger_psid is None:
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

            # Texting the assistant from a registered phone is the same
            # privileged surface as the in-app chat, so it carries the same
            # role. Resolved from the membership rather than assumed: without
            # it a field technician with their number on file would reach every
            # CRM tool by text. Missing membership fails closed to the field
            # tier, which holds no assistant tool capability.
            role = await _operator_workspace_role(db, operator_user.id, event.workspace_id)
            await process_assistant_message(
                db=db,
                workspace_id=event.workspace_id,
                user_id=operator_user.id,
                message=event.body,
                role=role,
                response_channel=event.response_channel,
                sms_from_number=event.to_number,
                sms_to_number=event.from_number,
            )
            return None

    ingest_result = await ingest_message(db, event)
    if not ingest_result.created:
        log.info(
            "inbound_text_side_effects_duplicate_skipped",
            message_id=str(ingest_result.message.id),
        )
        return ingest_result.message
    await run_inbound_text_side_effects(
        db=db,
        message=ingest_result.message,
        event=event,
        log=log,
        conversation_syncer=conversation_syncer,
        schedule_ai_response_fn=schedule_ai_response_fn,
        push_service=push_service,
    )
    return ingest_result.message


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
        body=event.body or event.media_preview or "Media attachment received",
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
    messenger_psid: str | None = None,
    messenger_display_name: str | None = None,
    messenger_window_expires_at: datetime | None = None,
) -> InboundMessageIngestResult:
    """Persist an inbound text and report whether this delivery created it.

    When ``messenger_psid`` is set the thread is keyed on that Page-Scoped ID
    instead of the phone pair, and ``from_number``/``to_number`` are Meta object
    IDs kept only for logging.
    """
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
            return InboundMessageIngestResult(existing_message, created=False)

    if messenger_psid:
        conversation = await _get_or_create_messenger_conversation(
            db=db,
            messenger_psid=messenger_psid,
            display_name=messenger_display_name,
            workspace_id=workspace_id,
            channel=stored_channel,
            log=log,
        )
        # Refreshed on every inbound user message: Meta's window restarts from
        # the person's last message, never from our replies.
        if messenger_window_expires_at is not None:
            conversation.messenger_window_expires_at = messenger_window_expires_at
    else:
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
        return InboundMessageIngestResult(existing_message, created=False)

    await db.refresh(message)
    return InboundMessageIngestResult(message, created=True)


async def _get_or_create_text_conversation(
    *,
    db: AsyncSession,
    workspace_phone: str,
    contact_phone: str,
    workspace_id: uuid.UUID,
    channel: str,
    log: Any,
) -> Conversation:
    # The phone columns are Fernet-encrypted, so the match runs on the
    # deterministic lookup hashes.
    result = await db.execute(
        select(Conversation).where(
            Conversation.workspace_id == workspace_id,
            Conversation.workspace_phone_hash == hash_phone(workspace_phone),
            Conversation.contact_phone_hash == hash_phone(contact_phone),
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


async def _get_or_create_messenger_conversation(
    *,
    db: AsyncSession,
    messenger_psid: str,
    display_name: str | None,
    workspace_id: uuid.UUID,
    channel: str,
    log: Any,
) -> Conversation:
    """Find or open the DM thread for one Page-Scoped ID.

    ``contact_id`` stays NULL until a phone or email surfaces in the thread: a
    PSID identifies someone only to the Page that received it, so there is
    nothing to match an existing contact on and inventing a placeholder contact
    would pollute the CRM with unreachable records.
    """
    psid_hash = hash_value(messenger_psid)
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.messenger_psid_hash == psid_hash,
            )
        )
    ).scalar_one_or_none()

    if conversation is not None:
        if display_name and conversation.messenger_display_name != display_name:
            conversation.messenger_display_name = display_name
        return conversation

    conversation = Conversation(
        workspace_id=workspace_id,
        contact_id=None,
        messenger_psid=messenger_psid,
        messenger_display_name=display_name,
        channel=channel,
        assigned_agent_id=await _resolve_default_messenger_agent_id(db, workspace_id),
        ai_enabled=True,
        initiated_by="external",
    )
    db.add(conversation)
    await db.flush()
    log.info("messenger_conversation_created", conversation_id=str(conversation.id))
    return conversation


async def _resolve_default_messenger_agent_id(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the workspace's default agent for a DM thread, if it has one.

    There is no Page-to-agent mapping the way a phone number has one, so a DM
    always lands on the workspace default. ``None`` when the workspace has no
    active agent: the DM still lands in the inbox, it just gets no AI reply.
    """
    default_agent = await get_default_agent(db, workspace_id)
    if default_agent is None:
        logger.warning("messenger_no_active_agent", workspace_id=str(workspace_id))
        return None
    return default_agent.id


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

    Prefers an explicit :attr:`PhoneNumber.assigned_agent_id`, but only while it
    still points at a live agent -- a number left pointing at a deleted or
    deactivated agent falls through to the workspace default rather than
    silently muting the AI. Read-only: never creates an agent.

    Returns ``None`` when the workspace has no active agent at all. The message
    is still stored and shown in the inbox; it just gets no AI reply, which is
    the honest outcome -- the alternative is inventing a script and sending it
    to a real customer under the operator's name.
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
    if assigned_agent_id is not None and await _agent_is_live(db, workspace_id, assigned_agent_id):
        return assigned_agent_id

    default_agent = await get_default_agent(db, workspace_id)
    if default_agent is None:
        # Warning, not info: inbound texts are now landing with no AI reply and
        # only a human will move them.
        logger.warning(
            "inbound_no_active_agent",
            workspace_id=str(workspace_id),
            workspace_phone=workspace_phone,
        )
        return None

    logger.info(
        "inbound_default_agent_fallback",
        workspace_id=str(workspace_id),
        agent_id=str(default_agent.id),
    )
    return default_agent.id


async def _agent_is_live(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
) -> bool:
    """Return whether this agent still exists, is active, and is undeleted."""
    result = await db.execute(
        select(Agent.id).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
            Agent.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def _operator_workspace_role(
    db: AsyncSession,
    user_id: int,
    workspace_id: uuid.UUID,
) -> str:
    """Return the operator's role in this workspace, or the lowest tier.

    Fail-closed: a user with no membership row resolves to ``technician``, which
    the capability matrix maps to the field tier and which therefore holds no
    CRM assistant tool.
    """
    result = await db.execute(
        select(WorkspaceMembership.role).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    role: str | None = result.scalar_one_or_none()
    return role or WorkspaceRole.TECHNICIAN.value


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
    if not event.body.strip() or not conversation.ai_enabled or conversation.ai_paused:
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
