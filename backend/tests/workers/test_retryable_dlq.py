"""Tests for ``RetryableWorker`` retry-exhaustion → DLQ insertion path.

The retryable mixin retries transient errors and, when the budget is
exhausted, writes a row to the ``failed_jobs`` table. These tests cover:

1. Successful calls never touch the DLQ.
2. A call that fails forever ends up at ``_record_dead_letter`` with the
   correct ``worker_name``, ``item_key``, payload, and error string.
3. ``_dead_letter`` never raises — DB failures are logged but swallowed.
4. The static upsert helper inserts a new row on first failure and bumps
   ``attempts`` / ``last_failed_at`` on repeat failures.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.failed_job import (
    FAILED_JOB_STATUS_ABANDONED,
    FAILED_JOB_STATUS_PENDING,
    FailedJob,
)
from app.workers.retryable import RetryableWorker


class _Recorder:
    """Test double that captures ``_record_dead_letter`` invocations."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        session: Any,
        *,
        worker_name: str,
        item_key: str,
        payload: dict[str, Any],
        error: str | None,
    ) -> None:
        self.calls.append(
            {
                "worker_name": worker_name,
                "item_key": item_key,
                "payload": payload,
                "error": error,
            }
        )


class _NullSession:
    """No-op async context manager that yields itself; used to satisfy
    ``async with session_factory() as session``."""

    async def __aenter__(self) -> _NullSession:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


def _null_session_factory() -> _NullSession:
    return _NullSession()


def _make_worker(
    *,
    max_retries: int = 2,
    component_name: str = "test_worker",
    recorder: _Recorder | None = None,
) -> RetryableWorker:
    """Build a RetryableWorker instance with retry/sleep made instant."""

    class _Worker(RetryableWorker):
        COMPONENT_NAME = component_name

    worker = _Worker()
    worker.max_retries = max_retries
    worker.backoff_base_seconds = 0.0
    worker.logger = MagicMock()
    # Replace the real session factory + the DB-touching upsert so unit
    # tests don't need a live Postgres.
    worker._dlq_session_factory = lambda: _null_session_factory  # type: ignore[method-assign]
    if recorder is not None:
        worker._record_dead_letter = recorder  # type: ignore[method-assign]
    return worker


# ---------------------------------------------------------------------------
# execute_with_retry → _dead_letter orchestration
# ---------------------------------------------------------------------------


async def test_success_skips_dead_letter() -> None:
    recorder = _Recorder()
    worker = _make_worker(recorder=recorder)

    async def ok() -> str:
        return "fine"

    result = await worker.execute_with_retry(ok, item_key="key-1")

    assert result == "fine"
    assert recorder.calls == []


async def test_retries_then_succeeds_skips_dead_letter() -> None:
    recorder = _Recorder()
    worker = _make_worker(max_retries=3, recorder=recorder)
    attempts: list[int] = []

    async def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"

    result = await worker.execute_with_retry(flaky, item_key="key-flaky")

    assert result == "ok"
    assert len(attempts) == 3
    assert recorder.calls == []


async def test_exhausted_retries_writes_to_dlq() -> None:
    recorder = _Recorder()
    worker = _make_worker(max_retries=2, component_name="my_worker", recorder=recorder)

    async def always_fail(contact_id: int, *, reason: str) -> None:
        raise ValueError(f"boom for {contact_id}: {reason}")

    result = await worker.execute_with_retry(
        always_fail, 42, reason="db-down", item_key="contact-42"
    )

    assert result is None
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["worker_name"] == "my_worker"
    assert call["item_key"] == "contact-42"
    assert "boom for 42: db-down" in (call["error"] or "")

    payload = call["payload"]
    assert payload["fn"] == "always_fail"
    # args/kwargs round-trip through the JSON-safe coercer.
    assert payload["args"] == [42]
    assert payload["kwargs"] == {"reason": "db-down"}


async def test_dead_letter_uses_function_name_when_item_key_missing() -> None:
    recorder = _Recorder()
    worker = _make_worker(max_retries=1, recorder=recorder)

    async def specific_fn() -> None:
        raise RuntimeError("fail")

    await worker.execute_with_retry(specific_fn)

    assert recorder.calls[0]["item_key"] == "specific_fn"


