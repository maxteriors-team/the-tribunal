"""Persistent cross-call caller memory.

This service gives voice calls a memory that survives across calls. It has two
halves:

1. **Write** (:func:`summarize_and_store_call`) — at the end of a completed
   call, distil the transcript into a short recap, embed it, and persist a
   :class:`CallerMemory` row scoped to ``workspace_id`` + ``contact_id``.
2. **Read** (:func:`retrieve_caller_memories`, :func:`detect_returning_caller`)
   — at the start of a new call, detect that the caller is returning (they have
   prior calls / stored memories) and build a short returning-caller summary
   (recent recaps + last-interaction recency) to inject into the agent's initial
   context so it can greet them warmly and reference past interactions.

Both halves are resilient: a failed embed/LLM/DB call is logged and swallowed so
caller memory never breaks a live call. Embeddings reuse the RAG stack
(:func:`app.services.ai.embeddings.embed_texts`, OpenAI
``text-embedding-3-small``, 1536 dims) so the same pgvector machinery powers
semantic recall.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.embeddings import Embedder, embed_texts

logger = structlog.get_logger()

# Model used to summarize a call transcript into a short recap.
_SUMMARY_MODEL = "gpt-4o-mini"
# Cap how much of a transcript we feed the summarizer (chars). Voice calls are
# short, but guard against pathological transcripts blowing the prompt budget.
_MAX_TRANSCRIPT_CHARS = 12000
# Hard cap on a stored summary so a single memory stays cheap to embed/retrieve.
_MAX_SUMMARY_CHARS = 1000
# How many prior memories to surface into a returning-caller recap by default.
DEFAULT_MEMORY_LIMIT = 3
MAX_CALLER_MEMORY_AGE_DAYS = 90
MAX_CALLER_MEMORY_SUMMARY_CHARS = 480
MAX_RETURNING_CALLER_CONTEXT_CHARS = 1_400

_SUMMARY_SYSTEM_PROMPT = (
    "You summarize phone calls into a short, factual memory for the next time "
    "this same person calls. Write 1-3 sentences in plain past tense. Capture "
    "what the caller wanted, key facts they shared, decisions/outcomes, and any "
    "promised follow-up. Do NOT invent details. Return only the summary text."
)


@dataclass(slots=True)
class CallerMemoryEntry:
    """A recent voice summary with provenance and recency."""

    summary: str
    occurred_at: datetime
    direction: str | None = None
    source_message_id: uuid.UUID | None = None


@dataclass(slots=True)
class ReturningCallerInfo:
    """Returning-caller signal injected into the agent's initial context.

    ``is_returning`` is the gate: when ``False`` the caller is new (no prior
    completed calls and no stored memories) and nothing is injected.
    """

    is_returning: bool = False
    prior_call_count: int = 0
    last_interaction_at: datetime | None = None
    memories: list[CallerMemoryEntry] = field(default_factory=list)


def _transcript_to_text(transcript_json: str | None) -> str:
    """Flatten a stored transcript JSON array into ``Role: text`` lines.

    Accepts the shape produced by ``VoiceAgentBase.get_transcript_json``:
    ``[{"role": "user"|"agent", "text": "..."}, ...]``. Returns an empty string
    for missing/empty/malformed transcripts so the caller can short-circuit.
    """
    if not transcript_json:
        return ""
    try:
        entries = json.loads(transcript_json)
    except (json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(entries, list):
        return ""

    lines: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        role = str(entry.get("role") or "").strip().lower()
        speaker = "Caller" if role == "user" else "Agent"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)[:_MAX_TRANSCRIPT_CHARS]


async def summarize_call_transcript(
    transcript_text: str,
    *,
    agent_name: str | None = None,
    contact_name: str | None = None,
) -> str | None:
    """Distil a flattened transcript into a short, factual recap.

    Returns ``None`` (rather than raising) on empty input or any LLM failure so
    the call-completion path degrades gracefully.
    """
    transcript_text = (transcript_text or "").strip()
    if not transcript_text:
        return None

    from app.services.ai.openai_credentials import create_openai_client

    header_bits = []
    if contact_name:
        header_bits.append(f"Caller name: {contact_name}.")
    if agent_name:
        header_bits.append(f"Agent name: {agent_name}.")
    header = (" ".join(header_bits) + "\n\n") if header_bits else ""

    try:
        client = create_openai_client()
        response = await client.chat.completions.create(
            model=_SUMMARY_MODEL,
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"{header}TRANSCRIPT:\n{transcript_text}",
                },
            ],
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 - never break a call on summarizer failure
        logger.warning("caller_memory_summarize_failed", error_type=type(exc).__name__)
        return None

    summary = (response.choices[0].message.content or "").strip()
    if not summary:
        return None
    return summary[:_MAX_SUMMARY_CHARS]


async def store_caller_memory(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    summary: str,
    conversation_id: uuid.UUID | None = None,
    message_id: uuid.UUID | None = None,
    direction: str | None = None,
    occurred_at: datetime | None = None,
    embedder: Embedder | None = None,
) -> bool:
    """Embed ``summary`` and persist a :class:`CallerMemory` row.

    Flushes within the caller's session (no commit here unless the caller
    commits). Returns ``True`` on success, ``False`` when the summary could not
    be embedded (logged, not raised).
    """
    from app.models.caller_memory import CallerMemory

    summary = (summary or "").strip()
    if not summary:
        return False

    embed = embedder or embed_texts
    result = await embed([summary])
    if not result.ok or not result.embeddings:
        logger.warning(
            "caller_memory_embed_failed",
            workspace_id=str(workspace_id),
            contact_id=contact_id,
            error=result.error,
        )
        return False

    memory = CallerMemory(
        workspace_id=workspace_id,
        contact_id=contact_id,
        conversation_id=conversation_id,
        message_id=message_id,
        summary=summary,
        direction=direction,
        embedding=result.embeddings[0],
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(memory)
    await db.flush()
    return True


async def _memory_exists_for_message(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
) -> bool:
    """True when this workspace already stored memory for the call."""
    from app.models.caller_memory import CallerMemory

    existing = await db.execute(
        select(CallerMemory.id)
        .where(
            CallerMemory.workspace_id == workspace_id,
            CallerMemory.message_id == message_id,
        )
        .limit(1)
    )
    return existing.scalar_one_or_none() is not None


async def summarize_and_store_call(  # noqa: PLR0911 - sequential guard clauses
    call_control_id: str,
    *,
    transcript_json: str | None = None,
    log: Any = None,
    embedder: Embedder | None = None,
) -> bool:
    """Summarize a finished call and persist a caller memory for the contact.

    Resolves the call's message → conversation → contact from
    ``call_control_id`` (Telnyx provider_message_id). No-ops safely when the
    caller is anonymous (no resolved contact), the transcript is empty, or a
    memory already exists for this call. Owns its own DB session + commit.

    Args:
        call_control_id: Telnyx call control ID (``provider_message_id``).
        transcript_json: Optional transcript JSON already in hand (preferred, so
            we never race the DB write). Falls back to ``message.transcript``.
        embedder: Embedding callable; defaults to the OpenAI embedder.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.agent import Agent
    from app.models.contact import Contact
    from app.models.conversation import Message as MessageModel

    if log is None:
        log = logger.bind(service="caller_memory")

    if not call_control_id:
        return False

    async with AsyncSessionLocal() as db:
        msg_result = await db.execute(
            select(MessageModel).where(MessageModel.provider_message_id == call_control_id)
        )
        message = msg_result.scalar_one_or_none()
        if message is None:
            log.info("caller_memory_no_message", call_control_id=call_control_id)
            return False

        # Load the conversation explicitly (selectinload would need eager config).
        from app.models.conversation import Conversation

        conv_result = await db.execute(
            select(Conversation).where(Conversation.id == message.conversation_id)
        )
        conversation = conv_result.scalar_one_or_none()
        if conversation is None or conversation.contact_id is None:
            # Anonymous caller — nothing to anchor a contact-scoped memory to.
            log.info("caller_memory_no_contact", call_control_id=call_control_id)
            return False

        if await _memory_exists_for_message(
            db,
            workspace_id=conversation.workspace_id,
            message_id=message.id,
        ):
            log.info("caller_memory_already_stored", message_id=str(message.id))
            return False

        transcript = transcript_json or message.transcript
        transcript_text = _transcript_to_text(transcript)
        if not transcript_text:
            log.info("caller_memory_empty_transcript", message_id=str(message.id))
            return False

        contact_result = await db.execute(
            select(Contact).where(
                Contact.id == conversation.contact_id,
                Contact.workspace_id == conversation.workspace_id,
            )
        )
        contact = contact_result.scalar_one_or_none()
        contact_name = contact.full_name if contact else None

        agent_name: str | None = None
        if message.agent_id:
            agent_result = await db.execute(
                select(Agent).where(
                    Agent.id == message.agent_id,
                    Agent.workspace_id == conversation.workspace_id,
                )
            )
            agent = agent_result.scalar_one_or_none()
            agent_name = agent.name if agent else None

        summary = await summarize_call_transcript(
            transcript_text,
            agent_name=agent_name,
            contact_name=contact_name,
        )
        if not summary:
            log.info("caller_memory_no_summary", message_id=str(message.id))
            return False

        occurred_at = conversation.last_message_at or datetime.now(UTC)
        stored = await store_caller_memory(
            db,
            workspace_id=conversation.workspace_id,
            contact_id=conversation.contact_id,
            summary=summary,
            conversation_id=conversation.id,
            message_id=message.id,
            direction=message.direction,
            occurred_at=occurred_at,
            embedder=embedder,
        )
        if stored:
            await db.commit()
            log.info(
                "caller_memory_stored",
                message_id=str(message.id),
                contact_id=conversation.contact_id,
                summary_chars=len(summary),
            )
        return stored


