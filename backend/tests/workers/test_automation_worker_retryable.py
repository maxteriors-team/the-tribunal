"""AutomationWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.automation_worker import AutomationWorker
from app.workers.base import BaseWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(AutomationWorker, RetryableWorker)
    assert issubclass(AutomationWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert AutomationWorker.COMPONENT_NAME == "automation_worker"
    assert AutomationWorker.max_retries == 3
    assert AutomationWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_automation_evaluation_routes_to_dlq() -> None:
    worker = AutomationWorker()
    recorder = wire_worker_for_retry_test(worker)

    automation = MagicMock(id=uuid4(), trigger_type="never_booked")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("eval failed")

    item_key = f"automation:{automation.id}"
    await worker.execute_with_retry(fail, automation, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "automation_worker"
    assert recorder.calls[0]["item_key"] == item_key
