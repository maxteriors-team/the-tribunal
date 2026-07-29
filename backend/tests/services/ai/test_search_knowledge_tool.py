"""Tests for exposing hybrid retrieval as the on-demand ``search_knowledge`` tool.

Covers tool-definition wiring (voice + text formats), opt-in enablement from
agent config, and that both executors dispatch ``search_knowledge`` to the shared
knowledge search executor scoped to the call's workspace + agent.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.ai import text_tool_executor as tte_mod
from app.services.ai import tool_executor as vte_mod
from app.services.ai.text_tool_executor import TextToolExecutor
from app.services.ai.tool_executor import VoiceToolExecutor
from app.services.ai.voice_tools import (
    SEARCH_KNOWLEDGE_TOOL,
    build_tools_list,
    get_text_search_knowledge_tool,
    get_tools_from_agent_config,
    is_search_knowledge_enabled,
)
from app.services.knowledge import search_tool as search_tool_mod


def _tool_names(tools: list[dict[str, Any]]) -> list[str]:
    names = []
    for tool in tools:
        if "function" in tool:
            names.append(tool["function"]["name"])
        elif "name" in tool:
            names.append(tool["name"])
    return names


# ── Tool definitions ────────────────────────────────────────────────────────
class TestToolDefinitions:
    def test_voice_tool_shape(self) -> None:
        assert SEARCH_KNOWLEDGE_TOOL["type"] == "function"
        assert SEARCH_KNOWLEDGE_TOOL["name"] == "search_knowledge"
        props = SEARCH_KNOWLEDGE_TOOL["parameters"]["properties"]
        assert "query" in props
        assert "top_k" in props
        assert SEARCH_KNOWLEDGE_TOOL["parameters"]["required"] == ["query"]

    def test_text_tool_wraps_in_function_envelope(self) -> None:
        tool = get_text_search_knowledge_tool()
        assert tool["type"] == "function"
        assert tool["function"]["name"] == "search_knowledge"
        assert tool["function"]["parameters"]["required"] == ["query"]

    def test_build_tools_list_includes_when_enabled(self) -> None:
        without = build_tools_list(enable_search_knowledge=False)
        assert "search_knowledge" not in _tool_names(without)
        with_tool = build_tools_list(enable_search_knowledge=True)
        assert "search_knowledge" in _tool_names(with_tool)


# ── Opt-in enablement ───────────────────────────────────────────────────────
class TestEnablement:
    def test_is_enabled_reads_enabled_tools(self) -> None:
        assert is_search_knowledge_enabled(SimpleNamespace(enabled_tools=["search_knowledge"]))
        assert not is_search_knowledge_enabled(SimpleNamespace(enabled_tools=["web_search"]))
        assert not is_search_knowledge_enabled(SimpleNamespace(enabled_tools=None))
        assert not is_search_knowledge_enabled(None)

    def test_agent_config_exposes_tool_when_opted_in(self) -> None:
        agent = SimpleNamespace(
            enabled_tools=["search_knowledge"],
            tool_settings={},
        )
        tools = get_tools_from_agent_config(agent)
        assert "search_knowledge" in _tool_names(tools)

    def test_agent_config_omits_tool_by_default(self) -> None:
        agent = SimpleNamespace(enabled_tools=["book_appointment"], tool_settings={})
        tools = get_tools_from_agent_config(agent)
        assert "search_knowledge" not in _tool_names(tools)


# ── Voice executor dispatch ─────────────────────────────────────────────────
class TestVoiceExecutorDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_to_shared_search_scoped_to_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = uuid.uuid4()
        agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=uuid.uuid4())
        executor = VoiceToolExecutor(agent=agent, workspace_id=ws)

        @asynccontextmanager
        async def fake_session() -> Any:
            yield "db-session"

        monkeypatch.setattr(
            "app.db.session.AsyncSessionLocal",
            lambda: fake_session(),
        )
        captured: dict[str, Any] = {}

        async def fake_search(db: Any, **kwargs: Any) -> dict[str, Any]:
            captured["db"] = db
            captured.update(kwargs)
            return {"success": True, "passages": []}

        monkeypatch.setattr(
            "app.services.knowledge.search_tool.execute_knowledge_search", fake_search
        )

        result = await executor.execute("search_knowledge", {"query": "hours", "top_k": 3})
        assert result["success"] is True
        assert captured["db"] == "db-session"
        assert captured["workspace_id"] == ws  # executor scope wins
        assert captured["agent_id"] == agent.id
        assert captured["query"] == "hours"
        assert captured["top_k"] == 3

    @pytest.mark.asyncio
    async def test_missing_scope_returns_error(self) -> None:
        agent = SimpleNamespace(id=None, workspace_id=None)
        executor = VoiceToolExecutor(agent=agent, workspace_id=None)
        result = await executor.execute("search_knowledge", {"query": "hi"})
        assert result["success"] is False


# ── Text executor dispatch ──────────────────────────────────────────────────
class TestTextExecutorDispatch:
    @pytest.mark.asyncio
    async def test_dispatches_with_conversation_scope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ws = uuid.uuid4()
        agent = SimpleNamespace(id=uuid.uuid4(), workspace_id=ws)
        conversation = SimpleNamespace(id=uuid.uuid4(), workspace_id=ws)
        db = AsyncMock()
        executor = TextToolExecutor.__new__(TextToolExecutor)
        executor.agent = agent
        executor.conversation = conversation
        executor.db = db
        import structlog

        executor.log = structlog.get_logger()

        captured: dict[str, Any] = {}

        async def fake_search(passed_db: Any, **kwargs: Any) -> dict[str, Any]:
            captured["db"] = passed_db
            captured.update(kwargs)
            return {"success": True, "passages": []}

        monkeypatch.setattr(
            "app.services.knowledge.search_tool.execute_knowledge_search", fake_search
        )

        result = await executor.execute("search_knowledge", {"query": "pricing"})
        assert result["success"] is True
        assert captured["db"] is db
        assert captured["workspace_id"] == ws
        assert captured["agent_id"] == agent.id
        assert captured["query"] == "pricing"


# ── Gate exemption constants stay in sync ───────────────────────────────────
def test_gate_exempt_tools_cover_search_knowledge() -> None:
    assert "search_knowledge" in vte_mod.GATE_EXEMPT_TOOLS
    assert "search_knowledge" in tte_mod.GATE_EXEMPT_TOOLS
    # Imported for coverage of the module-level search executor symbol.
    assert callable(search_tool_mod.execute_knowledge_search)
