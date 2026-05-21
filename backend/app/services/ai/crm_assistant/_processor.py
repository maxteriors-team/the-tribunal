"""CRM assistant processor — orchestrates LLM + tool execution for operator chat.

Architecture:
- Multi-turn tool loop (capped) so the model can chain actions like
  search → send_sms in one user request.
- Sequential tool execution within a single turn — tools share a single
  AsyncSession and SQLAlchemy AsyncSession is NOT safe for concurrent
  statements on one connection (raises InvalidRequestError). LLM latency
  dominates; tool DB calls are fast.
- OpenAI prompt caching via `prompt_cache_key` keyed per (workspace, user)
  — the system prompt prefix stays byte-identical across turns so
  cached_tokens hit on every follow-up call.
- Auto-summarization when the message log grows past a token budget,
  preserving the system prefix for cache stability.

Patterns adapted from ezcoder's agent-loop and compactor (see /home/groot/ezcoder).
"""

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.assistant_conversation import AssistantConversation, AssistantMessage
from app.services.ai.crm_assistant._summarizer import maybe_summarize
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools
from app.services.ai.openai_credentials import create_openai_client

logger = structlog.get_logger()

# ── Configuration ────────────────────────────────────────────────────
MODEL = "gpt-5.4-nano"
MAX_TOOL_TURNS = 5  # safety cap on chained tool calls
HISTORY_LOAD_LIMIT = 60  # rows pulled from DB before summarization
LLM_TIMEOUT_SECONDS = 45.0
MAX_COMPLETION_TOKENS = 800
TEMPERATURE = 0.3

AssistantStreamEvent = dict[str, Any]


@dataclass(slots=True)
class _StreamToolFunction:
    """Function call payload reconstructed from streamed deltas."""

    name: str
    arguments: str


@dataclass(slots=True)
class _StreamToolCall:
    """Tool call payload reconstructed from streamed deltas."""

    id: str
    function: _StreamToolFunction


