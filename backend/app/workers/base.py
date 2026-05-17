"""Base worker class and registry for background workers.

Provides a reusable base class that extracts common worker patterns:
- Start/stop lifecycle management
- Async run loop with configurable poll interval
- Bounded per-item concurrency via an ``asyncio.Semaphore``
- Graceful shutdown that drains in-flight work (with timeout)
- Logging with component name binding
- Singleton registry for global worker instances
- Redis heartbeat keys so ``/readyz`` can verify per-worker liveness
"""

import asyncio
import contextlib
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Iterable
from typing import Any, ClassVar, TypeVar

import structlog

from app.core.metrics import (
    observe_worker_item,
    worker_loop_timer,
)
from app.db.redis import get_redis

logger = structlog.get_logger()

# Heartbeat TTL is set to ``HEARTBEAT_TTL_MULTIPLIER * poll_interval`` so that a
# single missed cycle still leaves the key alive, but two consecutive misses
# (a wedged loop) cause the key to expire and ``/readyz`` to flip to 503.
HEARTBEAT_TTL_MULTIPLIER = 3

# Jitter is bounded to 10% of the poll interval. Enough to desynchronise
# workers across processes without materially shifting effective throughput.
_JITTER_FRACTION = 0.1

# Default max number of items a single worker may process concurrently.
# Conservative; subclasses bump this when their items are I/O-bound and the
# downstream resources (DB pool, external API rate limits) can absorb it.
_DEFAULT_MAX_CONCURRENCY = 5

# Default grace window for draining in-flight items on shutdown.
_DEFAULT_DRAIN_TIMEOUT_SECONDS = 30.0

_T = TypeVar("_T")


def heartbeat_key(component_name: str) -> str:
    """Return the Redis key that holds ``component_name``'s heartbeat timestamp."""
    return f"worker:{component_name}:heartbeat"


