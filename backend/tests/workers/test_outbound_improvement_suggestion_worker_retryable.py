"""OutboundImprovementSuggestionWorker — RetryableWorker contract."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.outbound_improvement_suggestion_worker import OutboundImprovementSuggestionWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(OutboundImprovementSuggestionWorker, RetryableWorker)
    assert issubclass(OutboundImprovementSuggestionWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert OutboundImprovementSuggestionWorker.COMPONENT_NAME == "outbound_improvement_suggestions"
    assert OutboundImprovementSuggestionWorker.max_retries == 3
    assert OutboundImprovementSuggestionWorker.backoff_base_seconds == 2.0


def test_weekly_generation_runs_only_on_monday() -> None:
    assert OutboundImprovementSuggestionWorker._should_process_weekly(date(2026, 5, 18)) is True
    assert OutboundImprovementSuggestionWorker._should_process_weekly(date(2026, 5, 19)) is False


@pytest.mark.asyncio
async def test_failed_workspace_processing_routes_to_dlq() -> None:
    worker = OutboundImprovementSuggestionWorker()
    recorder = wire_worker_for_retry_test(worker)

    workspace_id = uuid4()
    db = MagicMock()
    today = date(2026, 5, 20)

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("suggestion failed")

    item_key = f"workspace:{workspace_id}:daily:{today.isoformat()}"
    await worker.execute_with_retry(fail, db, workspace_id, "daily", today, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "outbound_improvement_suggestions"
    assert recorder.calls[0]["item_key"] == item_key