@dataclass(slots=True)
class _StreamToolCallAccumulator:
    """Mutable tool call accumulator keyed by streamed tool-call index."""

    id: str = ""
    name_parts: list[str] = field(default_factory=list)
    argument_parts: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return "".join(self.name_parts)

    @property
    def arguments(self) -> str:
        return "".join(self.argument_parts)

    def to_tool_call(self) -> _StreamToolCall:
        return _StreamToolCall(
            id=self.id,
            function=_StreamToolFunction(name=self.name, arguments=self.arguments),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


# Concise, action-oriented system prompt. Style borrowed from ezcoder's
# system-prompt.ts: short bullets, clear rules, no preamble.
SYSTEM_PROMPT = """\
You are the CRM operator assistant. Help the user run their CRM by calling tools.

## How to talk
- Be concise. 1–3 sentences per reply.
- After taking action, confirm what you did in one line.
- No preamble, no recap, no "let me know if…".

## How to work
- Prefer tools over guessing. If you need data, call a tool.
- Chain tools when needed (e.g. search_contacts → send_sms).
- Confirm destructive actions (sending SMS, creating records) before doing them, \
unless the user already gave a clear directive.
- If a tool fails, surface the error briefly and stop — don't retry blindly."""


def _cache_key(workspace_id: uuid.UUID, user_id: int) -> str:
    """Stable per-(workspace, user) key for OpenAI prompt caching.

    OpenAI uses this as a routing hint to keep similar requests on the
    same machine for prefix-cache hits. Each operator gets their own
    bucket so their conversation prefix stays warm.
    See: https://platform.openai.com/docs/guides/prompt-caching
    """
    raw = f"crm_assistant:{workspace_id}:{user_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _serialize_history(rows: list[AssistantMessage]) -> list[dict[str, Any]]:
    """Convert DB rows into the OpenAI Chat Completions message shape."""
    out: list[dict[str, Any]] = []
    for msg in rows:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = msg.tool_calls
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        out.append(entry)
    return out


def _repair_pairing(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop any orphan tool_calls or tool_results that would cause a 400.

    Mirrors ezcoder's repairToolPairing — defensive cleanup before sending
    to OpenAI in case a previous turn was interrupted mid-loop and left
    asymmetric history in the DB.
    """
    call_ids: set[str] = set()
    result_ids: set[str] = set()
    for msg in messages:
        for tc in msg.get("tool_calls") or []:
            tcid = tc.get("id")
            if tcid:
                call_ids.add(tcid)
        if msg.get("role") == "tool":
            tcid = msg.get("tool_call_id")
            if tcid:
                result_ids.add(tcid)

    repaired: list[dict[str, Any]] = []
    for msg in messages:
        # Drop orphan tool results
        if msg.get("role") == "tool" and msg.get("tool_call_id") not in call_ids:
            continue
        # Strip orphan tool_calls from assistant messages
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            kept = [tc for tc in msg["tool_calls"] if tc.get("id") in result_ids]
            new_msg = dict(msg)
            if kept:
                new_msg["tool_calls"] = kept
            else:
                new_msg.pop("tool_calls", None)
                # If the assistant message had no text content either, skip it.
                if not new_msg.get("content"):
                    continue
            repaired.append(new_msg)
            continue
        repaired.append(msg)
    return repaired


async def _get_or_create_conversation(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
    conversation_id: uuid.UUID | None,
) -> AssistantConversation:
    """Load a scoped assistant conversation, preserving legacy latest-thread behavior."""
    stmt = select(AssistantConversation).where(
        AssistantConversation.workspace_id == workspace_id,
        AssistantConversation.user_id == user_id,
    )
    if conversation_id is not None:
        stmt = stmt.where(AssistantConversation.id == conversation_id)
    else:
        stmt = stmt.order_by(
            AssistantConversation.updated_at.desc(),
            AssistantConversation.created_at.desc(),
        ).limit(1)

    result = await db.execute(stmt)
    conversation = result.scalar_one_or_none()
    if conversation is not None:
        return conversation

    if conversation_id is None:
        conversation = AssistantConversation(workspace_id=workspace_id, user_id=user_id)
    else:
        conversation = AssistantConversation(
            id=conversation_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
    db.add(conversation)
    await db.flush()
    return conversation


def _touch_conversation(conversation: AssistantConversation) -> None:
    """Mark a conversation as recently active for list ordering."""
    conversation.updated_at = datetime.now(UTC)


async def _append_assistant_message(
    db: AsyncSession,
    conversation: AssistantConversation,
    role: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_call_id: str | None = None,
) -> AssistantMessage:
    """Persist one assistant conversation message and update parent recency."""
    _touch_conversation(conversation)
    assistant_message = AssistantMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )
    db.add(assistant_message)
    await db.flush()
    return assistant_message


async def _build_api_messages(
    db: AsyncSession,
    conversation_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Load recent conversation history and build OpenAI chat messages."""
    history_result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation_id)
        .order_by(AssistantMessage.created_at.desc())
        .limit(HISTORY_LOAD_LIMIT)
    )
    history_rows = list(reversed(history_result.scalars().all()))
    return _repair_pairing(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            *_serialize_history(history_rows),
        ]
    )


async def _execute_tool_calls_sequential(
    executor: CRMToolExecutor,
    tool_calls: list[Any],
) -> list[dict[str, Any]]:
    """Run all tool calls in a single turn sequentially.

    Returns a list of dicts: { id, name, arguments, result } in the same
    order as `tool_calls`, so we can build matching tool messages and
    actions_taken summaries.

    Sequential (not asyncio.gather) because every tool shares the same
    AsyncSession via `executor.db`, and SQLAlchemy AsyncSession does not
    support concurrent statements on a single connection — concurrent use
    raises InvalidRequestError. The same constraint motivated the
    sequential rewrite of `services/contacts/engagement_summary.py`.
    """
    results: list[dict[str, Any]] = []
    for tc in tool_calls:
        name = tc.function.name
        try:
            args = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            args = {}
        result = await executor.execute(name, args)
        results.append({"id": tc.id, "name": name, "arguments": args, "result": result})
    return results


