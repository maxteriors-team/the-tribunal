"""NoshowReengagementWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
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


def test_default_day7_message_is_business_neutral() -> None:
    worker = NoshowReengagementWorker()
    contact = MagicMock(first_name="Paulina", last_name=None)

    body = worker._render_template(_DEFAULT_DAY7_TEMPLATE, contact, MagicMock())

    assert body == (
        "Hi Paulina, are you still interested in rescheduling? "
        "Reply YES and we'll help find a new time."
    )


@pytest.mark.asyncio
async def test_sweep_only_loads_active_agents() -> None:
    worker = NoshowReengagementWorker()
    agent_result = MagicMock()
    agent_result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=agent_result)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.workers.noshow_reengagement_worker.system_session",
        return_value=context,
    ):
        await worker._process_items()

    statement = db.execute.await_args.args[0]
    assert "agents.is_active IS true" in str(statement)


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