class BaseWorker(ABC):
    """Abstract base class for background workers.

    Subclasses must implement:
    - _process_items(): Main processing logic called each poll cycle

    Subclasses may optionally implement:
    - _on_start(): Called before the run loop starts (setup resources)
    - _on_stop(): Called after the run loop stops (cleanup resources)

    Class attributes:
    - POLL_INTERVAL_SECONDS: Time between poll cycles (default: 60)
    - COMPONENT_NAME: Logger component name (default: class name lowercase)

    Example:
        class MyWorker(BaseWorker):
            POLL_INTERVAL_SECONDS = 30
            COMPONENT_NAME = "my_worker"

            async def _process_items(self) -> None:
                # Do work each cycle
                pass
    """

    POLL_INTERVAL_SECONDS: ClassVar[int] = 60
    COMPONENT_NAME: ClassVar[str | None] = None

    # Max number of items processed concurrently via :meth:`run_concurrently`.
    # Per-worker override expected — defaults are intentionally low so a
    # subclass that forgets to tune it can't accidentally fan out 1k tasks.
    MAX_CONCURRENCY: ClassVar[int] = _DEFAULT_MAX_CONCURRENCY

    # Grace window (seconds) for in-flight items to finish on :meth:`stop`
    # before the run-loop task is cancelled. Items that exceed this window
    # are cancelled too — better to drop one item than block a deploy.
    DRAIN_TIMEOUT_SECONDS: ClassVar[float] = _DEFAULT_DRAIN_TIMEOUT_SECONDS

    def __init__(
        self,
        poll_interval: int | None = None,
        *,
        max_concurrency: int | None = None,
        drain_timeout: float | None = None,
    ) -> None:
        """Initialize the worker.

        Args:
            poll_interval: Optional override for poll interval in seconds.
            max_concurrency: Optional override for the per-worker semaphore.
                Defaults to ``MAX_CONCURRENCY``.
            drain_timeout: Optional override for the shutdown drain window.
                Defaults to ``DRAIN_TIMEOUT_SECONDS``.
        """
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self._poll_interval = poll_interval or self.POLL_INTERVAL_SECONDS
        self._worker_label = self.COMPONENT_NAME or self.__class__.__name__.lower()
        self._items_this_cycle = 0
        self.logger = logger.bind(component=self._worker_label)

        resolved_concurrency = (
            max_concurrency if max_concurrency is not None else self.MAX_CONCURRENCY
        )
        if resolved_concurrency < 1:
            raise ValueError(f"max_concurrency must be >= 1, got {resolved_concurrency}")
        self._max_concurrency = resolved_concurrency
        self._semaphore = asyncio.Semaphore(resolved_concurrency)

        resolved_drain = drain_timeout if drain_timeout is not None else self.DRAIN_TIMEOUT_SECONDS
        if resolved_drain < 0:
            raise ValueError(f"drain_timeout must be >= 0, got {resolved_drain}")
        self._drain_timeout = float(resolved_drain)

        # Tracks per-item tasks spawned via :meth:`run_concurrently` so
        # :meth:`stop` can wait for them to finish before cancelling the
        # run-loop task. Using a set so completed tasks are easy to discard.
        self._inflight: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        """Start the worker background task."""
        if self.running:
            self.logger.warning("Worker already running")
            return

        self.running = True
        await self._on_start()
        self._task = asyncio.create_task(self._run_loop())
        self.logger.info(
            "Worker started",
            max_concurrency=self._max_concurrency,
            drain_timeout=self._drain_timeout,
        )

    async def stop(self) -> None:
        """Stop the worker, draining in-flight items first.

        Shutdown sequence:

        1. Flip ``self.running`` to ``False`` so the run loop exits at the
           next safe point and ``_process_items`` can observe the shutdown.
        2. Wait up to ``_drain_timeout`` seconds for items already accepted
           via :meth:`run_concurrently` to finish. This avoids interrupting
           mid-item work (DB writes, external API calls) on deploys.
        3. Cancel any items still running after the grace window — better to
           drop one job than block a rollout indefinitely.
        4. Cancel the run-loop task and await it.
        """
        self.running = False
        await self._drain_inflight()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._on_stop()
        self.logger.info("Worker stopped")

    async def _drain_inflight(self) -> None:
        """Wait for in-flight per-item tasks to finish, bounded by timeout.

        Logged at INFO so deploys leave a paper trail of how long shutdown
        actually took. Cancellations are also logged so dropped work is
        visible in the journal.
        """
        # Snapshot — _inflight may shrink concurrently as tasks complete.
        pending = {t for t in self._inflight if not t.done()}
        if not pending:
            return

        started = time.monotonic()
        self.logger.info(
            "drain_started",
            inflight=len(pending),
            timeout=self._drain_timeout,
        )
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True),
                timeout=self._drain_timeout,
            )
            self.logger.info(
                "drain_completed",
                duration_ms=round((time.monotonic() - started) * 1000.0, 2),
            )
        except TimeoutError:
            still_running = [t for t in pending if not t.done()]
            self.logger.warning(
                "drain_timeout_exceeded",
                cancelled=len(still_running),
                timeout=self._drain_timeout,
            )
            for task in still_running:
                task.cancel()
            # Let cancellations propagate so the event loop reclaims them.
            await asyncio.gather(*still_running, return_exceptions=True)

    async def run_concurrently(
        self,
        coros: Iterable[Awaitable[_T]],
    ) -> list[_T | BaseException]:
        """Run ``coros`` concurrently, capped by the per-worker semaphore.

        Each coroutine is wrapped in a task that acquires ``self._semaphore``
        before running, so at most ``max_concurrency`` items execute at once.
        Tasks are tracked in ``self._inflight`` so :meth:`stop` can drain
        them on shutdown rather than killing in-progress work.

        Exceptions are captured (``return_exceptions=True``) so a single
        failed item doesn't abort the rest of the batch — callers decide
        how to handle errors per item (typically via ``RetryableWorker``).

        Args:
            coros: Iterable of awaitables, one per work item.

        Returns:
            List of results (or ``BaseException`` instances), positionally
            aligned with the input iterable.
        """
        coros_list = list(coros)
        if not coros_list:
            return []

        async def _bounded(coro: Awaitable[_T]) -> _T:
            async with self._semaphore:
                return await coro

        tasks: list[asyncio.Task[_T]] = [asyncio.create_task(_bounded(coro)) for coro in coros_list]
        # Track for graceful shutdown. ``discard`` so already-removed tasks
        # don't raise on the completion callback.
        for task in tasks:
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_loop(self) -> None:
        """Main worker loop that polls for items to process.

        Each cycle:
        1. Times ``_process_items`` and updates Prometheus histograms/counters
           via :func:`worker_loop_timer` (success or failure).
        2. Writes a Redis heartbeat key with a TTL of
           ``HEARTBEAT_TTL_MULTIPLIER * poll_interval`` so ``/readyz`` can
           detect wedged workers.
        3. Emits a structured ``loop_completed`` log with elapsed wall time
           and the number of items the subclass reported via
           :meth:`record_items_processed`.
        4. Sleeps ``poll_interval`` plus small jitter (≤10%) to avoid
           thundering-herd alignment across processes.
        """
        while self.running:
            self._items_this_cycle = 0
            cycle_started = time.monotonic()
            try:
                with worker_loop_timer(self._worker_label):
                    await self._process_items()
            except Exception:
                # worker_loop_timer already incremented the error counter
                # before re-raising; we only need to log here.
                self.logger.exception("Error in worker loop")

            duration_ms = (time.monotonic() - cycle_started) * 1000.0
            await self._write_heartbeat()
            self.logger.info(
                "loop_completed",
                worker=self._worker_label,
                duration_ms=round(duration_ms, 2),
                items_processed=self._items_this_cycle,
            )

            jitter = random.uniform(0, self._poll_interval * _JITTER_FRACTION)
            await asyncio.sleep(self._poll_interval + jitter)

    async def _write_heartbeat(self) -> None:
        """Persist this worker's heartbeat in Redis with a bounded TTL.

        Failures are logged at WARNING and swallowed: Redis being unreachable
        should not crash the worker loop — ``/readyz`` will already flip to
        503 once the existing key expires.
        """
        ttl = max(1, int(self._poll_interval * HEARTBEAT_TTL_MULTIPLIER))
        try:
            redis = await get_redis()
            await redis.setex(
                heartbeat_key(self._worker_label),
                ttl,
                str(int(time.time())),
            )
        except Exception as exc:  # noqa: BLE001 — broad to keep the loop alive
            self.logger.warning(
                "heartbeat_write_failed",
                worker=self._worker_label,
                error=type(exc).__name__,
            )

    def record_items_processed(self, count: int = 1) -> None:
        """Record ``count`` work items processed in the current cycle.

        Subclasses should call this once per processed item (or in batches)
        from inside :meth:`_process_items` so the
        ``worker_items_processed_total`` counter reflects real throughput
        rather than poll-cycle counts. The same count is also surfaced in
        the per-cycle ``loop_completed`` structured log.
        """
        if count <= 0:
            return
        self._items_this_cycle += count
        observe_worker_item(self._worker_label, count=count)

    @abstractmethod
    async def _process_items(self) -> None:
        """Process items in a single poll cycle.

        Subclasses must implement this method with their specific logic.
        """

    async def _on_start(self) -> None:  # noqa: B027
        """Hook called before the run loop starts.

        Override to initialize resources (e.g., HTTP clients, services).
        """

    async def _on_stop(self) -> None:  # noqa: B027
        """Hook called after the run loop stops.

        Override to clean up resources (e.g., close HTTP clients).
        """


class WorkerRegistry[W: BaseWorker]:
    """Manages singleton lifecycle for a worker class.

    Provides start/stop/get functions that maintain a single global instance
    of a worker type.

    Example:
        _registry = WorkerRegistry(MyWorker)
        start_my_worker = _registry.start
        stop_my_worker = _registry.stop
        get_my_worker = _registry.get
    """

    def __init__(self, worker_class: type[W]) -> None:
        """Initialize the registry.

        Args:
            worker_class: The worker class to manage.
        """
        self._worker_class = worker_class
        self._instance: W | None = None

    async def start(self) -> W:
        """Start the global worker instance.

        Creates a new instance if none exists and starts it.

        Returns:
            The running worker instance.
        """
        if self._instance is None:
            self._instance = self._worker_class()
            await self._instance.start()
        return self._instance

    async def stop(self) -> None:
        """Stop and clear the global worker instance."""
        if self._instance:
            await self._instance.stop()
            self._instance = None

    def get(self) -> W | None:
        """Get the current worker instance.

        Returns:
            The worker instance if running, None otherwise.
        """
        return self._instance
