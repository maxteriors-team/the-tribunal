"""ReputationWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.reputation_worker import ReputationWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(ReputationWorker, RetryableWorker)
    assert issubclass(ReputationWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert ReputationWorker.COMPONENT_NAME == "reputation_worker"
    assert ReputationWorker.max_retries == 3
    assert ReputationWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_phone_update_routes_to_dlq() -> None:
    worker = ReputationWorker()
    recorder = wire_worker_for_retry_test(worker)

    phone = MagicMock(id=uuid4())
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("reputation update failed")

    item_key = f"phone:{phone.id}"
    await worker.execute_with_retry(fail, phone, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "reputation_worker"
    assert recorder.calls[0]["item_key"] == item_key
