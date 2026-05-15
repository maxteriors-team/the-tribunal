"""PromptImprovementWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.prompt_improvement_worker import PromptImprovementWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(PromptImprovementWorker, RetryableWorker)
    assert issubclass(PromptImprovementWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert PromptImprovementWorker.COMPONENT_NAME == "prompt_improvement"
    assert PromptImprovementWorker.max_retries == 3
    assert PromptImprovementWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_agent_improvement_routes_to_dlq() -> None:
    worker = PromptImprovementWorker()
    recorder = wire_worker_for_retry_test(worker)

    agent = MagicMock(id=uuid4(), name="agent-x")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("improve failed")

    item_key = f"agent:{agent.id}"
    await worker.execute_with_retry(fail, db, agent, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "prompt_improvement"
    assert recorder.calls[0]["item_key"] == item_key
