"""NeverBookedWorker — RetryableWorker contract."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.base import BaseWorker
from app.workers.never_booked_worker import (
    _DEFAULT_NEVER_BOOKED_TEMPLATE,
    NeverBookedWorker,
)
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(NeverBookedWorker, RetryableWorker)
    assert issubclass(NeverBookedWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert NeverBookedWorker.COMPONENT_NAME == "never_booked_worker"
    assert NeverBookedWorker.max_retries == 3
    assert NeverBookedWorker.backoff_base_seconds == 2.0


def test_default_message_is_business_neutral() -> None:
    worker = NeverBookedWorker()
    contact = MagicMock(first_name="Paulina", last_name=None)

    body = worker._render_template(_DEFAULT_NEVER_BOOKED_TEMPLATE, contact, MagicMock())

    assert body == (
        "Hi Paulina, are you still interested in learning more? "
        "Reply YES and we'll help with next steps."
    )


@pytest.mark.asyncio
async def test_sweep_only_loads_active_agents() -> None:
    worker = NeverBookedWorker()
    agent_result = MagicMock()
    agent_result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=agent_result)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=None)

    with patch(
        "app.workers.never_booked_worker.system_session",
        return_value=context,
    ):
        await worker._process_items()

    statement = db.execute.await_args.args[0]
    assert "agents.is_active IS true" in str(statement)


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
    await worker.execute_with_retry(fail, contact, agent, db, item_key=item_key)

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "never_booked_worker"
    assert recorder.calls[0]["item_key"] == item_key
