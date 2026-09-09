"""AutomationWorker — one undeliverable event must not wedge the queue forever.

A ``job_completed`` event sat ``pending`` in production from 2026-09-08 because
the SMS it triggered hit an ``uq_conversation_phones`` violation. Events drain
oldest-first through one shared session, so that single row:

1. poisoned the session, failing every event behind it in the same batch, and
2. was re-selected first on every subsequent cycle, because a terminal failure
   left it ``pending``.

Two website leads queued behind it went untexted for hours. The drain must
retire an event that exhausts its retries and keep going.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.automation_event import EVENT_STATUS_PENDING, AutomationEvent
from app.workers.automation_worker import AutomationWorker

pytestmark = pytest.mark.asyncio


class _BatchSession:
    """Returns a fixed batch of events, and records rollbacks."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.rollback = AsyncMock()
        self.commit = AsyncMock()
        self.info: dict[str, object] = {}

    async def execute(self, _statement: Any) -> Any:
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._rows
        return result


def _event() -> AutomationEvent:
    return AutomationEvent(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        event_type="lead_created",
        payload={},
        status=EVENT_STATUS_PENDING,
    )


def _worker() -> AutomationWorker:
    worker = AutomationWorker()
    worker.max_retries = 0
    worker.backoff_base_seconds = 0.0
    worker._dead_letter = AsyncMock()  # type: ignore[method-assign]
    worker._retire_failed_event = AsyncMock()  # type: ignore[method-assign]
    return worker


async def test_failed_event_is_retired_and_batch_continues() -> None:
    """The poisoned event is retired; the leads queued behind it still run."""
    poisoned, lead_a, lead_b = _event(), _event(), _event()
    worker = _worker()
    db = _BatchSession([poisoned, lead_a, lead_b])
    handled: list[uuid.UUID] = []

    async def _process(event: AutomationEvent, _db: Any) -> bool:
        if event.id == poisoned.id:
            raise RuntimeError("uq_conversation_phones")
        handled.append(event.id)
        return True

    worker._process_event = _process  # type: ignore[method-assign]

    await worker._process_events(db)  # type: ignore[arg-type]

    # The bad event is taken out of the queue instead of left pending.
    worker._retire_failed_event.assert_awaited_once_with(poisoned.id)  # type: ignore[attr-defined]
    # The session is reset, or every event behind it fails on a dead transaction.
    db.rollback.assert_awaited()
    # And the leads behind it are still delivered.
    assert handled == [lead_a.id, lead_b.id]


async def test_successful_events_are_not_retired() -> None:
    """A clean batch retires nothing and never rolls back."""
    worker = _worker()
    db = _BatchSession([_event(), _event()])

    async def _process(_event_row: AutomationEvent, _db: Any) -> bool:
        return True

    worker._process_event = _process  # type: ignore[method-assign]

    await worker._process_events(db)  # type: ignore[arg-type]

    worker._retire_failed_event.assert_not_awaited()  # type: ignore[attr-defined]
    db.rollback.assert_not_awaited()