def _api_params(api_messages: list[dict[str, Any]], cache_key: str) -> dict[str, Any]:
    """Build OpenAI chat completion parameters shared by normal and stream calls."""
    return {
        "model": MODEL,
        "messages": api_messages,
        "tools": get_crm_tools(),
        "tool_choice": "auto",
        "temperature": TEMPERATURE,
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
        "prompt_cache_key": cache_key,
    }


async def _collect_stream_turn(
    client: Any,
    api_messages: list[dict[str, Any]],
    cache_key: str,
) -> AsyncIterator[AssistantStreamEvent]:
    """Stream one OpenAI assistant turn while accumulating text and tool calls."""
    api_params = {**_api_params(api_messages, cache_key), "stream": True}
    stream = await asyncio.wait_for(
        client.chat.completions.create(**api_params),
        timeout=LLM_TIMEOUT_SECONDS,
    )

    content_parts: list[str] = []
    tool_accumulators: dict[int, _StreamToolCallAccumulator] = {}

    async for chunk in stream:
        if not chunk.choices:
            continue
        choice = chunk.choices[0]
        delta = choice.delta
        if delta.content:
            content_parts.append(delta.content)
            yield {"type": "delta", "text": delta.content}
        for tool_delta in delta.tool_calls or []:
            accumulator = tool_accumulators.setdefault(
                tool_delta.index,
                _StreamToolCallAccumulator(),
            )
            if tool_delta.id:
                accumulator.id = tool_delta.id
            if tool_delta.function:
                if tool_delta.function.name:
                    accumulator.name_parts.append(tool_delta.function.name)
                if tool_delta.function.arguments:
                    accumulator.argument_parts.append(tool_delta.function.arguments)

    ordered_calls = [
        accumulator.to_tool_call()
        for _, accumulator in sorted(tool_accumulators.items(), key=lambda item: item[0])
        if accumulator.id and accumulator.name
    ]
    payloads = [
        accumulator.to_payload()
        for _, accumulator in sorted(tool_accumulators.items(), key=lambda item: item[0])
        if accumulator.id and accumulator.name
    ]
    yield {
        "type": "turn_complete",
        "content": "".join(content_parts),
        "tool_calls": ordered_calls,
        "tool_calls_payload": payloads,
    }


