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
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.models.conversation import Conversation, Message
from app.services.ai.message_context_builder import build_message_context
from app.services.ai.opt_out_detector import (
    classify_opt_out_intent,
    has_potential_opt_out_keywords,
)
from app.services.ai.text_response_generator import generate_text_response

logger = structlog.get_logger()

# Pending responses waiting for debounce
_pending_responses: dict[str, asyncio.Task[None]] = {}


async def process_inbound_with_ai(  # noqa: PLR0911
    conversation_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """Process inbound message and generate AI response.

    Includes AI-powered opt-out detection that runs during the debounce delay,
    distinguishing between genuine opt-outs and false positives like
    "I think you should quit" (insult) vs "quit texting me" (opt-out).

    Args:
        conversation_id: The conversation ID
        workspace_id: Workspace ID
        db: Database session
    """
    from app.services.telephony.telnyx import TelnyxSMSService

    log = logger.bind(conversation_id=str(conversation_id))
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

    # TODO: Get OpenAI API key from workspace settings
    openai_key = settings.openai_api_key
    if not openai_key:
        log.error("no_openai_api_key")
        return

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
    )

    if not response_text:
        log.warning("no_response_generated")
        return

    # Send response via SMS
    telnyx_api_key = settings.telnyx_api_key
    if not telnyx_api_key:
        log.error("no_telnyx_api_key")
        return

    sms_service = TelnyxSMSService(telnyx_api_key)
    try:
        await sms_service.send_message(
            to_number=conversation.contact_phone,
            from_number=conversation.workspace_phone,
            body=response_text,
            db=db,
            workspace_id=workspace_id,
            agent_id=agent.id,
        )
        log.info(
            "ai_response_sent",
            response_length=len(response_text),
        )
    except Exception as e:
        log.error(
            "failed_to_send_ai_response",
            error=str(e),
            error_type=type(e).__name__,
        )
    finally:
        await sms_service.close()


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

    async def delayed_response() -> None:
        """Execute response after delay."""
        log.info("delayed_response_started")
        try:
            await asyncio.sleep(delay_ms / 1000.0)

            # Process in new database session
            async with AsyncSessionLocal() as db:
                await process_inbound_with_ai(conversation_id, workspace_id, db)

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
