"""Conversation history summarization for the CRM assistant.

Pattern: when the message log exceeds a token budget, summarize older
messages into a single system note and keep the most recent N intact.
This stabilizes the prefix (system + summary) for prompt caching while
preserving the live conversation tail for coherent multi-turn behavior.

Adapted from ezcoder's compactor pattern, simplified for the CRM
assistant's smaller context (no images, no thinking blocks, no
multi-provider concerns).
"""

import asyncio
from typing import Any

import structlog
from openai import AsyncOpenAI

from app.core.config import settings

logger = structlog.get_logger()

# ── Tunables ─────────────────────────────────────────────────────────
# Approx 4 chars/token — same heuristic ezcoder uses.
_CHARS_PER_TOKEN = 4

# When the conversation exceeds this token estimate, summarize.
SUMMARIZE_TRIGGER_TOKENS = 6_000

# Always keep at least this many of the most recent messages verbatim.
KEEP_RECENT_MESSAGES = 8

# Tool result content is truncated to this many chars before being fed to
# the summarizer — keeps the summarizer focused on intent, not blobs.
TOOL_RESULT_MAX_CHARS = 1_500

# Cap on the summarizer's own output.
MAX_SUMMARY_TOKENS = 600

# Summarisation is one mechanical rewrite with no tools, so it deliberately
# stays on the cheapest tier even though the main tool loop does not.
SUMMARY_MODEL = settings.openai_assistant_summary_model

_SUMMARY_SYSTEM_PROMPT = (
    "You compact CRM operator chat history into a brief technical summary. "
    "Output only the summary — no preamble, no questions.\n\n"
    "Include: operator's goals, contacts/campaigns/agents referenced by id or name, "
    "actions taken (tools called + outcome), key facts the assistant should remember.\n"
    "Exclude: tool-call boilerplate, full record dumps, conversational filler, "
    "anything already implied by the recent messages.\n"
    "Write in third person, factual tone. 200 words max."
)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough char-based token estimate. Matches the heuristic ezcoder uses
    for compaction triggers — accurate enough to drive the threshold."""
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    total += len(str(part.get("text", "")))
        # Tool calls add JSON overhead
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            total += len(fn.get("name", "")) + len(fn.get("arguments", ""))
    return total // _CHARS_PER_TOKEN


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n[... {len(text) - max_chars} chars truncated]"


def _flatten_for_summary(messages: list[dict[str, Any]]) -> str:
    """Convert a slice of API messages into plain text for the summarizer.

    Mirrors ezcoder's `prepareMessagesForSummary`: tool calls become
    `[Tool: name args]`, tool results become `[Result: ...]`. The
    summarizer never sees the raw tool_call/tool_result pairing, which
    would otherwise impose API constraints on the summary call.
    """
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content") or ""

        if role == "tool":
            text = content if isinstance(content, str) else str(content)
            lines.append(f"[Tool result]\n{_truncate(text, TOOL_RESULT_MAX_CHARS)}")
            continue

        if role == "assistant":
            text = content if isinstance(content, str) else ""
            if text:
                lines.append(f"Assistant: {_truncate(text, TOOL_RESULT_MAX_CHARS)}")
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                lines.append(f"[Tool call: {fn.get('name', '?')} {fn.get('arguments', '')}]")
            continue

        if role == "user":
            text = content if isinstance(content, str) else str(content)
            lines.append(f"User: {_truncate(text, TOOL_RESULT_MAX_CHARS)}")
            continue

        # Skip system / unknown roles — caller already excluded the system prompt.
    return "\n\n".join(lines)


def system_prefix_length(messages: list[dict[str, Any]]) -> int:
    """Return how many leading messages form the system prefix.

    The prefix is the static ``SYSTEM_PROMPT`` plus the live workspace-context
    message appended after it. Both must survive compaction: dropping the
    context block would silently make the assistant context-blind again the
    moment a conversation grew long enough to summarize.
    """

    length = 0
    for message in messages:
        if message.get("role") != "system":
            break
        length += 1
    return length


def _find_split_point(messages: list[dict[str, Any]]) -> int:
    """Return the index where recent-tail starts.

    Walks back from the end keeping at least KEEP_RECENT_MESSAGES, then
    backs up further so we never split a tool_calls/tool result pair.
    Index 0 (or wherever the system prompt ends) is preserved.
    """
    if len(messages) <= KEEP_RECENT_MESSAGES:
        return len(messages)  # nothing to summarize

    cut = len(messages) - KEEP_RECENT_MESSAGES

    # If we'd cut on a 'tool' message, walk back past all consecutive
    # tool messages and the assistant message that emitted the tool_calls.
    while cut > 0 and messages[cut].get("role") == "tool":
        cut -= 1
    # Now if the message immediately before cut is an assistant with
    # tool_calls, ensure we keep all subsequent tool results — i.e. cut
    # earlier than the assistant.
    if (
        cut > 0
        and messages[cut - 1].get("role") == "assistant"
        and messages[cut - 1].get("tool_calls")
    ):
        cut -= 1

    return max(cut, 1)


async def maybe_summarize(  # noqa: PLR0911
    client: AsyncOpenAI,
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """If `messages` exceed the trigger budget, replace older messages
    with a single system summary message and return the new list.

    The leading system prefix (static prompt + live workspace context) is
    always preserved verbatim — ``messages[0]`` must stay byte-identical for
    prompt caching to hit, and the context block must survive compaction.

    Args:
        client: AsyncOpenAI client used for the summary call.
        messages: API messages including the leading system prompt.

    Returns:
        Either the original list (no compaction needed) or a new list
        of the form [*system_prefix, summary_system, ...recent].
    """
    if not messages or messages[0].get("role") != "system":
        # Defensive: only run when the canonical system prompt is at index 0.
        return messages

    if estimate_tokens(messages) < SUMMARIZE_TRIGGER_TOKENS:
        return messages

    prefix_length = system_prefix_length(messages)
    split = _find_split_point(messages)
    if split <= prefix_length:  # nothing useful to summarize
        return messages

    middle = messages[prefix_length:split]
    if not middle:
        return messages

    log = logger.bind(service="crm_assistant_summarizer")
    log.info(
        "summarizing_history",
        total=len(messages),
        summarizing=len(middle),
        keeping=len(messages) - split,
    )

    flattened = _flatten_for_summary(middle)

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=SUMMARY_MODEL,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"Summarize the following CRM operator chat history:\n\n{flattened}"
                        ),
                    },
                ],
                temperature=0.2,
                max_completion_tokens=MAX_SUMMARY_TOKENS,
            ),
            timeout=20.0,
        )
        summary_text = response.choices[0].message.content
    except (TimeoutError, Exception):  # noqa: BLE001
        log.exception("summary_call_failed")
        return messages  # fall back to raw history; caller decides what to do

    if not summary_text:
        log.warning("empty_summary_returned")
        return messages

    summary_msg = {
        "role": "system",
        "content": (
            f"## Summary of earlier conversation\n{summary_text.strip()}\n## End of summary"
        ),
    }
    recent = messages[split:]
    return [*messages[:prefix_length], summary_msg, *recent]