async def stream_assistant_message(  # noqa: PLR0912, PLR0915
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
    message: str,
    conversation_id: uuid.UUID | None = None,
) -> AsyncIterator[AssistantStreamEvent]:
    """Process an operator message and yield assistant stream events."""
    log = logger.bind(
        workspace_id=str(workspace_id),
        user_id=user_id,
        conversation_id=str(conversation_id) if conversation_id else None,
        channel="stream",
    )
    log.info("streaming_assistant_message")

    conversation = await _get_or_create_conversation(
        db=db,
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    await _append_assistant_message(db, conversation, "user", message)
    api_messages = await _build_api_messages(db, conversation.id)

    client = create_openai_client()
    cache_key = _cache_key(workspace_id, user_id)
    api_messages = await maybe_summarize(client, api_messages)

    actions_taken: list[dict[str, Any]] = []
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=user_id)
    final_message: AssistantMessage | None = None

    try:
        for _turn_idx in range(MAX_TOOL_TURNS):
            turn_result: AssistantStreamEvent | None = None
            async for event in _collect_stream_turn(client, api_messages, cache_key):
                if event.get("type") == "turn_complete":
                    turn_result = event
                    continue
                yield event

            if turn_result is None:
                raise RuntimeError("OpenAI stream ended without a completed turn")

            content = str(turn_result.get("content") or "")
            tool_calls = turn_result.get("tool_calls")
            tool_calls_payload = turn_result.get("tool_calls_payload")
            if not isinstance(tool_calls, list):
                tool_calls = []
            if not isinstance(tool_calls_payload, list):
                tool_calls_payload = []

            if not tool_calls:
                if not content:
                    content = "I processed your request but couldn't generate a response."
                    yield {"type": "delta", "text": content}
                final_message = await _append_assistant_message(
                    db,
                    conversation,
                    "assistant",
                    content,
                )
                break

            await _append_assistant_message(
                db,
                conversation,
                "assistant",
                content,
                tool_calls=tool_calls_payload,
            )
            api_messages.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls_payload,
                }
            )

            executions: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                if not isinstance(tool_call, _StreamToolCall):
                    continue
                name = tool_call.function.name
                yield {"type": "tool_start", "name": name}
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                result = await executor.execute(name, args)
                executions.append(
                    {"id": tool_call.id, "name": name, "arguments": args, "result": result}
                )
                yield {"type": "tool_end", "name": name, "success": result.get("success", False)}

            for ex in executions:
                result_json = json.dumps(ex["result"])
                await _append_assistant_message(
                    db,
                    conversation,
                    "tool",
                    result_json,
                    tool_call_id=ex["id"],
                )
                api_messages.append(
                    {"role": "tool", "tool_call_id": ex["id"], "content": result_json}
                )
                actions_taken.append(
                    {
                        "tool_name": ex["name"],
                        "success": ex["result"].get("success", False),
                        "summary": result_json[:200],
                    }
                )
        else:
            log.warning("tool_loop_cap_reached", turns=MAX_TOOL_TURNS)
            cap_text = (
                "I worked through several steps but couldn't finish in one go. "
                "Want me to keep going, or refine the request?"
            )
            yield {"type": "delta", "text": cap_text}
            final_message = await _append_assistant_message(
                db,
                conversation,
                "assistant",
                cap_text,
            )

        await db.commit()
        yield {
            "type": "done",
            "conversation_id": str(conversation.id),
            "message_id": str(final_message.id) if final_message else None,
            "actions_taken": actions_taken,
        }
    except asyncio.CancelledError:
        log.info("assistant_stream_cancelled")
        await db.commit()
        raise
    except TimeoutError:
        log.error("assistant_stream_timeout")
        await db.commit()
        yield {"type": "error", "message": "Sorry, that took too long. Please try again."}
    except Exception:
        log.exception("assistant_stream_error")
        await db.commit()
        yield {
            "type": "error",
            "message": "Something went wrong processing your request. Please try again.",
        }


