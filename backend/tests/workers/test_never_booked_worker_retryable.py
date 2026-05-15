"""NeverBookedWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.never_booked_worker import NeverBookedWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(NeverBookedWorker, RetryableWorker)
    assert issubclass(NeverBookedWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert NeverBookedWorker.COMPONENT_NAME == "never_booked_worker"
    assert NeverBookedWorker.max_retries == 3
    assert NeverBookedWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_reengagement_routes_to_dlq() -> None:
    worker = NeverBookedWorker()
    recorder = wire_worker_for_retry_test(worker)

    contact = MagicMock(id=7)
    agent = MagicMock(id=uuid4())
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("send failed")

    item_key = f"never_booked:{agent.id}:contact:{contact.id}"
    await worker.execute_with_retry(
        fail, contact, agent, db, item_key=item_key
    )

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "never_booked_worker"
    assert recorder.calls[0]["item_key"] == item_key
