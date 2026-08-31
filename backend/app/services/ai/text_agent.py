"""Text agent orchestrator for AI-powered SMS responses.

Handles:
- Inbound message processing with AI response generation
- Response scheduling with debounce for message batching
- AI-powered opt-out detection

This module delegates to focused submodules:
- message_context_builder: Conversation context assembly
- text_response_generator: LLM response generation
- opt_out_detector: Opt-out keyword detection and AI classification
"""

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import observe_ai_text_response_failure
from app.models.agent import Agent
from app.models.contact import Contact
from app.models.conversation import Conversation, Message
from app.models.workspace import Workspace
from app.services.ai.message_context_builder import build_message_context
from app.services.ai.openai_credentials import (
    OpenAICredentialError,
    resolve_openai_credentials,
)
from app.services.ai.opt_out_detector import (
    classify_opt_out_intent,
    has_potential_opt_out_keywords,
)
from app.services.ai.text_response_generator import generate_text_response
from app.services.ai.text_response_timing import calculate_text_response_delay_ms
from app.services.notifications import notify_workspace_event
from app.services.quotes.acceptance_detector import (
    classify_quote_acceptance,
    find_outstanding_quote,
    has_potential_acceptance_keywords,
)
from app.services.quotes.acceptance_handoff import hand_off_accepted_quote
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.sla.speed_to_lead import get_speed_to_lead_settings
from app.services.telephony.text_provider import provider_for_conversation

logger = structlog.get_logger()

# Pending responses waiting for debounce
_pending_responses: dict[str, asyncio.Task[None]] = {}

_opt_out_manager = OptOutManager()


