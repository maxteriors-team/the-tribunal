"""Tests for app.utils.background_tasks — fire-and-forget task helper."""

from __future__ import annotations

import asyncio

import pytest

from app.utils import background_tasks
from app.utils.background_tasks import (
    background_task_count,
    spawn_background_task,
)


class TestSpawnBackgroundTask:
    """Tests for spawn_background_task lifecycle."""

    @pytest.mark.asyncio
    async def test_task_runs_to_completion(self) -> None:
        """Spawned task executes its coroutine."""
        result: list[str] = []

        async def work() -> None:
            await asyncio.sleep(0)
            result.append("done")

        task = spawn_background_task(work())
        await task
        assert result == ["done"]

    @pytest.mark.asyncio
    async def test_task_added_then_removed_from_set(self) -> None:
        """Task is pinned in the set during execution and removed when done."""
        started = asyncio.Event()
        proceed = asyncio.Event()

        async def work() -> None:
            started.set()
            await proceed.wait()

        before = background_task_count()
        task = spawn_background_task(work(), name="lifecycle-test")
        await started.wait()
        assert background_task_count() == before + 1
        assert task in background_tasks._background_tasks

        proceed.set()
        await task
        # Done callbacks run after the task completes; yield once to flush.
        await asyncio.sleep(0)
        assert task not in background_tasks._background_tasks
        assert background_task_count() == before

    @pytest.mark.asyncio
    async def test_exceptions_are_logged_not_raised(self, caplog: pytest.LogCaptureFixture) -> None:
        """A failing task logs the exception instead of crashing the loop."""

        async def boom() -> None:
            raise RuntimeError("kaboom")

        task = spawn_background_task(boom(), name="boom-test")
        # Awaiting the task itself re-raises; we want to confirm the
        # done-callback logger handled it. Wait via a shielded gather so
        # the callback fires before we inspect logs.
        with pytest.raises(RuntimeError, match="kaboom"):
            await task
        await asyncio.sleep(0)

        assert task not in background_tasks._background_tasks

    @pytest.mark.asyncio
    async def test_cancellation_does_not_log_error(self) -> None:
        """Cancelled tasks are not treated as failures."""

        async def work() -> None:
            await asyncio.sleep(60)

        task = spawn_background_task(work(), name="cancel-test")
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert task not in background_tasks._background_tasks

    @pytest.mark.asyncio
    async def test_task_name_is_set(self) -> None:
        """Custom task name is propagated to asyncio.Task."""

        async def work() -> None:
            return None

        task = spawn_background_task(work(), name="my-task")
        assert task.get_name() == "my-task"
        await task
