"""Tests for the shared ``search_knowledge`` tool executor.

Covers the channel-agnostic contract used by both the voice and text agents:
empty-query rejection, ``top_k`` clamping, the no-results message, and the
citation-friendly passage shape (title + content + score).
"""

from __future__ import annotations

import uuid

import pytest

from app.services.knowledge import search_tool
from app.services.knowledge.retrieval_service import RetrievedPassage
from app.services.knowledge.search_tool import (
    MAX_TOP_K,
    _clamp_top_k,
    execute_knowledge_search,
)


class _RecordingRetriever:
    """Stand-in for ``knowledge_retrieval_service`` capturing call args."""

    def __init__(self, passages: list[RetrievedPassage]) -> None:
        self._passages = passages
        self.calls: list[dict[str, object]] = []

    async def retrieve_passages(
        self,
        db: object,
        *,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        query: str,
        top_k: int | None = None,
    ) -> list[RetrievedPassage]:
        self.calls.append(
            {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "query": query,
                "top_k": top_k,
            }
        )
        return self._passages


def _passage(title: str, content: str, score: float) -> RetrievedPassage:
    return RetrievedPassage(
        document_id=uuid.uuid5(uuid.NAMESPACE_OID, title),
        title=title,
        content=content,
        score=score,
        ordinal=0,
    )


class TestClampTopK:
    def test_default_when_none(self) -> None:
        assert _clamp_top_k(None) == 5

    def test_floor_and_ceiling(self) -> None:
        assert _clamp_top_k(0) == 1
        assert _clamp_top_k(-3) == 1
        assert _clamp_top_k(999) == MAX_TOP_K

    def test_passthrough_and_bad_input(self) -> None:
        assert _clamp_top_k(3) == 3
        assert _clamp_top_k("not-an-int") == 5  # type: ignore[arg-type]


class TestExecuteKnowledgeSearch:
    @pytest.mark.asyncio
    async def test_empty_query_rejected_without_retrieval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        retriever = _RecordingRetriever([])
        monkeypatch.setattr(search_tool, "knowledge_retrieval_service", retriever)

        out = await execute_knowledge_search(
            db=object(),
            workspace_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            query="   ",
        )
        assert out["success"] is False
        assert retriever.calls == []

    @pytest.mark.asyncio
    async def test_no_passages_returns_guidance_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        retriever = _RecordingRetriever([])
        monkeypatch.setattr(search_tool, "knowledge_retrieval_service", retriever)

        out = await execute_knowledge_search(
            db=object(),
            workspace_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            query="refund policy",
        )
        assert out["success"] is True
        assert out["passages"] == []
        assert "knowledge base" in str(out["message"]).lower()

    @pytest.mark.asyncio
    async def test_passages_formatted_with_titles_and_scores(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        retriever = _RecordingRetriever(
            [
                _passage("Pricing", "Plans start at $49/mo.", 0.812345),
                _passage("Refund Policy", "30-day money back.", 0.51),
            ]
        )
        monkeypatch.setattr(search_tool, "knowledge_retrieval_service", retriever)

        ws, agent = uuid.uuid4(), uuid.uuid4()
        out = await execute_knowledge_search(
            db=object(),
            workspace_id=ws,
            agent_id=agent,
            query="how much does it cost",
            top_k=2,
        )
        assert out["success"] is True
        passages = out["passages"]
        assert isinstance(passages, list)
        assert passages[0] == {
            "title": "Pricing",
            "content": "Plans start at $49/mo.",
            "score": 0.8123,
        }
        assert passages[1]["title"] == "Refund Policy"
        # Scoping + trimmed query forwarded to the retriever.
        assert retriever.calls[0]["workspace_id"] == ws
        assert retriever.calls[0]["agent_id"] == agent
        assert retriever.calls[0]["query"] == "how much does it cost"
        assert retriever.calls[0]["top_k"] == 2

    @pytest.mark.asyncio
    async def test_top_k_clamped_before_retrieval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        retriever = _RecordingRetriever([])
        monkeypatch.setattr(search_tool, "knowledge_retrieval_service", retriever)

        await execute_knowledge_search(
            db=object(),
            workspace_id=uuid.uuid4(),
            agent_id=uuid.uuid4(),
            query="anything",
            top_k=500,
        )
        assert retriever.calls[0]["top_k"] == MAX_TOP_K
