"""ApprovalWorker — RetryableWorker contract.

Verifies the worker inherits the retry mixin, exposes the expected
configuration, and that per-action failures route through
``execute_with_retry`` so terminal errors land in the DLQ.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.workers.approval_worker import ApprovalWorker
from app.workers.base import BaseWorker
from app.workers.retryable import RetryableWorker


def test_class_inherits_retryable_and_base() -> None:
    assert issubclass(ApprovalWorker, RetryableWorker)
    assert issubclass(ApprovalWorker, BaseWorker)


def test_retry_configuration() -> None:
    assert ApprovalWorker.COMPONENT_NAME == "approval_worker"
    assert ApprovalWorker.max_retries == 3
    assert ApprovalWorker.backoff_base_seconds == 2.0


@pytest.mark.asyncio
async def test_failed_notification_routes_to_dead_letter() -> None:
    worker = ApprovalWorker()
    worker.backoff_base_seconds = 0.0  # no sleep in tests
    worker.max_retries = 1
    worker._dlq_session_factory = lambda: _null_session_factory  # type: ignore[method-assign]
    recorder = _Recorder()
    worker._record_dead_letter = recorder  # type: ignore[method-assign]

    action = MagicMock(id=uuid4())
    db = MagicMock()
    db.rollback = AsyncMock()
    worker.delivery_service.notify_pending_action = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    await worker.execute_with_retry(
        worker._notify_pending_action,
        db,
        action,
        item_key=f"notify:{action.id}",
    )

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["worker_name"] == "approval_worker"
    assert recorder.calls[0]["item_key"] == f"notify:{action.id}"


@pytest.mark.asyncio
async def test_failed_execution_routes_to_dead_letter() -> None:
    worker = ApprovalWorker()
    worker.backoff_base_seconds = 0.0
    worker.max_retries = 1
    worker._dlq_session_factory = lambda: _null_session_factory  # type: ignore[method-assign]
    recorder = _Recorder()
    worker._record_dead_letter = recorder  # type: ignore[method-assign]

    action = MagicMock(id=uuid4())
    db = MagicMock()
    db.rollback = AsyncMock()
    worker.gate_service.execute_approved_action = AsyncMock(
        side_effect=RuntimeError("nope")
    )

    await worker.execute_with_retry(
        worker._execute_single_action,
        db,
        action,
        item_key=f"execute:{action.id}",
    )

    assert len(recorder.calls) == 1
    assert recorder.calls[0]["item_key"] == f"execute:{action.id}"


@pytest.mark.asyncio
async def test_process_items_invokes_execute_with_retry_per_action() -> None:
    """End-to-end: a queue of pending actions is iterated via the retry helper."""
    worker = ApprovalWorker()
    worker.backoff_base_seconds = 0.0
    worker.max_retries = 0

    captured: list[tuple[str, str]] = []

    async def fake_with_retry(fn, *args, item_key=None, **kwargs):  # type: ignore[no-untyped-def]
        captured.append((fn.__name__, item_key or ""))

    worker.execute_with_retry = fake_with_retry  # type: ignore[method-assign]

    pending_action = MagicMock(id=uuid4())
    approved_action = MagicMock(id=uuid4())

    db = _DbCtx(
        pending=[pending_action],
        approved=[approved_action],
    )
    factory = MagicMock(return_value=db)

    with (
        patch("app.db.session.AsyncSessionLocal", factory),
        patch.object(worker, "_handle_timeouts", AsyncMock()),
    ):
        await worker._process_items()

    names = [c[0] for c in captured]
    assert "_notify_pending_action" in names
    assert "_execute_single_action" in names


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def __call__(self, session, *, worker_name, item_key, payload, error):  # type: ignore[no-untyped-def]
        self.calls.append(
            {
                "worker_name": worker_name,
                "item_key": item_key,
                "payload": payload,
                "error": error,
            }
        )


class _NullSession:
    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, *_):  # type: ignore[no-untyped-def]
        return None


def _null_session_factory() -> _NullSession:
    return _NullSession()


class _DbCtx:
    """Mimics ``async with AsyncSessionLocal() as db`` with canned queries.

    Returns ``pending`` actions for the pending-notification query and
    ``approved`` actions for the approved-execution query, by call order.
    """

    def __init__(self, pending: list[object], approved: list[object]) -> None:
        self._queue = [pending, approved]

    async def __aenter__(self) -> _DbCtx:
        return self

    async def __aexit__(self, *_):  # type: ignore[no-untyped-def]
        return None

    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        rows = self._queue.pop(0) if self._queue else []
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result