async def process_inbound_with_ai(  # noqa: PLR0911
    conversation_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
    response_started_at: float | None = None,
) -> None:
    """Process inbound message and generate AI response.

    Includes AI-powered opt-out detection that runs during the debounce delay,
    distinguishing between genuine opt-outs and false positives like
    "I think you should quit" (insult) vs "quit texting me" (opt-out).

    Args:
        conversation_id: The conversation ID
        workspace_id: Workspace ID
        db: Database session
        response_started_at: Monotonic timestamp for when the latest inbound text arrived.
    """
    log = logger.bind(conversation_id=str(conversation_id))
    if response_started_at is None:
        response_started_at = time.monotonic()
    log.info("processing_inbound_with_ai")

    # Get the tenant-bound conversation with its assigned agent.
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
        )
    )
    conversation = result.scalar_one_or_none()

    if not conversation:
        log.error("conversation_not_found")
        return
    if (
        getattr(conversation, "source_provider", None) == "quo"
        or not conversation.ai_enabled
        or conversation.ai_paused
    ):
        log.info("ai_disabled_for_conversation")
        return

    if not conversation.assigned_agent_id:
        log.info("no_agent_assigned")
        return

    # Fail closed if a stale/corrupt assignment points outside this workspace.
    agent_result = await db.execute(
        select(Agent).where(
            Agent.id == conversation.assigned_agent_id,
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
            Agent.channel_mode.in_(("text", "both")),
        )
    )
    agent = agent_result.scalar_one_or_none()

    if not agent or not agent.is_active:
        log.info("agent_not_active")
        return

    # Resolve the workspace's own OpenAI credential (workspace integration first,
    # then global env fallback), matching the voice path. Using the global token
    # here would ignore a tenant's configured key and misattribute their usage.
    # Resolve the full context (not just the bearer token) so OAuth-backed
    # workspaces get the required OAuth headers on every chat call.
    try:
        credential = await resolve_openai_credentials(db, workspace_id)
    except OpenAICredentialError:
        # A missing/expired credential means this lead gets silence. Make it
        # loud: metric for alerting + operator notification so a human can jump
        # in, instead of the reply vanishing with only a debug log.
        observe_ai_text_response_failure(workspace_id, "no_credential")
        log.error(
            "ai_text_response_failed",
            reason="no_credential",
            workspace_id=str(workspace_id),
            contact_id=conversation.contact_id,
        )
        await _notify_ai_went_dark(
            db,
            conversation=conversation,
            reason="no_credential",
            log=log,
        )
        return
    openai_key = credential.bearer_token

    # === AI-POWERED OPT-OUT DETECTION ===
    # Get last inbound message to check for opt-out intent
    last_msg_result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == "inbound",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    last_inbound = last_msg_result.scalar_one_or_none()

    if last_inbound and has_potential_opt_out_keywords(last_inbound.body):
        log.info("potential_opt_out_detected", message_id=str(last_inbound.id))

        # Get conversation context for better classification
        messages_context = await build_message_context(conversation, db, max_messages=5)

        # Run AI classifier to verify intent
        is_genuine_opt_out = await classify_opt_out_intent(
            message=last_inbound.body,
            conversation_context=messages_context,
            openai_api_key=openai_key,
            credential=credential,
        )

        if is_genuine_opt_out:
            # Confirmed opt-out. Disabling AI on this one thread is not enough:
            # without a global opt-out record, campaigns/drips and the iMessage
            # relay (which has no carrier STOP) can keep texting this lead. Record
            # it on the workspace-wide opt-out list so every outbound path
            # suppresses, and stamp contact consent for the compliance record.
            await _record_ai_confirmed_opt_out(
                db=db,
                conversation=conversation,
                inbound_message=last_inbound,
                log=log,
            )
            return
        else:
            log.info(
                "opt_out_rejected_by_ai",
                message_id=str(last_inbound.id),
            )
            # Not a genuine opt-out - proceed with normal response

    # === QUOTE ACCEPTANCE INTERCEPT ===
    # Runs before generation because the agent cannot be trusted to handle this
    # in-prompt: its booking instructions treat any agreement as buying intent,
    # so a "yes" to a proposal came back as two discovery-call slots for work the
    # customer had already bought. Accepting a quote hands off to a human instead.
    if last_inbound and await _handle_quote_acceptance(
        db=db,
        conversation=conversation,
        agent=agent,
        inbound_message=last_inbound,
        credential=credential,
        log=log,
    ):
        return

    # Generate response
    response_text = await generate_text_response(
        agent=agent,
        conversation=conversation,
        db=db,
        openai_api_key=openai_key,
        credential=credential,
    )

    if not response_text:
        # Generation returned nothing (LLM error/timeout/empty). The lead is
        # left on read — surface it for alerting and pull in an operator.
        observe_ai_text_response_failure(workspace_id, "generation_failed")
        log.error(
            "ai_text_response_failed",
            reason="generation_failed",
            workspace_id=str(workspace_id),
            contact_id=conversation.contact_id,
        )
        await _notify_ai_went_dark(
            db,
            conversation=conversation,
            reason="generation_failed",
            log=log,
        )
        return

    response_delay_ms = calculate_text_response_delay_ms(
        response_text=response_text,
        minimum_delay_ms=agent.text_response_delay_ms,
    )
    elapsed_ms = round((time.monotonic() - response_started_at) * 1000)
    send_wait_ms = max(0, response_delay_ms - elapsed_ms)

    # The human-like delay must never push the FIRST reply to a new lead past the
    # workspace speed-to-lead SLA — the response time we advertise and measure.
    # Ongoing conversation keeps its full human-like pacing (cap is None once a
    # first response has been recorded).
    sla_cap_ms = await _first_response_sla_cap_ms(db, conversation)
    if sla_cap_ms is not None and sla_cap_ms < send_wait_ms:
        log.info(
            "speed_to_lead_delay_capped",
            from_wait_ms=send_wait_ms,
            to_wait_ms=sla_cap_ms,
        )
        send_wait_ms = sla_cap_ms

    agent_id = agent.id

    await _send_ai_text_response_after_delay(
        db=db,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        agent_id=agent_id,
        response_text=response_text,
        target_delay_ms=response_delay_ms,
        elapsed_ms=elapsed_ms,
        wait_ms=send_wait_ms,
        log=log,
    )


