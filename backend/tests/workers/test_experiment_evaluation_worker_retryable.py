"""ExperimentEvaluationWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.experiment_evaluation_worker import ExperimentEvaluationWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(ExperimentEvaluationWorker, RetryableWorker)
    assert issubclass(ExperimentEvaluationWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert ExperimentEvaluationWorker.COMPONENT_NAME == "experiment_evaluation"
    assert ExperimentEvaluationWorker.max_retries == 3
    assert ExperimentEvaluationWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_agent_evaluation_routes_to_dlq() -> None:
    worker = ExperimentEvaluationWorker()
    recorder = wire_worker_for_retry_test(worker)

    agent = MagicMock(id=uuid4(), name="agent-x")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("eval failed")

    item_key = f"agent:{agent.id}"
    await worker.execute_with_retry(fail, db, agent, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "experiment_evaluation"
    assert recorder.calls[0]["item_key"] == item_key
