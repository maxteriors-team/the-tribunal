"""Tests for the transcript analysis worker."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers import transcript_analysis_worker as worker_module


def _fake_session(messages: list[MagicMock]) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = messages

    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    session.__ctx__ = ctx
    return session


@pytest.mark.asyncio
async def test_worker_analyzes_unanalyzed_messages() -> None:
    outcome = SimpleNamespace(
        id="outcome-1",
        workspace_id="workspace-1",
        outcome_type="completed",
        signals={"duration_seconds": 42},
    )
    msg = MagicMock()
    msg.id = "msg-1"
    msg.transcript = "Hello, I want to book an appointment."
    msg.call_outcome = outcome
    msg.conversation = SimpleNamespace(workspace_id="workspace-1")

    session = _fake_session([msg])

    analysis_payload = {
        "sentiment": "positive",
        "sentiment_score": 0.7,
        "intents": ["book"],
        "topics": ["scheduling"],
        "summary": "Wants appointment",
        "objections": [],
        "next_steps": ["confirm time"],
    }

    fake_sessionmaker = MagicMock(return_value=session.__ctx__)

    with (
        patch.object(worker_module, "AsyncSessionLocal", fake_sessionmaker),
        patch.object(
            worker_module,
            "analyze_transcript",
            AsyncMock(return_value=analysis_payload),
        ) as mocked_analyze,
        patch.object(
            worker_module,
            "refresh_contact_ai_memory_from_voice_analysis",
            AsyncMock(return_value=True),
        ) as refresh_memory,
    ):
        worker = worker_module.TranscriptAnalysisWorker()
        await worker._process_items()

    mocked_analyze.assert_awaited_once_with(msg.transcript)
    refresh_memory.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        message_id=msg.id,
        analysis={**analysis_payload, "call_outcome": "completed"},
        provenance_event_id="call-outcome:outcome-1",
    )
    assert outcome.signals["sentiment"] == "positive"
    assert outcome.signals["analyzed"] is True
    assert outcome.signals["duration_seconds"] == 42
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_marks_errors_without_infinite_retry() -> None:
    outcome = SimpleNamespace(id="outcome-err", outcome_type="failed", signals={})
    msg = MagicMock()
    msg.id = "msg-err"
    msg.transcript = "garbled"
    msg.call_outcome = outcome
    msg.conversation = SimpleNamespace(workspace_id="workspace-1")

    session = _fake_session([msg])
    fake_sessionmaker = MagicMock(return_value=session.__ctx__)

    with (
        patch.object(worker_module, "AsyncSessionLocal", fake_sessionmaker),
        patch.object(
            worker_module,
            "analyze_transcript",
            AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch.object(
            worker_module,
            "refresh_contact_ai_memory_from_voice_analysis",
            AsyncMock(return_value=True),
        ) as refresh_memory,
    ):
        worker = worker_module.TranscriptAnalysisWorker()
        await worker._process_items()

    assert outcome.signals["analyzed"] == "error"
    refresh_memory.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        message_id=msg.id,
        analysis={"call_outcome": "failed"},
        provenance_event_id="call-outcome:outcome-err",
    )
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_noop_on_empty_queue() -> None:
    session = _fake_session([])
    fake_sessionmaker = MagicMock(return_value=session.__ctx__)

    with (
        patch.object(worker_module, "AsyncSessionLocal", fake_sessionmaker),
        patch.object(worker_module, "analyze_transcript", AsyncMock()) as mocked_analyze,
    ):
        worker = worker_module.TranscriptAnalysisWorker()
        await worker._process_items()

    mocked_analyze.assert_not_awaited()
    session.commit.assert_not_awaited()
