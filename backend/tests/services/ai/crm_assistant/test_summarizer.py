"""Tests for the CRM assistant summarizer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai.crm_assistant import _summarizer as summarizer


def test_estimate_tokens_includes_tool_calls() -> None:
    msgs = [
        {"role": "user", "content": "x" * 40},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "1",
                    "type": "function",
                    "function": {"name": "list_agents", "arguments": "{}"},
                },
            ],
        },
    ]
    # 40 chars + ~12 chars of name+args → at 4 chars/token, ≥10 tokens
    assert summarizer.estimate_tokens(msgs) >= 10


def test_no_summarize_below_trigger() -> None:
    """Short conversations are returned unchanged with no LLM call."""
    msgs = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock()))
    )

    import asyncio

    out = asyncio.run(summarizer.maybe_summarize(fake_client, msgs))
    assert out == msgs
    fake_client.chat.completions.create.assert_not_called()


@pytest.mark.asyncio
async def test_summarize_replaces_middle_keeps_recent_and_system() -> None:
    """When over budget: system (idx 0) preserved + recent tail intact."""
    long_text = "x" * (summarizer._CHARS_PER_TOKEN * summarizer.SUMMARIZE_TRIGGER_TOKENS + 1000)
    msgs = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": long_text},  # forces budget overflow
    ]
    # Add enough recent messages to exceed KEEP_RECENT
    for i in range(summarizer.KEEP_RECENT_MESSAGES + 4):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"})

    fake_response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="SUMMARY_TEXT"))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=fake_response))
        )
    )

    out = await summarizer.maybe_summarize(fake_client, msgs)

    # System prompt preserved byte-for-byte (cache stability)
    assert out[0] == msgs[0]
    # Second message is now the summary system note
    assert out[1]["role"] == "system"
    assert "SUMMARY_TEXT" in out[1]["content"]
    # Tail preserved
    assert out[-1] == msgs[-1]
    # Total length reduced
    assert len(out) < len(msgs)


@pytest.mark.asyncio
async def test_summarize_falls_back_on_llm_failure() -> None:
    """If the summary call fails, return the original messages unchanged."""
    long_text = "x" * (summarizer._CHARS_PER_TOKEN * summarizer.SUMMARIZE_TRIGGER_TOKENS + 1000)
    msgs = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": long_text},
    ]
    for i in range(summarizer.KEEP_RECENT_MESSAGES + 4):
        msgs.append({"role": "user", "content": f"m{i}"})

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("boom")))
        )
    )

    out = await summarizer.maybe_summarize(fake_client, msgs)
    assert out == msgs


def test_split_point_avoids_breaking_tool_pairs() -> None:
    """Cut point should not land between an assistant tool_calls and its tool result."""
    msgs = [{"role": "system", "content": "s"}]
    # A long history of plain user/assistant
    for i in range(20):
        msgs.append({"role": "user", "content": f"u{i}"})
        msgs.append({"role": "assistant", "content": f"a{i}"})
    # Ending with an assistant→tool pair
    msgs.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "T1", "type": "function", "function": {"name": "x", "arguments": "{}"}},
            ],
        }
    )
    msgs.append({"role": "tool", "tool_call_id": "T1", "content": "{}"})

    cut = summarizer._find_split_point(msgs)
    # The cut must not be on a 'tool' message
    assert msgs[cut].get("role") != "tool"
    # If cut-1 is an assistant with tool_calls, it shouldn't be — we backed up further
    if cut > 0 and msgs[cut - 1].get("role") == "assistant":
        assert not msgs[cut - 1].get("tool_calls")
