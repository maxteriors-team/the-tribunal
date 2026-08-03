"""ApprovalWorker — an undeliverable action must not wedge the tick forever.

Two coupled defects produced ~38k retries on a single month-old action in dev:

1. ``_handle_timeouts`` ran last, so a raise from the notification phase meant
   expired actions were never auto-rejected.
2. Still-``pending`` expired actions were therefore re-notified on every 30s
   tick, each burning the full retry backoff.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.pending_action import PendingAction
from app.workers.approval_worker import ApprovalWorker


class _CapturingSession:
    """Captures the statements issued so filters can be asserted on."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.statements: list[Any] = []
        self._rows = rows or []
        self.rollback = AsyncMock()
        self.commit = AsyncMock()

    async def __aenter__(self) -> _CapturingSession:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = self._rows
        return result


def _worker() -> ApprovalWorker:
    worker = ApprovalWorker()
    worker.max_retries = 0
    worker.backoff_base_seconds = 0.0
    worker._dead_letter = AsyncMock()
    return worker


async def test_expired_actions_are_not_notified() -> None:
    """The notification query filters on ``expires_at``, so timed-out requests
    fall through to rejection instead of being retried forever."""
    worker = _worker()
    db = _CapturingSession()

    await worker._send_pending_notifications(db)  # type: ignore[arg-type]

    compiled = str(db.statements[0].compile(compile_kwargs={"literal_binds": False}))
    assert "expires_at IS NULL" in compiled
    assert "expires_at >" in compiled
    # Ids only — never ORM entities, which a rollback would expire.
    assert db.statements[0].selected_columns.keys() == ["id"]


async def test_timeouts_run_even_when_notification_phase_fails() -> None:
    """A raising phase is logged and isolated; later phases still run."""
    worker = _worker()
    db = _CapturingSession()
    order: list[str] = []

    async def failing_notifications(_db: Any) -> None:
        order.append("notify")
        raise RuntimeError("no from_number configured")

    async def record_execute(_db: Any) -> None:
        order.append("execute")

    async def record_timeouts(_db: Any) -> None:
        order.append("timeouts")

    worker._send_pending_notifications = failing_notifications  # type: ignore[method-assign]
    worker._execute_approved_actions = record_execute  # type: ignore[method-assign]
    worker._handle_timeouts = record_timeouts  # type: ignore[method-assign]

    with patch("app.db.session.AsyncSessionLocal", MagicMock(return_value=db)):
        await worker._process_items()

    assert order == ["notify", "execute", "timeouts"]
    # The failed phase left the session clean for the phases behind it.
    db.rollback.assert_awaited_once()


async def test_expired_pending_action_is_rejected_by_timeouts() -> None:
    """The cleanup phase moves the action out of ``pending`` for good."""
    worker = _worker()
    now = datetime.now(UTC)
    action = PendingAction(
        id=uuid4(),
        workspace_id=uuid4(),
        agent_id=None,
        status="pending",
        expires_at=now - timedelta(days=1),
        created_at=now - timedelta(days=2),
    )

    db = MagicMock()
    db.commit = AsyncMock()
    results = [_scalars([]), _scalars([action])]
    db.execute = AsyncMock(side_effect=results)

    await worker._handle_timeouts(db)

    assert action.status == "rejected"
    assert action.review_channel == "timeout"
    db.commit.assert_awaited_once()


def _scalars(rows: list[Any]) -> Any:
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    return result
