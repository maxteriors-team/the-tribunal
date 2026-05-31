"""Tests for the standalone background-worker runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.workers import runner


async def test_runner_starts_workers_then_cleans_up_on_stop() -> None:
    """``run_until_stopped`` owns the worker lifecycle and shared resources."""
    calls: list[str] = []

    def _validate() -> None:
        calls.append("validate")

    async def _start_workers() -> None:
        calls.append("start_workers")

    async def _wait_for_stop() -> None:
        calls.append("wait_for_stop")

    async def _stop_workers() -> None:
        calls.append("stop_workers")

    async def _close_redis() -> None:
        calls.append("close_redis")

    fake_engine = MagicMock()
    fake_engine.dispose = AsyncMock(side_effect=lambda: calls.append("dispose"))

    with (
        patch.object(runner, "_validate_startup_config", _validate),
        patch.object(runner, "start_all_workers", _start_workers),
        patch.object(runner, "stop_all_workers", _stop_workers),
        patch.object(runner, "close_redis", _close_redis),
        patch.object(runner, "engine", fake_engine),
    ):
        await runner.run_until_stopped(wait_for_stop=_wait_for_stop)

    assert calls == [
        "validate",
        "start_workers",
        "wait_for_stop",
        "stop_workers",
        "close_redis",
        "dispose",
    ]
    fake_engine.dispose.assert_awaited_once()
