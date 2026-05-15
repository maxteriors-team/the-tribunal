"""Base worker class and registry for background workers.

Provides a reusable base class that extracts common worker patterns:
- Start/stop lifecycle management
- Async run loop with configurable poll interval
- Logging with component name binding
- Singleton registry for global worker instances
- Redis heartbeat keys so ``/readyz`` can verify per-worker liveness
"""

import asyncio
import contextlib
import random
import time
from abc import ABC, abstractmethod
from typing import ClassVar

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

    def __init__(self, poll_interval: int | None = None) -> None:
        """Initialize the worker.

        Args:
            poll_interval: Optional override for poll interval in seconds.
        """
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self._poll_interval = poll_interval or self.POLL_INTERVAL_SECONDS
        self._worker_label = self.COMPONENT_NAME or self.__class__.__name__.lower()
        self._items_this_cycle = 0
        self.logger = logger.bind(component=self._worker_label)

    async def start(self) -> None:
        """Start the worker background task."""
        if self.running:
            self.logger.warning("Worker already running")
            return

        self.running = True
        await self._on_start()
        self._task = asyncio.create_task(self._run_loop())
        self.logger.info("Worker started")

    async def stop(self) -> None:
        """Stop the worker."""
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._on_stop()
        self.logger.info("Worker stopped")

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
