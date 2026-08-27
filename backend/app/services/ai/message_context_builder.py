"""Bounded conversation and durable contact context for AI responses.

Current-thread messages remain normal chat turns. Typed CRM state, durable memory, and
selected cross-channel history are loaded separately so historical text can never masquerade
as a live quote, invoice, appointment, or qualification field.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import CampaignContact
from app.models.conversation import Conversation, Message
from app.models.workspace import Workspace
from app.services.ai.contact_ai_memory_service import (
    ContactAIMemoryService,
    render_contact_ai_memory_context,
)
from app.services.ai.contact_context_snapshot import (
    ContactContextSnapshotService,
    ContactTimelineItem,
)
from app.services.ai.context_observability import ContextChunk, collect_context_provenance

logger = structlog.get_logger()

# Default timezone fallback
DEFAULT_TIMEZONE = "America/New_York"
MAX_LATEST_INBOUND_CHARS: Final = 2_000
MAX_LIVE_CONTACT_CONTEXT_CHARS: Final = 10_500
MAX_DURABLE_MEMORY_CONTEXT_CHARS: Final = 3_500
MAX_CONTACT_PROMPT_CONTEXT_CHARS: Final = 14_500
MAX_CROSS_CHANNEL_CANDIDATES: Final = 30
MAX_RELEVANT_CROSS_CHANNEL_ITEMS: Final = 10
_CONTEXT_TOKEN_PATTERN: Final = re.compile(r"[a-z0-9]+")
_CONTEXT_STOP_WORDS: Final = frozenset(
    {
        "a",
        "about",
        "and",
        "are",
        "can",
        "for",
        "from",
        "have",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "we",
        "what",
        "when",
        "with",
        "you",
    }
)


async def get_workspace_timezone(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """Get timezone from workspace settings.

    Args:
        workspace_id: The workspace ID
        db: Database session

    Returns:
        Timezone string (e.g., "America/New_York")
    """
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace and workspace.settings:
        tz = workspace.settings.get("timezone")
        if isinstance(tz, str):
            return tz
    return DEFAULT_TIMEZONE


def extract_email_from_messages(
    messages: list[dict[str, str]],
    *,
    fallback_email: str | None = None,
) -> str | None:
    """Return the latest valid thread email, then a validated CRM fallback."""
    email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    for message in reversed(messages):
        match = re.search(email_pattern, message.get("content", ""))
        if match:
            return match.group(0)
    fallback_match = re.search(email_pattern, fallback_email or "")
    return fallback_match.group(0) if fallback_match else None


async def build_message_context(
    conversation: Conversation,
    db: AsyncSession,
    max_messages: int = 20,
) -> list[dict[str, str]]:
    """Build message history for LLM context.

    Args:
        conversation: The conversation
        db: Database session
        max_messages: Maximum messages to include

    Returns:
        List of message dicts in OpenAI format
    """
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    )
    messages = list(reversed(result.scalars().all()))

    context: list[dict[str, str]] = []
    for msg in messages:
        role = "user" if msg.direction == "inbound" else "assistant"
        context.append({"role": role, "content": msg.body})

    return context


@dataclass(frozen=True, slots=True)
class ContactGenerationContext:
    """SMS-only model context kept separate from ordinary chat messages."""

    prompt_block: str
    latest_inbound_intent: str
    observation_chunks: tuple[ContextChunk, ...] = ()


def get_latest_inbound_intent(messages: list[dict[str, str]]) -> str:
    """Return the latest customer turn, bounded for retrieval and intent checks."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "").strip()
        if content:
            return content[:MAX_LATEST_INBOUND_CHARS]
    return ""


async def build_contact_generation_context(
    conversation: Conversation,
    db: AsyncSession,
    *,
    messages: list[dict[str, str]],
) -> ContactGenerationContext:
    """Load live CRM state first, then bounded durable memory for one SMS turn.

    The snapshot query is scoped by both ``workspace_id`` and ``contact_id``. Its timeline
    spans the contact's SMS, voice, and voicemail conversations; only the entries most
    relevant to the latest inbound turn are retained for the prompt.
    """
    latest_inbound_intent = get_latest_inbound_intent(messages)
    contact_id = conversation.contact_id
    if contact_id is None:
        return ContactGenerationContext("", latest_inbound_intent)

    sections: list[str] = []
    observation_chunks: list[ContextChunk] = []
    try:
        snapshot = await ContactContextSnapshotService(
            db,
            timeline_limit=MAX_CROSS_CHANNEL_CANDIDATES,
        ).get_snapshot(
            workspace_id=conversation.workspace_id,
            contact_id=contact_id,
        )
        if snapshot is not None:
            selected_timeline = select_relevant_cross_channel_history(
                snapshot.recent_timeline,
                latest_inbound_intent=latest_inbound_intent,
            )
            snapshot = snapshot.model_copy(update={"recent_timeline": selected_timeline})
            rendered_snapshot = snapshot.render(max_chars=MAX_LIVE_CONTACT_CONTEXT_CHARS)
            sections.append(rendered_snapshot)
            provenance = collect_context_provenance(snapshot)
            observation_chunks.append(
                ContextChunk(
                    source_type="contact_snapshot",
                    source_ids=provenance.source_ids or (f"contact:{contact_id}",),
                    text=rendered_snapshot,
                    observed_at=provenance.earliest_observed_at or snapshot.observed_at,
                    record_updated_at=(
                        provenance.earliest_record_updated_at or snapshot.observed_at
                    ),
                )
            )
    except Exception:
        logger.warning(
            "sms_contact_snapshot_load_failed",
            workspace_id=str(conversation.workspace_id),
            contact_id=contact_id,
            exc_info=True,
        )

    try:
        memory_context = await ContactAIMemoryService(db).get_context(
            workspace_id=conversation.workspace_id,
            contact_id=contact_id,
        )
        rendered_memory = render_contact_ai_memory_context(
            memory_context,
            max_chars=MAX_DURABLE_MEMORY_CONTEXT_CHARS,
        )
        if rendered_memory and memory_context is not None:
            sections.append(rendered_memory)
            memory_source_ids = {
                source_id
                for source_id in (
                    memory_context.summary_source_event_id,
                    *(
                        fact.provenance_event_id or str(fact.fact_id or "")
                        for fact in memory_context.facts
                    ),
                )
                if source_id
            }
            observed_times = [
                observed_at
                for observed_at in (
                    memory_context.summary_observed_at,
                    *(fact.observed_at for fact in memory_context.facts),
                )
                if observed_at is not None
            ]
            observation_chunks.append(
                ContextChunk(
                    source_type="durable_memory",
                    source_ids=tuple(sorted(memory_source_ids)) or (f"contact:{contact_id}",),
                    text=rendered_memory,
                    observed_at=min(observed_times, default=None),
                    record_updated_at=min(observed_times, default=None),
                )
            )
    except Exception:
        logger.warning(
            "sms_contact_memory_load_failed",
            workspace_id=str(conversation.workspace_id),
            contact_id=contact_id,
            exc_info=True,
        )

    prompt_block = "\n\n".join(sections)[:MAX_CONTACT_PROMPT_CONTEXT_CHARS]
    return ContactGenerationContext(
        prompt_block,
        latest_inbound_intent,
        tuple(observation_chunks),
    )


