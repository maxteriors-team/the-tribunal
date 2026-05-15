"""TranscriptAnalysisWorker — RetryableWorker contract.

The existing ``test_transcript_analysis_worker.py`` still pins down the
batch processing behavior; this file covers the retry/DLQ contract that
the worker gained when it adopted ``RetryableWorker``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.workers.base import BaseWorker
from app.workers.retryable import RetryableWorker
from app.workers.transcript_analysis_worker import TranscriptAnalysisWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(TranscriptAnalysisWorker, RetryableWorker)
    assert issubclass(TranscriptAnalysisWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert (
        TranscriptAnalysisWorker.COMPONENT_NAME == "transcript_analysis_worker"
    )
    assert TranscriptAnalysisWorker.max_retries == 3
    assert TranscriptAnalysisWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_batch_routes_to_dlq() -> None:
    worker = TranscriptAnalysisWorker()
    recorder = wire_worker_for_retry_test(worker)

    with patch.object(
        worker,
        "_process_batch",
        AsyncMock(side_effect=RuntimeError("batch blew up")),
    ):
        await worker._process_items()

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "transcript_analysis_worker"
    assert recorder.calls[0]["item_key"] == "transcript_batch"


@pytest.mark.asyncio
async def test_successful_batch_does_not_touch_dlq() -> None:
    worker = TranscriptAnalysisWorker()
    recorder = wire_worker_for_retry_test(worker)

    with patch.object(
        worker, "_process_batch", AsyncMock(return_value=None)
    ) as batch:
        await worker._process_items()
        batch.assert_awaited_once()

    assert recorder.calls == []
