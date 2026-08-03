"""NudgeWorker — one bad workspace must not skip every workspace behind it.

The tick used to iterate live ``Workspace`` ORM rows. A per-workspace failure
rolls the shared session back, expiring every instance in it, so the *next*
loop turn raised ``MissingGreenlet`` reading ``workspace.settings`` and killed
the whole pass. Iterating ids keeps the loop immune to that.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.nudge_worker import NudgeWorker


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return self._rows


def _worker() -> NudgeWorker:
    worker = NudgeWorker()
    worker.max_retries = 0
    worker.backoff_base_seconds = 0.0
    worker._dead_letter = AsyncMock()
    return worker


async def test_failing_workspace_does_not_stop_the_tick() -> None:
    """Every workspace is attempted even when an earlier one blows up."""
    worker = _worker()
    ids = [uuid.uuid4() for _ in range(3)]
    attempted: list[uuid.UUID] = []

    async def process(db: Any, workspace_id: uuid.UUID) -> None:
        attempted.append(workspace_id)
        if workspace_id == ids[0]:
            raise RuntimeError("undecryptable contact row")

    worker._process_single_workspace = process  # type: ignore[method-assign]
    worker._expire_snoozed_nudges = AsyncMock(return_value=0)  # type: ignore[method-assign]

    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result(ids))

    await worker._process_workspaces(db)

    assert attempted == ids
    worker._dead_letter.assert_awaited_once()


async def test_workspace_is_reloaded_per_attempt_and_respects_opt_out() -> None:
    """The row is fetched by id inside the retried unit, and opt-out is honored."""
    worker = _worker()
    workspace_id = uuid.uuid4()
    workspace = MagicMock(id=workspace_id, settings={"nudge_settings": {"enabled": False}})

    db = MagicMock()
    db.get = AsyncMock(return_value=workspace)
    worker.generator.generate_for_workspace = AsyncMock(return_value=0)
    worker.delivery.deliver_pending_nudges = AsyncMock(return_value=0)

    await worker._process_single_workspace(db, workspace_id)

    db.get.assert_awaited_once()
    # Disabled workspace short-circuits before any generation work.
    worker.generator.generate_for_workspace.assert_not_awaited()
    worker.delivery.deliver_pending_nudges.assert_not_awaited()


async def test_missing_workspace_is_a_no_op() -> None:
    """A workspace deleted between the id scan and processing is skipped."""
    worker = _worker()
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    worker.generator.generate_for_workspace = AsyncMock()

    await worker._process_single_workspace(db, uuid.uuid4())

    worker.generator.generate_for_workspace.assert_not_awaited()


async def test_enabled_workspace_generates_and_delivers() -> None:
    worker = _worker()
    workspace_id = uuid.uuid4()
    workspace = MagicMock(id=workspace_id, settings={})

    db = MagicMock()
    db.get = AsyncMock(return_value=workspace)
    worker.generator.generate_for_workspace = AsyncMock(return_value=2)
    worker.delivery.deliver_pending_nudges = AsyncMock(return_value=1)

    with patch.object(worker, "record_items_processed") as recorded:
        await worker._process_single_workspace(db, workspace_id)

    worker.generator.generate_for_workspace.assert_awaited_once_with(db, workspace)
    worker.delivery.deliver_pending_nudges.assert_awaited_once_with(db, workspace_id)
    assert [call.args[0] for call in recorded.call_args_list] == [2, 1]
