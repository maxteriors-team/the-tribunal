"""FollowupWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.followup_worker import FollowupWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(FollowupWorker, RetryableWorker)
    assert issubclass(FollowupWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert FollowupWorker.COMPONENT_NAME == "followup_worker"
    assert FollowupWorker.max_retries == 3
    assert FollowupWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_conversation_followup_routes_to_dlq() -> None:
    worker = FollowupWorker()
    recorder = wire_worker_for_retry_test(worker)

    conversation = MagicMock(id=uuid4())
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("followup blew up")

    item_key = f"conversation:{conversation.id}"
    await worker.execute_with_retry(fail, conversation, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "followup_worker"
    assert recorder.calls[0]["item_key"] == item_key
