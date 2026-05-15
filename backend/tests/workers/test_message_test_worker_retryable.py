"""MessageTestWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.message_test_worker import MessageTestWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(MessageTestWorker, RetryableWorker)
    assert issubclass(MessageTestWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert MessageTestWorker.COMPONENT_NAME == "message_test_worker"
    assert MessageTestWorker.max_retries == 3
    assert MessageTestWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_test_routes_to_dlq() -> None:
    worker = MessageTestWorker()
    recorder = wire_worker_for_retry_test(worker)

    test = MagicMock(id=uuid4(), name="A/B test")
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("test blew up")

    item_key = f"message_test:{test.id}"
    await worker.execute_with_retry(fail, test, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "message_test_worker"
    assert recorder.calls[0]["item_key"] == item_key