async def process_assistant_message(  # noqa: PLR0915
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
    message: str,
    conversation_id: uuid.UUID | None = None,
    response_channel: str = "in_app",
    sms_from_number: str | None = None,
    sms_to_number: str | None = None,
) -> dict[str, Any]:
    """Process an operator message through the CRM assistant.

    Returns a dict with:
        response: str — final assistant text
        actions_taken: list[{tool_name, success, summary}]
    """
    log = logger.bind(
        workspace_id=str(workspace_id),
        user_id=user_id,
        conversation_id=str(conversation_id) if conversation_id else None,
        channel=response_channel,
    )
    log.info("processing_assistant_message")

    # ── 1. Get or create conversation ──────────────────────────────────
    conversation = await _get_or_create_conversation(
        db=db,
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )

    # ── 2. Append user message ─────────────────────────────────────────
    await _append_assistant_message(db, conversation, "user", message)

    # ── 3. Load history (most recent N), oldest first ──────────────────
    api_messages = await _build_api_messages(db, conversation.id)

    client = create_openai_client()
    cache_key = _cache_key(workspace_id, user_id)

    # Compact older history if we're over budget. Preserves the system
    # prefix so prompt caching keeps hitting.
    api_messages = await maybe_summarize(client, api_messages)

    actions_taken: list[dict[str, Any]] = []
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=user_id)
    final_text: str | None = None

    try:
        # ── 4. Tool loop ───────────────────────────────────────────────
        for turn_idx in range(MAX_TOOL_TURNS):
            api_params = _api_params(api_messages, cache_key)
            response = await asyncio.wait_for(
                client.chat.completions.create(**api_params),
                timeout=LLM_TIMEOUT_SECONDS,
            )
            assistant_msg = response.choices[0].message

            # Log cache utilization for observability
            usage = response.usage
            if usage and usage.prompt_tokens_details:
                log.info(
                    "llm_call",
                    turn=turn_idx,
                    prompt_tokens=usage.prompt_tokens,
                    cached_tokens=usage.prompt_tokens_details.cached_tokens or 0,
                    completion_tokens=usage.completion_tokens,
                )

            # No tool calls → terminal turn
            if not assistant_msg.tool_calls:
                final_text = assistant_msg.content
                if final_text:
                    await _append_assistant_message(db, conversation, "assistant", final_text)
                break

            # Tool calls → record assistant turn, execute sequentially, append results.
            tool_calls_payload = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in assistant_msg.tool_calls
            ]
            await _append_assistant_message(
                db,
                conversation,
                "assistant",
                assistant_msg.content or "",
                tool_calls=tool_calls_payload,
            )
            api_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.content,
                    "tool_calls": tool_calls_payload,
                }
            )

            executions = await _execute_tool_calls_sequential(executor, assistant_msg.tool_calls)
            for ex in executions:
                result_json = json.dumps(ex["result"])
                await _append_assistant_message(
                    db,
                    conversation,
                    "tool",
                    result_json,
                    tool_call_id=ex["id"],
                )
                api_messages.append(
                    {"role": "tool", "tool_call_id": ex["id"], "content": result_json}
                )
                actions_taken.append(
                    {
                        "tool_name": ex["name"],
                        "success": ex["result"].get("success", False),
                        "summary": result_json[:200],
                    }
                )
            await db.flush()
        else:
            # Fell out of the loop without a final reply — cap reached.
            log.warning("tool_loop_cap_reached", turns=MAX_TOOL_TURNS)
            final_text = (
                "I worked through several steps but couldn't finish in one go. "
                "Want me to keep going, or refine the request?"
            )
            await _append_assistant_message(db, conversation, "assistant", final_text)

        if not final_text:
            final_text = "I processed your request but couldn't generate a response."

        await db.commit()

        if response_channel == "sms" and sms_from_number and sms_to_number:
            await _send_sms_response(
                sms_from_number,
                sms_to_number,
                final_text,
                db,
                workspace_id,
                log,
            )

        return {
            "response": final_text,
            "actions_taken": actions_taken,
            "conversation_id": str(conversation.id),
        }

    except TimeoutError:
        log.error("assistant_llm_timeout")
        await db.commit()
        return {
            "response": "Sorry, that took too long. Please try again.",
            "actions_taken": actions_taken,
            "conversation_id": str(conversation.id),
        }
    except Exception:
        log.exception("assistant_processing_error")
        await db.commit()
        return {
            "response": "Something went wrong processing your request. Please try again.",
            "actions_taken": actions_taken,
            "conversation_id": str(conversation.id),
        }


async def _send_sms_response(
    from_number: str,
    to_number: str,
    body: str,
    db: AsyncSession,
    workspace_id: uuid.UUID,
    log: Any,
) -> None:
    """Send the assistant's final reply as an SMS to the operator."""
    from app.services.telephony.telnyx import TelnyxSMSService

    telnyx_key = settings.telnyx_api_key
    if not telnyx_key:
        log.warning("no_telnyx_key_for_sms_response")
        return

    sms_service = TelnyxSMSService(telnyx_key)
    try:
        await sms_service.send_message(
            to_number=to_number,
            from_number=from_number,
            body=body,
            db=db,
            workspace_id=workspace_id,
        )
        log.info("assistant_sms_sent", to=to_number)
    except Exception:
        log.exception("assistant_sms_send_failed")
    finally:
        await sms_service.close()
