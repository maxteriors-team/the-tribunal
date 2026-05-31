"""Standalone entrypoint for running background workers without the API server."""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Awaitable, Callable
from contextlib import suppress

import structlog

from app.core.config import settings
from app.db.redis import close_redis
from app.db.session import engine
from app.main import _validate_startup_config
from app.workers import start_all_workers, stop_all_workers

logger = structlog.get_logger()


def _install_shutdown_handlers(stop_event: asyncio.Event) -> None:
    """Signal ``stop_event`` when the process receives SIGINT or SIGTERM."""
    loop = asyncio.get_running_loop()

    def _request_shutdown() -> None:
        if not stop_event.is_set():
            logger.info("worker_runner_shutdown_requested")
            stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signum, _request_shutdown)


async def run_until_stopped(
    *,
    wait_for_stop: Callable[[], Awaitable[object]] | None = None,
) -> None:
    """Start every worker, block until stopped, then drain resources."""
    stop_event = asyncio.Event()
    if wait_for_stop is None:
        _install_shutdown_handlers(stop_event)
        wait_for_stop = stop_event.wait

    log = logger.bind(context="worker_runner")
    log.info(
        "worker_runner_starting",
        run_background_workers=settings.run_background_workers,
    )
    _validate_startup_config()
    await start_all_workers()
    log.info("worker_runner_started")

    try:
        await wait_for_stop()
    finally:
        log.info("worker_runner_stopping")
        await stop_all_workers()
        await close_redis()
        await engine.dispose()
        log.info("worker_runner_stopped")


def main() -> None:
    """CLI entrypoint for ``uv run backend-workers``."""
    asyncio.run(run_until_stopped())


if __name__ == "__main__":
    main()
