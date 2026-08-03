"""``RetryableWorker`` must hand live ORM rows to each retry attempt.

Regression cover for the failure mode that produced misleading dead-letter
rows across several workers: ``execute_with_retry`` rolls the caller's session
back between attempts, which *expires every ORM instance in that session*. The
next attribute touch on a passed-in row — even its primary key — emits a lazy
refresh ``SELECT`` that raises ``MissingGreenlet`` under the async engine, so
the retry never retried the real work and the DLQ recorded a greenlet error
instead of the actual failure.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, make_transient_to_detached

from app.models.workspace import Workspace
from app.workers.retryable import RetryableWorker
from tests.workers._retryable_helpers import wire_worker_for_retry_test


class _Worker(RetryableWorker):
    COMPONENT_NAME = "revival_test_worker"

    def __init__(self) -> None:
        self.logger = MagicMock()


@pytest.fixture
def persistent_workspace() -> Iterator[Workspace]:
    """A genuinely *persistent* ORM instance, without touching a database.

    The owning ``Session`` is held for the whole test on purpose. If it is
    allowed to be garbage-collected the instance silently degrades to
    *detached* — a different state, which the code under test is supposed to
    skip — and the test becomes order-dependent rather than meaningful.
    """
    owner = Session()
    workspace = Workspace(id=uuid.uuid4(), name="Acme", slug="acme")
    make_transient_to_detached(workspace)
    owner.add(workspace)
    try:
        yield workspace
    finally:
        owner.close()


def _fake_session() -> Any:
    session = MagicMock(spec=AsyncSession)
    session.in_transaction = MagicMock(return_value=True)
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    session.__contains__ = MagicMock(return_value=True)
    return session


async def test_passed_orm_row_is_refreshed_after_rollback(
    persistent_workspace: Workspace,
) -> None:
    """The row the caller passed is re-populated before the next attempt."""
    worker = _Worker()
    wire_worker_for_retry_test(worker, max_retries=2)
    session = _fake_session()
    attempts: list[int] = []

    async def flaky(db: AsyncSession, row: Workspace) -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("delivery blew up")
        return "ok"

    result = await worker.execute_with_retry(flaky, session, persistent_workspace, item_key="k")

    assert result == "ok"
    # Rolled back once (after the single failure), then revived the row.
    assert session.rollback.await_count == 1
    session.refresh.assert_awaited_once_with(persistent_workspace)


async def test_detached_row_is_skipped(persistent_workspace: Workspace) -> None:
    """A row owned by a different session is never refreshed through this one."""
    worker = _Worker()
    wire_worker_for_retry_test(worker, max_retries=1)
    session = _fake_session()
    session.__contains__ = MagicMock(return_value=False)

    async def always_fail(db: AsyncSession, row: Workspace) -> None:
        raise RuntimeError("nope")

    await worker.execute_with_retry(always_fail, session, persistent_workspace, item_key="k")

    session.refresh.assert_not_awaited()


async def test_non_orm_arguments_are_not_refreshed() -> None:
    """Ids, sessions, and plain values must not be sent through ``refresh``."""
    worker = _Worker()
    wire_worker_for_retry_test(worker, max_retries=1)
    session = _fake_session()

    async def always_fail(db: AsyncSession, row_id: uuid.UUID, label: str) -> None:
        raise RuntimeError("nope")

    await worker.execute_with_retry(always_fail, session, uuid.uuid4(), "label", item_key="k")

    session.refresh.assert_not_awaited()


async def test_refresh_failure_does_not_abort_the_retry_loop(
    persistent_workspace: Workspace,
) -> None:
    """A row deleted underneath us must not mask the original error."""
    worker = _Worker()
    wire_worker_for_retry_test(worker, max_retries=2)
    session = _fake_session()
    session.refresh = AsyncMock(side_effect=RuntimeError("row is gone"))
    attempts: list[int] = []

    async def flaky(db: AsyncSession, row: Workspace) -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("transient")
        return "ok"

    result = await worker.execute_with_retry(flaky, session, persistent_workspace, item_key="k")

    assert result == "ok"
    assert len(attempts) == 2
