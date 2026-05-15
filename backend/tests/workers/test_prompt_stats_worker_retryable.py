"""PromptStatsWorker — RetryableWorker contract."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.workers.base import BaseWorker
from app.workers.prompt_stats_worker import PromptStatsWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(PromptStatsWorker, RetryableWorker)
    assert issubclass(PromptStatsWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert PromptStatsWorker.COMPONENT_NAME == "prompt_stats"
    assert PromptStatsWorker.max_retries == 3
    assert PromptStatsWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_aggregation_routes_to_dlq() -> None:
    worker = PromptStatsWorker()
    recorder = wire_worker_for_retry_test(worker)

    stat_date = date(2026, 1, 1)
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("aggregate failed")

    item_key = f"aggregate:{stat_date.isoformat()}"
    await worker.execute_with_retry(fail, db, stat_date, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "prompt_stats"
    assert recorder.calls[0]["item_key"] == item_key
