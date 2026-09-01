"""Tests for persistent cross-call caller memory.

Covers the two halves of :mod:`app.services.ai.caller_memory_service`:

* **Write** — transcript flattening, LLM summarization (mocked), and embedded
  storage of a :class:`CallerMemory` (deterministic fake embedder).
* **Read** — returning-caller detection (prior calls and/or stored memories),
  memory retrieval (semantic vs recency), and the returning-caller recap text.

No live database: sessions are faked and embeddings/LLM calls are stubbed, so
these lock the logic + scoping without a pgvector instance.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ai import caller_memory_service as svc
from app.services.ai.caller_memory_service import (
    CallerMemoryEntry,
    ReturningCallerInfo,
    _transcript_to_text,
    build_returning_caller_summary,
    detect_returning_caller,
    retrieve_caller_memories,
    store_caller_memory,
)
from app.services.ai.embeddings import EmbeddingResult

WORKSPACE_ID = uuid.uuid4()
CONTACT_ID = 4242


async def _fake_embedder(texts: list[str]) -> EmbeddingResult:
    """Deterministic embedder: one fixed 1536-dim vector per input text."""
    return EmbeddingResult(ok=True, embeddings=[[0.1] * 1536 for _ in texts])


async def _failing_embedder(texts: list[str]) -> EmbeddingResult:
    return EmbeddingResult(ok=False, error="boom")


# --------------------------------------------------------------------------- #
# Fake async session
# --------------------------------------------------------------------------- #
class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def one(self) -> Any:
        return self._rows[0]

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self


class _FakeSession:
    """Returns queued results in order; records added objects."""

    def __init__(self, results: list[_Result]) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.flushed = False

    async def execute(self, _stmt: Any) -> _Result:
        self.statements.append(_stmt)
        if not self._results:
            return _Result([])
        return self._results.pop(0)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed = True


# --------------------------------------------------------------------------- #
# Transcript flattening
# --------------------------------------------------------------------------- #
class TestTranscriptToText:
    def test_flattens_roles_to_speakers(self) -> None:
        transcript = '[{"role": "user", "text": "Hi"}, {"role": "agent", "text": "Hello!"}]'
        assert _transcript_to_text(transcript) == "Caller: Hi\nAgent: Hello!"

    def test_empty_and_malformed_return_empty(self) -> None:
        assert _transcript_to_text(None) == ""
        assert _transcript_to_text("") == ""
        assert _transcript_to_text("not json") == ""
        assert _transcript_to_text('{"role": "user"}') == ""  # not a list

    def test_skips_blank_entries(self) -> None:
        transcript = '[{"role": "user", "text": ""}, {"role": "agent", "text": "Ok"}]'
        assert _transcript_to_text(transcript) == "Agent: Ok"


# --------------------------------------------------------------------------- #
# Summarization (LLM mocked)
# --------------------------------------------------------------------------- #
class TestSummarize:
    @pytest.mark.asyncio
    async def test_returns_none_for_empty_input(self) -> None:
        assert await svc.summarize_call_transcript("   ") is None

    @pytest.mark.asyncio
    async def test_summarizes_and_truncates(self) -> None:
        long_summary = "x" * 5000
        message = SimpleNamespace(content=long_summary)
        choice = SimpleNamespace(message=message)
        completion = SimpleNamespace(choices=[choice])
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=completion))
            )
        )
        # create_openai_client is imported lazily inside the function; patch the
        # real import target so the fake client is used.
        with patch(
            "app.services.ai.openai_credentials.create_openai_client",
            return_value=client,
        ):
            out = await svc.summarize_call_transcript(
                "Caller: I want a quote.", agent_name="Ara", contact_name="Sam"
            )
        assert out is not None
        assert len(out) <= svc._MAX_SUMMARY_CHARS

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self) -> None:
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(side_effect=RuntimeError("x")))
            )
        )
        with patch(
            "app.services.ai.openai_credentials.create_openai_client",
            return_value=client,
        ):
            assert await svc.summarize_call_transcript("Caller: hello") is None


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
class TestStore:
    @pytest.mark.asyncio
    async def test_stores_embedded_memory(self) -> None:
        session = _FakeSession([])
        ok = await store_caller_memory(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            summary="Caller asked about pricing.",
            message_id=uuid.uuid4(),
            direction="inbound",
            embedder=_fake_embedder,
        )
        assert ok is True
        assert session.flushed is True
        assert len(session.added) == 1
        memory = session.added[0]
        assert memory.workspace_id == WORKSPACE_ID
        assert memory.contact_id == CONTACT_ID
        assert memory.direction == "inbound"
        assert len(memory.embedding) == 1536

    @pytest.mark.asyncio
    async def test_empty_summary_not_stored(self) -> None:
        session = _FakeSession([])
        ok = await store_caller_memory(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            summary="   ",
            embedder=_fake_embedder,
        )
        assert ok is False
        assert session.added == []

    @pytest.mark.asyncio
    async def test_embed_failure_not_stored(self) -> None:
        session = _FakeSession([])
        ok = await store_caller_memory(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            summary="Real summary.",
            embedder=_failing_embedder,
        )
        assert ok is False
        assert session.added == []


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #
class TestRetrieve:
    @pytest.mark.asyncio
    async def test_recency_path_when_no_query(self) -> None:
        now = datetime.now(UTC)
        rows = [
            SimpleNamespace(summary="Newest call", occurred_at=now, direction="inbound"),
            SimpleNamespace(
                summary="Older call", occurred_at=now - timedelta(days=2), direction="outbound"
            ),
        ]
        session = _FakeSession([_Result(rows)])
        embedder = AsyncMock(side_effect=_fake_embedder)

        entries = await retrieve_caller_memories(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            embedder=embedder,
            now=now,
        )
        assert [e.summary for e in entries] == ["Newest call", "Older call"]
        embedder.assert_not_called()  # no query -> no embedding spend
        params = session.statements[0].compile().params
        assert WORKSPACE_ID in params.values()
        assert CONTACT_ID in params.values()
        assert any(value == now - timedelta(days=90) for value in params.values())

    @pytest.mark.asyncio
    async def test_semantic_path_embeds_query(self) -> None:
        rows = [
            SimpleNamespace(summary="Pricing chat", occurred_at=datetime.now(UTC), direction=None)
        ]
        session = _FakeSession([_Result(rows)])
        embedder = AsyncMock(side_effect=_fake_embedder)

        entries = await retrieve_caller_memories(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            query="what did we discuss about price",
            embedder=embedder,
        )
        assert [e.summary for e in entries] == ["Pricing chat"]
        embedder.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zero_limit_returns_empty(self) -> None:
        session = _FakeSession([])
        entries = await retrieve_caller_memories(
            session, workspace_id=WORKSPACE_ID, contact_id=CONTACT_ID, limit=0
        )
        assert entries == []


# --------------------------------------------------------------------------- #
# Returning-caller detection
# --------------------------------------------------------------------------- #
class TestDetect:
    @pytest.mark.asyncio
    async def test_returning_when_prior_calls_exist(self) -> None:
        last = datetime.now(UTC) - timedelta(days=1)
        # 1st execute: (count, max_created_at); 2nd execute: memory rows.
        session = _FakeSession([_Result([(3, last)]), _Result([])])
        info = await detect_returning_caller(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            embedder=_fake_embedder,
        )
        assert info.is_returning is True
        assert info.prior_call_count == 3
        assert info.last_interaction_at == last

    @pytest.mark.asyncio
    async def test_returning_when_only_memories_exist(self) -> None:
        mem_row = SimpleNamespace(
            summary="Discussed a refund.", occurred_at=datetime.now(UTC), direction="inbound"
        )
        session = _FakeSession([_Result([(0, None)]), _Result([mem_row])])
        info = await detect_returning_caller(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            embedder=_fake_embedder,
        )
        assert info.is_returning is True
        assert info.prior_call_count == 0
        assert len(info.memories) == 1

    @pytest.mark.asyncio
    async def test_not_returning_for_new_caller(self) -> None:
        session = _FakeSession([_Result([(0, None)]), _Result([])])
        info = await detect_returning_caller(
            session,
            workspace_id=WORKSPACE_ID,
            contact_id=CONTACT_ID,
            embedder=_fake_embedder,
        )
        assert info.is_returning is False
        assert info.prior_call_count == 0
        assert info.memories == []


# --------------------------------------------------------------------------- #
# Returning-caller recap text
# --------------------------------------------------------------------------- #
class TestSummaryText:
    def test_none_for_new_caller(self) -> None:
        assert build_returning_caller_summary(ReturningCallerInfo(is_returning=False)) is None

    def test_recap_includes_counts_and_memories(self) -> None:
        info = ReturningCallerInfo(
            is_returning=True,
            prior_call_count=2,
            last_interaction_at=datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
            memories=[
                CallerMemoryEntry(
                    summary="Asked about pricing for the premium plan.",
                    occurred_at=datetime(2026, 6, 1, 15, 0, tzinfo=UTC),
                    direction="inbound",
                )
            ],
        )
        # `now` is pinned because the recap drops memories older than
        # MAX_CALLER_MEMORY_AGE_DAYS (90). Against the real clock this test
        # asserted "fresh memory is included" using a fixed 2026-06-01 date, so
        # it silently became an assertion about a *stale* memory 90 days later
        # and started failing on 2026-08-30. The staleness path is covered
        # separately by test_stale_voice_summary_is_omitted_from_live_call_context.
        text = build_returning_caller_summary(
            info,
            timezone="America/New_York",
            now=datetime(2026, 6, 2, 15, 0, tzinfo=UTC),
        )
        assert text is not None
        assert "Returning Caller" in text
        assert "Prior completed calls: 2" in text
        assert "pricing for the premium plan" in text
        assert "source=voice_summary:unknown" in text
        assert "freshness=" in text

    def test_stale_voice_summary_is_omitted_from_live_call_context(self) -> None:
        info = ReturningCallerInfo(
            is_returning=True,
            prior_call_count=1,
            last_interaction_at=datetime(2025, 1, 1, tzinfo=UTC),
            memories=[
                CallerMemoryEntry(
                    summary="The unpaid invoice was definitely cancelled.",
                    occurred_at=datetime(2025, 1, 1, tzinfo=UTC),
                    direction="inbound",
                )
            ],
        )

        text = build_returning_caller_summary(info, now=datetime(2026, 8, 17, tzinfo=UTC))

        assert text is not None
        assert "unpaid invoice was definitely cancelled" not in text
        assert "Prior completed call: 1" in text
        assert "freshness=historical" in text
