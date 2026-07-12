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
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import observe_ai_text_response_failure
from app.models.agent import Agent
from app.models.conversation import Conversation, Message
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

logger = structlog.get_logger()

# Pending responses waiting for debounce
_pending_responses: dict[str, asyncio.Task[None]] = {}


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

    # Get conversation with agent
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = result.scalar_one_or_none()

    if not conversation:
        log.error("conversation_not_found")
        return

    if not conversation.ai_enabled or conversation.ai_paused:
        log.info("ai_disabled_for_conversation")
        return

    if not conversation.assigned_agent_id:
        log.info("no_agent_assigned")
        return

    # Get agent
    agent_result = await db.execute(select(Agent).where(Agent.id == conversation.assigned_agent_id))
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
            contact_phone=conversation.contact_phone,
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
        log.info("potential_opt_out_detected", message_preview=last_inbound.body[:50])

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
            # Confirmed opt-out - disable AI and don't respond
            conversation.ai_enabled = False
            await db.commit()
            log.info(
                "opt_out_confirmed_by_ai",
                message=last_inbound.body[:100],
            )
            return
        else:
            log.info(
                "opt_out_rejected_by_ai",
                message=last_inbound.body[:100],
            )
            # Not a genuine opt-out - proceed with normal response

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
            contact_phone=conversation.contact_phone,
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
        log.warning("ai_dark_notification_failed", error=str(exc), reason=reason)


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
    from app.services.telephony.text_provider import get_text_message_provider

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

    provider_name = _preferred_provider_for_conversation(current_conversation)
    sms_service = get_text_message_provider(provider_name)
    try:
        await sms_service.send_message(
            to_number=current_conversation.contact_phone,
            from_number=current_conversation.workspace_phone,
            body=response_text,
            db=db,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        log.info(
            "ai_response_sent",
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
            error=str(e),
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
        not current_conversation.ai_enabled
        or current_conversation.ai_paused
        or current_conversation.assigned_agent_id != agent_id
    ):
        log.info("ai_response_skipped_after_delay")
        return None
    return current_conversation


def _preferred_provider_for_conversation(conversation: Conversation) -> str | None:
    """Keep AI replies on the same text transport as the inbound thread."""
    if conversation.channel == "imessage":
        return "mac_relay"
    return None


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
            _pending_responses.pop(key, None)

    # Create and store task
    task = asyncio.create_task(delayed_response())
    _pending_responses[key] = task
    log.info("ai_response_scheduled")
