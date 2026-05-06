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
from typing import Any

import structlog
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.assistant_conversation import AssistantConversation, AssistantMessage
from app.services.ai.crm_assistant._summarizer import maybe_summarize
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools

logger = structlog.get_logger()

# ── Configuration ────────────────────────────────────────────────────
MODEL = "gpt-5.4-nano"
MAX_TOOL_TURNS = 5  # safety cap on chained tool calls
HISTORY_LOAD_LIMIT = 60  # rows pulled from DB before summarization
LLM_TIMEOUT_SECONDS = 45.0
MAX_COMPLETION_TOKENS = 800
TEMPERATURE = 0.3

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


async def process_assistant_message(  # noqa: PLR0913, PLR0915
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
    message: str,
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
        channel=response_channel,
    )
    log.info("processing_assistant_message")

    # ── 1. Get or create conversation ──────────────────────────────────
    conv_result = await db.execute(
        select(AssistantConversation).where(
            AssistantConversation.workspace_id == workspace_id,
            AssistantConversation.user_id == user_id,
        )
    )
    conversation = conv_result.scalar_one_or_none()
    if conversation is None:
        conversation = AssistantConversation(workspace_id=workspace_id, user_id=user_id)
        db.add(conversation)
        await db.flush()

    # ── 2. Append user message ─────────────────────────────────────────
    db.add(AssistantMessage(conversation_id=conversation.id, role="user", content=message))
    await db.flush()

    # ── 3. Load history (most recent N), oldest first ──────────────────
    history_result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation.id)
        .order_by(AssistantMessage.created_at.desc())
        .limit(HISTORY_LOAD_LIMIT)
    )
    history_rows = list(reversed(history_result.scalars().all()))

    api_messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *_serialize_history(history_rows),
    ]
    api_messages = _repair_pairing(api_messages)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
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
            api_params: dict[str, Any] = {
                "model": MODEL,
                "messages": api_messages,
                "tools": get_crm_tools(),
                "tool_choice": "auto",
                "temperature": TEMPERATURE,
                "max_completion_tokens": MAX_COMPLETION_TOKENS,
                "prompt_cache_key": cache_key,
            }
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
                    db.add(
                        AssistantMessage(
                            conversation_id=conversation.id,
                            role="assistant",
                            content=final_text,
                        )
                    )
                    await db.flush()
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
            db.add(
                AssistantMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=assistant_msg.content or "",
                    tool_calls=tool_calls_payload,
                )
            )
            await db.flush()
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
                db.add(
                    AssistantMessage(
                        conversation_id=conversation.id,
                        role="tool",
                        content=result_json,
                        tool_call_id=ex["id"],
                    )
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
            db.add(
                AssistantMessage(
                    conversation_id=conversation.id,
                    role="assistant",
                    content=final_text,
                )
            )
            await db.flush()

        if not final_text:
            final_text = "I processed your request but couldn't generate a response."

        await db.commit()

        if response_channel == "sms" and sms_from_number and sms_to_number:
            await _send_sms_response(
                sms_from_number, sms_to_number, final_text, db, workspace_id, log,
            )

        return {"response": final_text, "actions_taken": actions_taken}

    except TimeoutError:
        log.error("assistant_llm_timeout")
        await db.commit()
        return {
            "response": "Sorry, that took too long. Please try again.",
            "actions_taken": actions_taken,
        }
    except Exception:
        log.exception("assistant_processing_error")
        await db.commit()
        return {
            "response": "Something went wrong processing your request. Please try again.",
            "actions_taken": actions_taken,
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