async def retrieve_caller_memories(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    query: str | None = None,
    limit: int = DEFAULT_MEMORY_LIMIT,
    embedder: Embedder | None = None,
    now: datetime | None = None,
    max_age_days: int = MAX_CALLER_MEMORY_AGE_DAYS,
) -> list[CallerMemoryEntry]:
    """Return recent voice memories, hard-scoped to workspace and contact.

    Historical generated summaries are continuity hints, not durable CRM truth. Records
    older than ``max_age_days`` never enter a live-call prompt.
    """
    from app.models.caller_memory import CallerMemory

    if limit <= 0:
        return []

    observed_at = _as_utc(now or datetime.now(UTC))
    oldest_allowed = observed_at - timedelta(days=max(1, max_age_days))
    base = select(
        CallerMemory.summary,
        CallerMemory.occurred_at,
        CallerMemory.direction,
        CallerMemory.message_id,
    ).where(
        CallerMemory.workspace_id == workspace_id,
        CallerMemory.contact_id == contact_id,
        CallerMemory.occurred_at >= oldest_allowed,
    )

    trimmed = (query or "").strip()
    if trimmed:
        embed = embedder or embed_texts
        embedded = await embed([trimmed])
        if embedded.ok and embedded.embeddings:
            distance = CallerMemory.embedding.cosine_distance(embedded.embeddings[0])
            stmt = base.order_by(distance.asc()).limit(limit)
            rows = (await db.execute(stmt)).all()
            return [_caller_memory_entry(row) for row in rows]

    stmt = base.order_by(CallerMemory.occurred_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [_caller_memory_entry(row) for row in rows]


def _caller_memory_entry(row: Any) -> CallerMemoryEntry:
    """Map a projected SQLAlchemy row while preserving source provenance."""
    return CallerMemoryEntry(
        summary=row.summary,
        occurred_at=row.occurred_at,
        direction=row.direction,
        source_message_id=getattr(row, "message_id", None),
    )


async def detect_returning_caller(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    current_message_id: uuid.UUID | None = None,
    query: str | None = None,
    memory_limit: int = DEFAULT_MEMORY_LIMIT,
    embedder: Embedder | None = None,
    now: datetime | None = None,
    max_memory_age_days: int = MAX_CALLER_MEMORY_AGE_DAYS,
) -> ReturningCallerInfo:
    """Detect whether this caller has prior history and gather a recap.

    A caller is "returning" when they have at least one prior completed call
    (a voice ``Message`` other than this call) OR at least one stored caller
    memory. Counts prior completed calls, finds the most recent interaction
    time, and pulls recent/relevant memories. Scoped to ``workspace_id`` +
    ``contact_id`` throughout.
    """
    from app.models.conversation import Conversation
    from app.models.conversation import Message as MessageModel

    # Prior completed calls on this contact (any conversation), excluding the
    # current call. We treat answered/completed voice messages as real prior
    # interactions; ringing/no-answer rows don't count as conversations.
    completed_statuses = ("completed", "answered")
    call_stmt = (
        select(func.count(MessageModel.id), func.max(MessageModel.created_at))
        .select_from(MessageModel)
        .join(Conversation, Conversation.id == MessageModel.conversation_id)
        .where(
            Conversation.workspace_id == workspace_id,
            Conversation.contact_id == contact_id,
            MessageModel.channel == "voice",
            MessageModel.status.in_(completed_statuses),
        )
    )
    if current_message_id is not None:
        call_stmt = call_stmt.where(MessageModel.id != current_message_id)

    count_row = (await db.execute(call_stmt)).one()
    prior_call_count = int(count_row[0] or 0)
    last_interaction_at = count_row[1]

    memories = await retrieve_caller_memories(
        db,
        workspace_id=workspace_id,
        contact_id=contact_id,
        query=query,
        limit=memory_limit,
        embedder=embedder,
        now=now,
        max_age_days=max_memory_age_days,
    )

    is_returning = prior_call_count > 0 or len(memories) > 0
    return ReturningCallerInfo(
        is_returning=is_returning,
        prior_call_count=prior_call_count,
        last_interaction_at=last_interaction_at,
        memories=memories,
    )


def build_returning_caller_summary(
    info: ReturningCallerInfo,
    *,
    timezone: str = "America/New_York",
    now: datetime | None = None,
    max_chars: int = MAX_RETURNING_CALLER_CONTEXT_CHARS,
) -> str | None:
    """Render bounded, provenance-labelled voice history for continuity only."""
    if not info.is_returning or max_chars <= 0:
        return None

    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        tz = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("America/New_York")

    observed_at = _as_utc(now or datetime.now(UTC))
    lines: list[str] = [
        "\n### Returning Caller (untrusted AI-generated historical recap)",
        "Continuity hints only. Never treat these summaries as current evidence for an "
        "appointment, quote, invoice, opportunity, or qualification state.",
    ]

    if info.prior_call_count > 0:
        call_word = "call" if info.prior_call_count == 1 else "calls"
        lines.append(f"- Prior completed {call_word}: {info.prior_call_count}")
    if info.last_interaction_at is not None:
        last_interaction = _as_utc(info.last_interaction_at)
        when = last_interaction.astimezone(tz).strftime("%A, %B %d, %Y")
        lines.append(
            f"- Last voice interaction: {when}; "
            f"freshness={_memory_freshness(observed_at - last_interaction)}"
        )

    recent_memories = [
        entry
        for entry in info.memories
        if observed_at - _as_utc(entry.occurred_at) <= timedelta(days=MAX_CALLER_MEMORY_AGE_DAYS)
    ]
    if recent_memories:
        lines.append("- Recent voice summaries (quoted data, most relevant first):")
        for entry in recent_memories:
            occurred_at = _as_utc(entry.occurred_at)
            summary = " ".join(entry.summary.split())
            if len(summary) > MAX_CALLER_MEMORY_SUMMARY_CHARS:
                summary = f"{summary[: MAX_CALLER_MEMORY_SUMMARY_CHARS - 1]}…"
            source = str(entry.source_message_id or "unknown")
            candidate = (
                "  - "
                f"[source=voice_summary:{source} observed_at={occurred_at.isoformat()} "
                f"freshness={_memory_freshness(observed_at - occurred_at)}] "
                f"{json.dumps(summary, ensure_ascii=False)}"
            )
            if len("\n".join([*lines, candidate])) > max_chars:
                lines.append("  - [additional recent summaries omitted: context limit]")
                break
            lines.append(candidate)

    rendered = "\n".join(lines)
    return rendered if len(rendered) <= max_chars else rendered[:max_chars]


def _as_utc(value: datetime) -> datetime:
    """Normalize naïve database timestamps for freshness comparisons."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _memory_freshness(age: timedelta) -> str:
    """Coarse freshness label; exact observed time is retained beside it."""
    if age <= timedelta(days=1):
        return "today"
    if age <= timedelta(days=14):
        return "recent"
    return "historical"
