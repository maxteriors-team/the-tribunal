"""NoshowReengagementWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.noshow_reengagement_worker import (
    _DEFAULT_DAY7_TEMPLATE,
    NoshowReengagementWorker,
)
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(NoshowReengagementWorker, RetryableWorker)
    assert issubclass(NoshowReengagementWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert NoshowReengagementWorker.COMPONENT_NAME == "noshow_reengagement_worker"
    assert NoshowReengagementWorker.max_retries == 3
    assert NoshowReengagementWorker.backoff_base_seconds == 2.0


def test_default_day7_message_has_actionable_booking_cta() -> None:
    worker = NoshowReengagementWorker()
    contact = MagicMock(first_name="Paulina", last_name=None)

    body = worker._render_template(_DEFAULT_DAY7_TEMPLATE, contact, MagicMock())

    assert body == (
        "Hi Paulina, we're offering 300 free video ads to qualified businesses. "
        "Still interested? Reply YES and we'll get you booked."
    )


@pytest.mark.parametrize("placeholder", ["reschedule_link", "booking_link"])
def test_legacy_booking_placeholder_prompts_for_reply(placeholder: str) -> None:
    worker = NoshowReengagementWorker()
    contact = MagicMock(first_name="Paulina", last_name=None)

    body = worker._render_template(
        f"Hi {{first_name}}, book here: {{{placeholder}}}", contact, MagicMock()
    )

    assert body == "Hi Paulina, book here: Reply YES"


@pytest.mark.asyncio
async def test_failed_agent_processing_routes_to_dlq() -> None:
    worker = NoshowReengagementWorker()
    recorder = wire_worker_for_retry_test(worker)

    agent = MagicMock(id=uuid4())
    db = MagicMock()

    async def fail(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("agent blew up")

    item_key = f"agent:{agent.id}"
    await worker.execute_with_retry(fail, agent, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "noshow_reengagement_worker"
    assert recorder.calls[0]["item_key"] == item_key
