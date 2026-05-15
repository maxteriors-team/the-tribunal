"""ReminderWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.workers.base import BaseWorker
from app.workers.reminder_worker import ReminderWorker
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(ReminderWorker, RetryableWorker)
    assert issubclass(ReminderWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert ReminderWorker.COMPONENT_NAME == "reminder_worker"
    assert ReminderWorker.max_retries == 3
    assert ReminderWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_reminder_send_routes_to_dlq() -> None:
    worker = ReminderWorker()
    recorder = wire_worker_for_retry_test(worker)

    appt = MagicMock(id=99)
    db = MagicMock()
    offset = 1440

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("send failed")

    item_key = f"reminder:{appt.id}:offset:{offset}"
    await worker.execute_with_retry(fail, appt, offset, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "reminder_worker"
    assert recorder.calls[0]["item_key"] == item_key


@pytest.mark.asyncio
async def test_failed_vr_send_routes_to_dlq() -> None:
    worker = ReminderWorker()
    recorder = wire_worker_for_retry_test(worker)

    appt = MagicMock(id=101)
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("vr send failed")

    item_key = f"vr:{appt.id}"
    await worker.execute_with_retry(fail, appt, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["item_key"] == item_key
