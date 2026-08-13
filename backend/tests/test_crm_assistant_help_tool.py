"""Grounded product help for CRM Assistant.

These tests pin the behavior that keeps product answers honest: the tool is
registered, it searches the deployed markdown source without a seed dependency,
and unsupported questions produce an explicit no-match result.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.ai.crm_assistant._help_tools import (
    DEFAULT_TOP_K,
    MAX_TOP_K,
    HelpAssistantTools,
)
from app.services.ai.crm_assistant._processor import SYSTEM_PROMPT
from app.services.ai.crm_assistant._tool_context import CRMToolContext
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools
from app.services.knowledge.product_help import ProductHelpError


@pytest.fixture
def tools() -> HelpAssistantTools:
    context = CRMToolContext(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)
    return HelpAssistantTools(context)


class TestRegistration:
    def test_tool_is_exposed_to_the_model(self) -> None:
        schemas = {tool["function"]["name"]: tool["function"] for tool in get_crm_tools()}

        assert "search_help" in schemas
        assert schemas["search_help"]["parameters"]["required"] == ["query"]
        assert schemas["search_help"]["parameters"]["additionalProperties"] is False
        assert "exact UI labels" in schemas["search_help"]["description"]

    @pytest.mark.asyncio
    async def test_executor_dispatches_the_tool(self) -> None:
        executor = CRMToolExecutor(db=AsyncMock(), workspace_id=uuid.uuid4(), user_id=1)

        assert "search_help" in executor.handlers

    def test_help_lookups_never_need_approval(self) -> None:
        from app.services.ai.crm_assistant._tool_metadata import get_tool_policy

        assert get_tool_policy("search_help").requires_approval is False

    def test_system_prompt_requires_route_accurate_grounded_steps(self) -> None:
        assert "call search_help first" in SYSTEM_PROMPT
        assert "give numbered steps" in SYSTEM_PROMPT
        assert "exact route" in SYSTEM_PROMPT
        assert "not documented as supported" in SYSTEM_PROMPT


class TestSearchHelp:
    @pytest.mark.asyncio
    async def test_invoice_help_comes_from_bundled_source(self, tools: HelpAssistantTools) -> None:
        result = await tools.search_help({"query": "How do I create and send an invoice?"})

        assert result["success"] is True
        assert result["total"] >= 1
        first = result["data"][0]
        assert first["source"] == "docs/help/sales-quotes-and-invoices.md"
        assert first["title"].endswith("Create an invoice")
        assert "`/invoices`" in first["content"]
        assert "**New invoice**" in first["content"]
        assert "same route" in first["content"]
        assert "numbered steps" in str(result["message"])
        # Product help is shipped with the backend; no workspace seed or DB read is needed.
        tools.context.db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("question", "source", "must_include"),
        [
            (
                "Where can I see my pipeline?",
                "docs/help/sales-quotes-and-invoices.md",
                "`/opportunities`",
            ),
            (
                "How do I import contacts?",
                "docs/help/contacts-and-communications.md",
                "`/contacts`",
            ),
            (
                "How do I receive inventory stock?",
                "docs/help/operations-and-service-delivery.md",
                "`/inventory`",
            ),
            (
                "How do I add a sending phone number?",
                "docs/help/phone-numbers.md",
                "`/phone-numbers`",
            ),
            (
                "How do I set up an automation?",
                "docs/help/automations.md",
                "`/automations`",
            ),
        ],
    )
    async def test_representative_crm_questions_find_route_accurate_help(
        self,
        tools: HelpAssistantTools,
        question: str,
        source: str,
        must_include: str,
    ) -> None:
        result = await tools.search_help({"query": question})

        matches = [item for item in result["data"] if item["source"] == source]
        assert matches, result
        assert must_include in "\n".join(str(item["content"]) for item in matches)

    @pytest.mark.asyncio
    async def test_no_match_tells_the_model_not_to_guess(
        self,
        tools: HelpAssistantTools,
    ) -> None:
        result = await tools.search_help({"query": "How do I export to QuickBooks?"})

        assert result["success"] is True
        assert result["data"] == []
        assert result["total"] == 0
        assert "not documented as supported" in str(result["message"])

    @pytest.mark.asyncio
    async def test_blank_query_is_a_self_correctable_error(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        search = Mock()
        monkeypatch.setattr(
            "app.services.ai.crm_assistant._help_tools.search_help_documents",
            search,
        )

        result = await tools.search_help({"query": "   "})

        assert result["success"] is False
        assert result["code"] == "invalid_argument"
        assert result["retryable"] is True
        search.assert_not_called()

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
        search = Mock(return_value=[])
        monkeypatch.setattr(
            "app.services.ai.crm_assistant._help_tools.search_help_documents",
            search,
        )

        await tools.search_help({"query": "quiet hours", "top_k": requested})

        assert search.call_args.kwargs["top_k"] == expected

    @pytest.mark.asyncio
    async def test_missing_source_fails_without_inviting_a_guess(
        self,
        tools: HelpAssistantTools,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        search = Mock(side_effect=ProductHelpError("missing"))
        monkeypatch.setattr(
            "app.services.ai.crm_assistant._help_tools.search_help_documents",
            search,
        )

        result = await tools.search_help({"query": "How do I create an invoice?"})

        assert result == {
            "success": False,
            "error": "Product help is temporarily unavailable; do not answer from memory.",
        }