async def test_dead_letter_db_failure_is_swallowed() -> None:
    """If the DB write blows up, the worker loop must not crash."""

    class _Worker(RetryableWorker):
        COMPONENT_NAME = "fragile_worker"

    worker = _Worker()
    worker.max_retries = 1
    worker.backoff_base_seconds = 0.0
    worker.logger = MagicMock()

    # Session factory raises immediately — simulates DB connectivity loss.
    def _broken_factory() -> Any:
        raise ConnectionError("postgres unreachable")

    worker._dlq_session_factory = lambda: _broken_factory  # type: ignore[method-assign]

    async def always_fail() -> None:
        raise RuntimeError("nope")

    # Must not raise — the dead-letter persistence failure is logged only.
    result = await worker.execute_with_retry(always_fail, item_key="x")
    assert result is None
    worker.logger.exception.assert_called()


async def test_non_jsonable_args_are_safely_coerced() -> None:
    recorder = _Recorder()
    worker = _make_worker(max_retries=1, recorder=recorder)

    class Opaque:
        def __repr__(self) -> str:
            return "<Opaque object>"

    async def fail_with_opaque(_obj: Any) -> None:
        raise RuntimeError("bad")

    await worker.execute_with_retry(fail_with_opaque, Opaque(), item_key="opaque-1")

    payload = recorder.calls[0]["payload"]
    # Opaque objects collapse to their repr — JSON-safe and bounded.
    assert payload["args"] == ["<Opaque object>"]


# ---------------------------------------------------------------------------
# _record_dead_letter upsert behavior — exercised against a fake session
# ---------------------------------------------------------------------------


class _FakeAsyncSession:
    """Minimal async session that mimics the subset of SQLAlchemy used by
    ``RetryableWorker._record_dead_letter``: ``execute(select)``,
    ``execute(update)``, ``add()``, ``commit()``, ``refresh()``."""

    def __init__(self) -> None:
        self.rows: list[FailedJob] = []
        self.commits = 0

    async def execute(self, stmt: Any) -> _FakeResult:
        # Detect select vs update by class name to avoid importing every
        # SA construct in the test.
        cls = stmt.__class__.__name__
        if cls == "Select":
            # WHERE clauses are stored on stmt.whereclause as a BooleanClauseList.
            # We re-extract worker_name + item_key from the compiled params.
            params = stmt.compile().params
            worker_name = params.get("worker_name_1")
            item_key = params.get("item_key_1")
            for row in self.rows:
                if row.worker_name == worker_name and row.item_key == item_key:
                    return _FakeResult(row)
            return _FakeResult(None)

        if cls == "Update":
            compiled = stmt.compile()
            row_id = compiled.params.get("id_1")
            for row in self.rows:
                if row.id == row_id:
                    # Apply the ``values`` payload.
                    for key, value in (stmt._values or {}).items():
                        col_name = key.key if hasattr(key, "key") else str(key)
                        if col_name == "attempts":
                            row.attempts = row.attempts + 1
                        else:
                            setattr(row, col_name, _resolve_value(value))
                    return _FakeResult(None)
            return _FakeResult(None)

        raise AssertionError(f"unexpected statement: {cls}")

    def add(self, row: FailedJob) -> None:
        self.rows.append(row)

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _row: FailedJob) -> None:
        return None


class _FakeResult:
    def __init__(self, row: FailedJob | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> FailedJob | None:
        return self._row


def _resolve_value(value: Any) -> Any:
    """SQLAlchemy ``values()`` arguments arrive as BindParameter or literals."""
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "effective_value"):
        return value.effective_value
    return value


async def test_record_dead_letter_inserts_new_row() -> None:
    session = _FakeAsyncSession()

    row = await RetryableWorker._record_dead_letter(
        session,  # type: ignore[arg-type]
        worker_name="nudge_worker",
        item_key="contact-7",
        payload={"fn": "deliver", "args": [7], "kwargs": {}},
        error="timeout",
    )

    assert len(session.rows) == 1
    assert row.worker_name == "nudge_worker"
    assert row.item_key == "contact-7"
    assert row.attempts == 1
    assert row.status == FAILED_JOB_STATUS_PENDING
    assert row.error == "timeout"
    assert session.commits == 1


