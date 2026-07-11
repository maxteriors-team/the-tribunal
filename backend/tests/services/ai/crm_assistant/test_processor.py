"""Tests for the CRM assistant processor.

Covers:
- Single-turn (no tool call) response.
- Tool-loop dispatch + actions_taken accumulation.
- prompt_cache_key is set per (workspace, user) and stays stable.
- Tool-pairing repair drops orphan tool_calls/results.
"""

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.crm_assistant import _processor as processor


def _make_response(
    *,
    content: str | None = None,
    tool_calls: list[Any] | None = None,
) -> SimpleNamespace:
    """Mimic an OpenAI ChatCompletion response."""
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(
        prompt_tokens=100,
        completion_tokens=50,
        prompt_tokens_details=SimpleNamespace(cached_tokens=80),
    )
    return SimpleNamespace(choices=[choice], usage=usage)


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    import json

    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )


def _make_db() -> AsyncMock:
    db = AsyncMock()
    # Default: no existing conversation
    no_conv = MagicMock()
    no_conv.scalar_one_or_none.return_value = None
    no_history = MagicMock()
    no_history.scalars.return_value.all.return_value = []
    db.execute.side_effect = [no_conv, no_history]
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    return db


@pytest.mark.asyncio
async def test_enhance_prompt_uses_workspace_client_without_executing_tools() -> None:
    """Enhancement rewrites the draft only and uses the tenant credential."""
    db = AsyncMock()
    workspace_id = uuid.uuid4()
    create = AsyncMock(
        return_value=_make_response(
            content=(
                "Analyze my five newest contacts using dated CRM evidence; "
                "rank follow-up priority and label missing data."
            )
        )
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch.object(
        processor,
        "create_workspace_openai_client",
        new=AsyncMock(return_value=fake_client),
    ) as client_factory:
        enhanced = await processor.enhance_assistant_prompt(
            db,
            workspace_id,
            "Who needs follow-up?",
        )

    client_factory.assert_awaited_once_with(db, workspace_id)
    assert "dated CRM evidence" in enhanced
    request = create.await_args.kwargs
    assert "tools" not in request
    assert request["messages"][-1] == {"role": "user", "content": "Who needs follow-up?"}


@pytest.mark.asyncio
async def test_simple_response_no_tools() -> None:
    """When the LLM returns plain text, return it as the response."""
    db = _make_db()
    workspace_id = uuid.uuid4()
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(return_value=_make_response(content="Hello, operator."))
            )
        )
    )

    with patch.object(
        processor,
        "create_workspace_openai_client",
        new=AsyncMock(return_value=fake_client),
    ) as client_factory, patch.object(
        processor, "maybe_summarize", AsyncMock(side_effect=lambda _c, m: m)
    ):
        result = await processor.process_assistant_message(
            db=db, workspace_id=workspace_id, user_id=42, message="hi",
        )

    assert result["response"] == "Hello, operator."
    assert result["actions_taken"] == []
    client_factory.assert_awaited_once_with(db, workspace_id)
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_stream_uses_workspace_openai_client() -> None:
    """Streaming chat resolves the requesting workspace's credential."""
    db = _make_db()
    workspace_id = uuid.uuid4()
    fake_client = SimpleNamespace()

    async def fake_stream_turn(*_args: Any) -> Any:
        yield {"type": "delta", "text": "Hello"}
        yield {
            "type": "turn_complete",
            "content": "Hello",
            "tool_calls": [],
            "tool_calls_payload": [],
        }

    with patch.object(
        processor,
        "create_workspace_openai_client",
        new=AsyncMock(return_value=fake_client),
    ) as client_factory, patch.object(
        processor, "maybe_summarize", AsyncMock(side_effect=lambda _c, m: m)
    ), patch.object(processor, "_collect_stream_turn", new=fake_stream_turn):
        events = [
            event
            async for event in processor.stream_assistant_message(
                db=db,
                workspace_id=workspace_id,
                user_id=42,
                message="hi",
            )
        ]

    client_factory.assert_awaited_once_with(db, workspace_id)
    assert events[0] == {"type": "delta", "text": "Hello"}
    assert events[-1]["type"] == "done"
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_tool_loop_dispatches_and_records_actions() -> None:
    """Tool call → executor runs → follow-up call returns final text."""
    db = _make_db()
    workspace_id = uuid.uuid4()

    create = AsyncMock(
        side_effect=[
            _make_response(
                tool_calls=[_tool_call("call_1", "get_dashboard_stats", {})],
            ),
            _make_response(content="You have 5 contacts."),
        ]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch.object(
        processor,
        "create_workspace_openai_client",
        new=AsyncMock(return_value=fake_client),
    ), patch.object(
        processor, "maybe_summarize", AsyncMock(side_effect=lambda _c, m: m)
    ), patch.object(
        processor.CRMToolExecutor,
        "execute",
        AsyncMock(return_value={"success": True, "data": {"contacts": 5}}),
    ):
        result = await processor.process_assistant_message(
            db=db, workspace_id=workspace_id, user_id=42, message="how many contacts?",
        )

    assert result["response"] == "You have 5 contacts."
    assert len(result["actions_taken"]) == 1
    assert result["actions_taken"][0]["tool_name"] == "get_dashboard_stats"
    assert result["actions_taken"][0]["success"] is True
    # Two LLM calls: tool turn + final reply turn
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_five_contact_summary_can_reach_terminal_response() -> None:
    """Search plus five detail lookups must fit before the bounded loop cap."""
    db = _make_db()
    workspace_id = uuid.uuid4()
    responses = [
        _make_response(tool_calls=[_tool_call("search", "search_contacts", {"limit": 5})]),
        *[
            _make_response(
                tool_calls=[
                    _tool_call(
                        f"conversation_{index}",
                        "get_conversation",
                        {"contact_id": index},
                    )
                ]
            )
            for index in range(1, 6)
        ],
        _make_response(content="Contact summary complete."),
    ]
    create = AsyncMock(side_effect=responses)
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch.object(
        processor,
        "create_workspace_openai_client",
        new=AsyncMock(return_value=fake_client),
    ), patch.object(
        processor, "maybe_summarize", AsyncMock(side_effect=lambda _c, m: m)
    ), patch.object(
        processor.CRMToolExecutor,
        "execute",
        AsyncMock(return_value={"success": True, "data": []}),
    ):
        result = await processor.process_assistant_message(
            db=db,
            workspace_id=workspace_id,
            user_id=42,
            message="Summarize my five newest contacts.",
        )

    assert result["response"] == "Contact summary complete."
    assert create.await_count == 7
    assert len(result["actions_taken"]) == 6


@pytest.mark.asyncio
async def test_prompt_cache_key_is_stable_and_workspace_scoped() -> None:
    """Same (workspace, user) → same cache key. Different workspace → different key."""
    ws_a = uuid.uuid4()
    ws_b = uuid.uuid4()
    key_a1 = processor._cache_key(ws_a, 1)
    key_a1_again = processor._cache_key(ws_a, 1)
    key_a2 = processor._cache_key(ws_a, 2)
    key_b1 = processor._cache_key(ws_b, 1)

    assert key_a1 == key_a1_again
    assert key_a1 != key_a2  # different user
    assert key_a1 != key_b1  # different workspace
    assert len(key_a1) == 32  # truncated sha256


@pytest.mark.asyncio
async def test_prompt_cache_key_passed_to_openai_call() -> None:
    """The processor must forward prompt_cache_key on every chat completion call."""
    db = _make_db()
    workspace_id = uuid.uuid4()
    create = AsyncMock(return_value=_make_response(content="ok"))
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    with patch.object(
        processor,
        "create_workspace_openai_client",
        new=AsyncMock(return_value=fake_client),
    ), patch.object(
        processor, "maybe_summarize", AsyncMock(side_effect=lambda _c, m: m)
    ):
        await processor.process_assistant_message(
            db=db, workspace_id=workspace_id, user_id=99, message="ping",
        )

    assert create.await_count == 1
    kwargs = create.await_args.kwargs
    assert "prompt_cache_key" in kwargs
    assert kwargs["prompt_cache_key"] == processor._cache_key(workspace_id, 99)


def test_repair_pairing_drops_orphan_tool_results() -> None:
    """Tool messages whose tool_call_id has no matching assistant call are removed."""
    messages = [
        {"role": "system", "content": "x"},
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "ghost", "content": "{}"},
    ]
    repaired = processor._repair_pairing(messages)
    assert all(m.get("role") != "tool" for m in repaired)


def test_repair_pairing_strips_orphan_tool_calls_from_assistant() -> None:
    """Assistant tool_calls without a matching tool result are stripped, keeping text."""
    messages = [
        {"role": "system", "content": "x"},
        {
            "role": "assistant",
            "content": "thinking…",
            "tool_calls": [
                {"id": "call_orphan", "type": "function",
                 "function": {"name": "foo", "arguments": "{}"}},
            ],
        },
    ]
    repaired = processor._repair_pairing(messages)
    assistant = next(m for m in repaired if m["role"] == "assistant")
    assert "tool_calls" not in assistant
    assert assistant["content"] == "thinking…"


def test_repair_pairing_drops_assistant_with_only_orphan_calls_and_no_text() -> None:
    """Empty assistant turns with only orphan tool_calls are dropped entirely."""
    messages = [
        {"role": "system", "content": "x"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_orphan", "type": "function",
                 "function": {"name": "foo", "arguments": "{}"}},
            ],
        },
        {"role": "user", "content": "hi"},
    ]
    repaired = processor._repair_pairing(messages)
    roles = [m["role"] for m in repaired]
    assert roles == ["system", "user"]