def select_relevant_cross_channel_history(
    timeline: tuple[ContactTimelineItem, ...],
    *,
    latest_inbound_intent: str,
    limit: int = MAX_RELEVANT_CROSS_CHANNEL_ITEMS,
) -> tuple[ContactTimelineItem, ...]:
    """Choose bounded intent-relevant history while retaining another channel."""
    if limit <= 0 or not timeline:
        return ()
    if len(timeline) <= limit:
        return timeline

    query_tokens = _context_tokens(latest_inbound_intent)
    mentions_call = bool(query_tokens.intersection({"call", "called", "discussed", "spoke"}))

    ranked = sorted(
        enumerate(timeline),
        key=lambda pair: (
            _timeline_relevance(pair[1], query_tokens, mentions_call=mentions_call),
            pair[0],
        ),
        reverse=True,
    )
    selected = [item for _, item in ranked[:limit]]

    cross_channel_items = [item for item in timeline if item.channel != "sms"]
    if cross_channel_items and not any(item.channel != "sms" for item in selected):
        selected[-1] = max(
            cross_channel_items,
            key=lambda item: (
                _timeline_relevance(item, query_tokens, mentions_call=mentions_call),
                item.occurred_at,
            ),
        )

    selected_by_id = {item.message_id: item for item in selected}
    return tuple(
        sorted(
            selected_by_id.values(),
            key=lambda item: (item.occurred_at, str(item.message_id)),
        )
    )


def _timeline_relevance(
    item: ContactTimelineItem,
    query_tokens: frozenset[str],
    *,
    mentions_call: bool,
) -> int:
    overlap = len(query_tokens.intersection(_context_tokens(item.content)))
    cross_channel_bonus = 1 if item.channel != "sms" else 0
    call_bonus = 3 if mentions_call and item.channel in {"voice", "voicemail"} else 0
    return overlap * 4 + cross_channel_bonus + call_bonus


def _context_tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _CONTEXT_TOKEN_PATTERN.findall(text.casefold())
        if len(token) > 1 and token not in _CONTEXT_STOP_WORDS
    )


async def get_offer_context(
    conversation: Conversation,
    db: AsyncSession,
) -> str | None:
    """Get offer context for a conversation from its campaign.

    Args:
        conversation: The conversation
        db: Database session

    Returns:
        Formatted offer context string, or None if no offer
    """
    from sqlalchemy.orm import selectinload

    from app.models.campaign import Campaign

    # Get campaign contact for this conversation
    result = await db.execute(
        select(CampaignContact)
        .options(selectinload(CampaignContact.campaign).selectinload(Campaign.offer))
        .where(CampaignContact.conversation_id == conversation.id)
        .order_by(CampaignContact.created_at.desc())
        .limit(1)
    )
    campaign_contact = result.scalar_one_or_none()

    if not campaign_contact or not campaign_contact.campaign or not campaign_contact.campaign.offer:
        return None

    offer = campaign_contact.campaign.offer

    # Format discount text
    discount_text = ""
    if offer.discount_type == "percentage":
        discount_text = f"{offer.discount_value}% off"
    elif offer.discount_type == "fixed":
        discount_text = f"${offer.discount_value} off"
    elif offer.discount_type == "free_service":
        discount_text = "Free service"

    # Build context string
    context_parts = [f"The customer was offered: {offer.name}"]

    if discount_text:
        context_parts.append(f"Discount: {discount_text}")

    if offer.description:
        context_parts.append(f"Description: {offer.description}")

    if offer.terms:
        context_parts.append(f"Terms: {offer.terms}")

    context_parts.append("Refer to this offer in your responses if relevant to the conversation.")

    return "\n".join(context_parts)