async def _handle_quote_acceptance(
    *,
    db: AsyncSession,
    conversation: Conversation,
    agent: Agent,
    inbound_message: Message,
    credential: Any,
    log: Any,
) -> bool:
    """Park the conversation on a human when the customer accepts their quote.

    Returns ``True`` when the acceptance was handled and the caller must not
    generate a reply.

    Ordered cheapest-check-first so the overwhelming majority of inbound texts
    cost nothing: keyword pre-filter, then a quote lookup, and only then the
    classifier. Any failure returns ``False`` and falls through to the normal
    reply — this guard must never be the reason a lead is left on read.
    """
    try:
        if not has_potential_acceptance_keywords(inbound_message.body or ""):
            return False

        quote = await find_outstanding_quote(
            db,
            workspace_id=conversation.workspace_id,
            contact_id=conversation.contact_id,
        )
        if quote is None:
            return False

        context = await build_message_context(conversation, db, max_messages=6)
        accepted = await classify_quote_acceptance(
            inbound_message.body or "",
            context,
            credential=credential,
        )
        if not accepted:
            log.info("quote_acceptance_rejected_by_ai", quote_id=str(quote.id))
            return False

        contact = await db.get(Contact, conversation.contact_id)
        if contact is None:
            log.warning("quote_acceptance_contact_missing")
            return False

        log.info("quote_acceptance_detected", quote_id=str(quote.id))
        await hand_off_accepted_quote(
            db,
            conversation=conversation,
            contact=contact,
            quote=quote,
            agent_id=agent.id,
            log=log,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - never block the nurture path
        log.warning("quote_acceptance_intercept_failed", error_type=type(exc).__name__)
        return False


_AI_DARK_MESSAGES: dict[str, str] = {
    "no_credential": (
        "AI couldn't reply to a new lead — OpenAI isn't connected for this "
        "workspace. Connect it in Settings, then follow up manually."
    ),
    "generation_failed": (
        "AI couldn't reply to a new lead and the conversation is waiting on a "
        "human. Jump in so the lead isn't left on read."
    ),
    "send_failed": (
        "AI wrote a reply to a new lead but it couldn't be delivered. Check the "
        "conversation and follow up so the lead isn't left on read."
    ),
}


async def _notify_ai_went_dark(
    db: AsyncSession,
    *,
    conversation: Conversation,
    reason: str,
    log: Any,
) -> None:
    """Alert workspace operators that AI could not reply to an inbound lead.

    Best-effort: a notification failure must never break (or re-raise into) the
    already-failing nurture path. Deduped per (conversation, reason) so retries
    and repeat inbounds don't spam operators.
    """
    body = _AI_DARK_MESSAGES.get(reason, _AI_DARK_MESSAGES["generation_failed"])
    try:
        await notify_workspace_event(
            db,
            workspace_id=conversation.workspace_id,
            notification_type="message",
            title="AI needs a hand",
            body=body,
            data={
                "type": "ai_response_failed",
                "reason": reason,
                "conversationId": str(conversation.id),
                "screen": f"/(tabs)/messages/{conversation.id}",
            },
            channel_id="messages",
            email_subject="AI couldn't reply to a lead",
            email_heading="AI needs a hand",
            email_intro=body,
            dedupe_key=f"ai_dark:{conversation.id}:{reason}",
        )
    except Exception as exc:  # noqa: BLE001 - notification must not break nurture
        log.warning(
            "ai_dark_notification_failed",
            error_type=type(exc).__name__,
            reason=reason,
        )


# Fraction of the SLA budget the first reply is allowed to consume, leaving
# headroom for send + carrier latency so "within SLA" stays true end to end.
_SPEED_TO_LEAD_DELAY_BUDGET = 0.8


async def _first_response_sla_cap_ms(
    db: AsyncSession,
    conversation: Conversation,
) -> int | None:
    """Max additional wait (ms) for the first reply so it stays within the SLA.

    Returns ``None`` when no cap applies: this is not the first response to an
    inbound-led conversation, or the workspace has speed-to-lead disabled. When a
    cap applies it is the remaining SLA budget from now (never negative), so a
    reply that is already late is sent immediately instead of waiting further.
    """
    # Only the first response to a lead who reached out first is SLA-measured.
    if conversation.first_inbound_at is None or conversation.first_response_at is not None:
        return None

    workspace = await db.get(Workspace, conversation.workspace_id)
    if workspace is None:
        return None
    config = get_speed_to_lead_settings(workspace)
    if not config.enabled:
        return None

    anchor = conversation.first_inbound_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    budget_ms = int(config.sla_seconds * 1000 * _SPEED_TO_LEAD_DELAY_BUDGET)
    elapsed_ms = int((datetime.now(UTC) - anchor).total_seconds() * 1000)
    return max(0, budget_ms - elapsed_ms)


async def _record_ai_confirmed_opt_out(
    *,
    db: AsyncSession,
    conversation: Conversation,
    inbound_message: Message,
    log: Any,
) -> None:
    """Persist a workspace-wide opt-out for an AI-confirmed STOP request.

    Disables AI on the conversation, adds the contact to the global opt-out list
    (so campaigns, drips, reminders, review requests and the iMessage relay all
    suppress future sends), and stamps the contact's SMS consent status for the
    compliance record. Idempotent: when the campaign reply handler already
    recorded the opt-out, :meth:`OptOutManager.add_opt_out` returns ``None`` and
    we still commit the AI-disable / consent changes ourselves.
    """
    conversation.ai_enabled = False

    if conversation.contact_id is not None:
        contact_result = await db.execute(
            select(Contact).where(
                Contact.id == conversation.contact_id,
                Contact.workspace_id == conversation.workspace_id,
            )
        )
        contact = contact_result.scalar_one_or_none()
        if contact is not None:
            contact.sms_consent_status = "opted_out"
            contact.sms_consent_source = "sms_reply"
            contact.sms_consent_collected_at = datetime.now(UTC)
            contact.sms_consent_notes = f"Opted out via SMS reply: {inbound_message.body[:100]}"

    # The global opt-out list is keyed on phone numbers. A Messenger thread has
    # none, so "stop" there can only silence this thread — which the
    # ``ai_enabled = False`` above already did. Recording nothing is better than
    # recording it under a PSID no SMS send would ever check.
    opt_out = None
    if conversation.contact_phone:
        opt_out = await _opt_out_manager.add_opt_out(
            workspace_id=conversation.workspace_id,
            phone_number=conversation.contact_phone,
            db=db,
            keyword=inbound_message.body[:50] if inbound_message.body else None,
            source_message_id=inbound_message.id,
        )
    if opt_out is None:
        # Already on the opt-out list; add_opt_out skipped its own commit, so
        # persist the ai_enabled / consent changes here.
        await db.commit()

    log.info(
        "opt_out_confirmed_by_ai",
        message_id=str(inbound_message.id),
        global_opt_out_recorded=opt_out is not None,
    )


async def _send_ai_text_response_after_delay(
    *,
    db: AsyncSession,
    conversation_id: uuid.UUID,
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    response_text: str,
    target_delay_ms: int,
    elapsed_ms: int,
    wait_ms: int,
    log: Any,
) -> None:
    """Wait the remaining human-like delay, re-check state, then send."""
    from app.services.telephony.text_provider import (
        get_text_message_provider,
        outbound_addresses,
    )

    if wait_ms > 0:
        log.info(
            "ai_response_waiting_to_send",
            response_length=len(response_text),
            target_delay_ms=target_delay_ms,
            elapsed_ms=elapsed_ms,
            wait_ms=wait_ms,
        )
        await db.rollback()
        await asyncio.sleep(wait_ms / 1000.0)

    current_conversation = await _load_sendable_conversation(
        db=db,
        conversation_id=conversation_id,
        agent_id=agent_id,
        log=log,
    )
    if current_conversation is None:
        return

    provider_name = provider_for_conversation(current_conversation)
    to_address, from_address = outbound_addresses(current_conversation)
    sms_service = get_text_message_provider(provider_name)
    sent_message: Message | None = None
    try:
        sent_message = await sms_service.send_message(
            to_number=to_address,
            from_number=from_address,
            body=response_text,
            db=db,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        log.info(
            "ai_response_sent",
            message_id=str(sent_message.id),
            response_length=len(response_text),
            target_delay_ms=target_delay_ms,
            wait_ms=wait_ms,
        )
    except Exception as e:
        # Reply was generated but the provider rejected the send. Count it and
        # notify so the lead isn't silently dropped after passing generation.
        observe_ai_text_response_failure(workspace_id, "send_failed")
        log.error(
            "ai_text_response_failed",
            reason="send_failed",
            error_type=type(e).__name__,
        )
        await _notify_ai_went_dark(
            db,
            conversation=current_conversation,
            reason="send_failed",
            log=log,
        )
    finally:
        await sms_service.close()

    if sent_message is None:
        return

    try:
        from app.services.ai.contact_ai_memory_service import (
            refresh_contact_ai_memory_from_sms,
        )

        updated = await refresh_contact_ai_memory_from_sms(
            db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            completed_message_id=sent_message.id,
        )
        if updated:
            await db.commit()
    except Exception as exc:  # noqa: BLE001 - memory must never break a sent reply
        await db.rollback()
        log.warning(
            "contact_ai_memory_sms_refresh_failed",
            message_id=str(sent_message.id),
            error_type=type(exc).__name__,
        )


async def _load_sendable_conversation(
    *,
    db: AsyncSession,
    conversation_id: uuid.UUID,
    agent_id: uuid.UUID,
    log: Any,
) -> Conversation | None:
    """Return the conversation if it should still receive the delayed AI reply."""
    current_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    current_conversation = current_result.scalar_one_or_none()
    if not current_conversation:
        log.info("conversation_removed_before_ai_response_send")
        return None
    if (
        current_conversation.source_provider == "quo"
        or not current_conversation.ai_enabled
        or current_conversation.ai_paused
        or current_conversation.assigned_agent_id != agent_id
    ):
        log.info("ai_response_skipped_after_delay")
        return None
    # Meta's reply window can close during the human-like send delay. Sending
    # anyway earns a hard error 10 that no retry fixes, logged as a generic send
    # failure — indistinguishable from the AI ghosting the lead.
    window_expires_at = current_conversation.messenger_window_expires_at
    if window_expires_at is not None and window_expires_at <= datetime.now(UTC):
        log.info("ai_response_skipped_messaging_window_closed")
        return None
    return current_conversation


async def schedule_ai_response(
    conversation_id: uuid.UUID,
    workspace_id: uuid.UUID,
    delay_ms: int = 3000,
) -> None:
    """Schedule an AI response after a delay (for message batching).

    If called multiple times for the same conversation within the delay,
    the timer resets to wait for more messages.

    Args:
        conversation_id: The conversation ID
        workspace_id: Workspace ID
        delay_ms: Delay in milliseconds before responding
    """
    from app.db.session import AsyncSessionLocal

    key = str(conversation_id)
    log = logger.bind(conversation_id=key, delay_ms=delay_ms)

    # Cancel any existing pending response
    if key in _pending_responses:
        _pending_responses[key].cancel()
        log.debug("cancelled_pending_response")

    scheduled_at = time.monotonic()

    async def delayed_response() -> None:
        """Execute response after delay."""
        log.info("delayed_response_started")
        try:
            await asyncio.sleep(delay_ms / 1000.0)

            # Process in new database session
            async with AsyncSessionLocal() as db:
                await process_inbound_with_ai(
                    conversation_id,
                    workspace_id,
                    db,
                    response_started_at=scheduled_at,
                )

        except asyncio.CancelledError:
            log.info("response_cancelled")
        except Exception:
            log.exception("delayed_response_error")
        finally:
            if _pending_responses.get(key) is task:
                _pending_responses.pop(key, None)

    # Create and store task
    task = asyncio.create_task(delayed_response())
    _pending_responses[key] = task
    log.info("ai_response_scheduled")
