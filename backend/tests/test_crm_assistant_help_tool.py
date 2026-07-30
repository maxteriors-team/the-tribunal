"""``search_help`` — the assistant's only grounded answer to a product question.

Before this tool existed the assistant had no product corpus, so "how do I set
up an automation?" was answered from model priors while the prompt forbade
inventing facts. These tests pin the three things that keep the answer honest:
the tool is registered, retrieval is scoped to workspace-level help documents
(``agent_id=None``), and an empty result tells the model to say "I don't know"
rather than fill the gap.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.ai.crm_assistant._help_tools import MAX_TOP_K, HelpAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools
from app.services.knowledge.retrieval_service import DEFAULT_TOP_K


def _passage(title: str, content: str, score: float = 0.87) -> SimpleNamespace:
    return SimpleNamespace(
        document_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        title=title,
        content=content,
        score=score,
    )


@pytest.fixture
def tools() -> HelpAssistantTools:
    context = CRMToolContext(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)
    return HelpAssistantTools(context)


def _patch_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    passages: list[SimpleNamespace],
) -> AsyncMock:
    retrieve = AsyncMock(return_value=passages)
    monkeypatch.setattr(
        "app.services.ai.crm_assistant._help_tools.knowledge_retrieval_service.retrieve_passages",
        retrieve,
    )
    return retrieve


class TestRegistration:
    def test_tool_is_exposed_to_the_model(self) -> None:
        schemas = {tool["function"]["name"]: tool["function"] for tool in get_crm_tools()}

        assert "search_help" in schemas
        assert schemas["search_help"]["parameters"]["required"] == ["query"]
        assert schemas["search_help"]["parameters"]["additionalProperties"] is False

    @pytest.mark.asyncio
    async def test_executor_dispatches_the_tool(self) -> None:
        executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)

        assert "search_help" in executor.handlers

    def test_help_lookups_never_need_approval(self) -> None:
        from app.services.ai.crm_assistant._tool_metadata import get_tool_policy

        assert get_tool_policy("search_help").requires_approval is False


class TestSearchHelp:
    @pytest.mark.asyncio
    async def test_retrieval_is_scoped_to_workspace_level_help(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        retrieve = _patch_retrieval(monkeypatch, [_passage("Setting up an automation", "Steps.")])

        result = await tools.search_help({"query": "how do I set up an automation"})

        assert result["success"] is True
        kwargs = retrieve.await_args.kwargs
        assert kwargs["workspace_id"] == tools.context.workspace_id
        # None means "workspace-level product help", not "any agent's knowledge".
        assert kwargs["agent_id"] is None
        assert kwargs["query"] == "how do I set up an automation"
        assert kwargs["top_k"] == DEFAULT_TOP_K

    @pytest.mark.asyncio
    async def test_passages_carry_their_help_topic_title(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_retrieval(
            monkeypatch,
            [_passage("How the approval queue works", "Approve or reject.", 0.912345)],
        )

        result = await tools.search_help({"query": "how does the approval queue work"})

        assert result["data"] == [
            {
                "title": "How the approval queue works",
                "content": "Approve or reject.",
                "score": 0.9123,
            }
        ]
        assert result["total"] == 1
        assert result["has_more"] is False
        assert "only from these passages" in str(result["message"])

    @pytest.mark.asyncio
    async def test_no_match_tells_the_model_not_to_guess(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_retrieval(monkeypatch, [])

        result = await tools.search_help({"query": "how do I export to quickbooks"})

        assert result["success"] is True
        assert result["data"] == []
        assert result["total"] == 0
        assert "instead of guessing" in str(result["message"])

    @pytest.mark.asyncio
    async def test_blank_query_is_a_self_correctable_error(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        retrieve = _patch_retrieval(monkeypatch, [])

        result = await tools.search_help({"query": "   "})

        assert result["success"] is False
        assert result["code"] == "invalid_argument"
        assert result["retryable"] is True
        retrieve.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(1, 1), (3, 3), (99, MAX_TOP_K), (0, 1), (-4, 1), ("garbage", DEFAULT_TOP_K)],
    )
    async def test_top_k_is_clamped(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
        requested: object,
        expected: int,
    ) -> None:
        retrieve = _patch_retrieval(monkeypatch, [])

        await tools.search_help({"query": "quiet hours", "top_k": requested})

        assert retrieve.await_args.kwargs["top_k"] == expected