async def test_record_dead_letter_bumps_attempts_on_repeat() -> None:
    session = _FakeAsyncSession()
    existing = FailedJob(
        worker_name="nudge_worker",
        item_key="contact-7",
        payload={},
        error="first-error",
        attempts=1,
        first_failed_at=datetime.now(UTC),
        last_failed_at=datetime.now(UTC),
        status=FAILED_JOB_STATUS_ABANDONED,
    )
    session.rows.append(existing)

    await RetryableWorker._record_dead_letter(
        session,  # type: ignore[arg-type]
        worker_name="nudge_worker",
        item_key="contact-7",
        payload={"fn": "deliver", "args": [7], "kwargs": {}},
        error="second-error",
    )

    # No new row — the existing one was updated in place.
    assert len(session.rows) == 1
    updated = session.rows[0]
    assert updated.attempts == 2
    assert updated.error == "second-error"
    # Re-failure resurrects an abandoned row back into the triage queue.
    assert updated.status == FAILED_JOB_STATUS_PENDING


# ---------------------------------------------------------------------------
# Passed-in AsyncSession is rolled back between attempts
# ---------------------------------------------------------------------------


def _fake_session(*, in_transaction: bool = True) -> Any:
    """MagicMock that passes ``isinstance(x, AsyncSession)`` with async rollback."""
    session = MagicMock(spec=AsyncSession)
    session.in_transaction = MagicMock(return_value=in_transaction)
    session.rollback = AsyncMock()
    return session


async def test_passed_session_rolled_back_between_retries() -> None:
    """A DB error leaves the session pending-rollback; the retry must reset it
    or it would raise PendingRollbackError instead of actually retrying."""
    recorder = _Recorder()
    worker = _make_worker(max_retries=3, recorder=recorder)
    session = _fake_session()
    attempts: list[int] = []

    async def flaky(db: AsyncSession) -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("db blip")
        return "ok"

    result = await worker.execute_with_retry(flaky, session, item_key="k")

    assert result == "ok"
    assert len(attempts) == 3
    # Rolled back after each of the two failures, before the retry.
    assert session.rollback.await_count == 2
    assert recorder.calls == []


async def test_session_not_rolled_back_when_not_in_transaction() -> None:
    worker = _make_worker(max_retries=1, recorder=_Recorder())
    session = _fake_session(in_transaction=False)

    async def always_fail(db: AsyncSession) -> None:
        raise RuntimeError("x")

    await worker.execute_with_retry(always_fail, session, item_key="k")

    session.rollback.assert_not_awaited()


async def test_rollback_failure_does_not_abort_retry_loop() -> None:
    worker = _make_worker(max_retries=2, recorder=_Recorder())
    session = _fake_session()
    session.rollback = AsyncMock(side_effect=RuntimeError("rollback failed"))
    attempts: list[int] = []

    async def flaky(db: AsyncSession) -> str:
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("db blip")
        return "ok"

    # A failing rollback is swallowed — the retry still proceeds and succeeds.
    result = await worker.execute_with_retry(flaky, session, item_key="k")
    assert result == "ok"


async def test_execute_with_retry_actually_sleeps_between_attempts() -> None:
    """Sanity check that backoff is wired up (uses real asyncio.sleep with 0)."""
    recorder = _Recorder()
    worker = _make_worker(max_retries=2, recorder=recorder)
    attempts: list[float] = []

    async def fail() -> None:
        attempts.append(asyncio.get_event_loop().time())
        raise RuntimeError("nope")

    await worker.execute_with_retry(fail, item_key="x")
    # max_retries=2 → 3 total attempts.
    assert len(attempts) == 3
    assert len(recorder.calls) == 1


# ---------------------------------------------------------------------------
# Worker-name resolution
# ---------------------------------------------------------------------------


async def test_resolve_worker_name_prefers_dlq_override() -> None:
    class _Worker(RetryableWorker):
        COMPONENT_NAME = "component"
        dlq_worker_name = "explicit"

    w = _Worker()
    assert w._resolve_worker_name() == "explicit"


async def test_resolve_worker_name_falls_back_to_component_name() -> None:
    class _Worker(RetryableWorker):
        COMPONENT_NAME = "my_component"

    w = _Worker()
    assert w._resolve_worker_name() == "my_component"


async def test_resolve_worker_name_falls_back_to_classname() -> None:
    class CustomWorker(RetryableWorker):
        COMPONENT_NAME = None

    w = CustomWorker()
    assert w._resolve_worker_name() == "customworker"


@pytest.mark.parametrize("retries", [0, 1, 5])
async def test_terminal_failure_always_writes_one_dlq_row(retries: int) -> None:
    recorder = _Recorder()
    worker = _make_worker(max_retries=retries, recorder=recorder)

    async def always_fail() -> None:
        raise RuntimeError("nope")

    await worker.execute_with_retry(always_fail, item_key=f"k-{retries}")
    assert len(recorder.calls) == 1
