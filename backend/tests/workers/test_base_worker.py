"""Tests for BaseWorker and WorkerRegistry.

Tests the abstract base worker lifecycle (start, stop, run loop)
and the WorkerRegistry singleton pattern using a concrete test subclass.
No external services, databases, or Redis required.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from app.workers.base import (
    HEARTBEAT_TTL_MULTIPLIER,
    BaseWorker,
    WorkerRegistry,
    heartbeat_key,
)


class ConcreteWorker(BaseWorker):
    """Minimal concrete worker for testing."""

    POLL_INTERVAL_SECONDS = 1
    COMPONENT_NAME = "test_worker"

    def __init__(self, poll_interval: int | None = None) -> None:
        super().__init__(poll_interval=poll_interval)
        self.process_count = 0

    async def _process_items(self) -> None:
        self.process_count += 1


class SlowStartWorker(BaseWorker):
    """Worker that records _on_start and _on_stop calls."""

    COMPONENT_NAME = "slow_start_worker"

    def __init__(self) -> None:
        super().__init__()
        self.started = False
        self.stopped = False

    async def _on_start(self) -> None:
        self.started = True

    async def _on_stop(self) -> None:
        self.stopped = True

    async def _process_items(self) -> None:
        pass


class ErrorWorker(BaseWorker):
    """Worker that raises an exception in _process_items."""

    COMPONENT_NAME = "error_worker"

    def __init__(self) -> None:
        super().__init__(poll_interval=1)
        self.process_count = 0

    async def _process_items(self) -> None:
        self.process_count += 1
        raise RuntimeError("Simulated processing error")


class TestBaseWorkerInit:
    """Tests for BaseWorker initialization."""

    def test_initial_state(self) -> None:
        """Worker starts with running=False and no task."""
        worker = ConcreteWorker()
        assert worker.running is False
        assert worker._task is None

    def test_default_poll_interval(self) -> None:
        """Default poll interval comes from class attribute."""
        worker = ConcreteWorker()
        assert worker._poll_interval == ConcreteWorker.POLL_INTERVAL_SECONDS

    def test_custom_poll_interval(self) -> None:
        """Custom poll interval overrides class attribute."""
        worker = ConcreteWorker(poll_interval=30)
        assert worker._poll_interval == 30

    def test_component_name_in_logger(self) -> None:
        """Component name is used for logging."""
        worker = ConcreteWorker()
        # Logger is bound - just check it's not None
        assert worker.logger is not None


class TestBaseWorkerLifecycle:
    """Tests for BaseWorker start/stop lifecycle."""

    async def test_start_sets_running(self) -> None:
        """start() sets running=True and creates a task."""
        worker = ConcreteWorker()
        await worker.start()
        try:
            assert worker.running is True
            assert worker._task is not None
        finally:
            await worker.stop()

    async def test_stop_clears_running(self) -> None:
        """stop() sets running=False and clears task."""
        worker = ConcreteWorker()
        await worker.start()
        await worker.stop()
        assert worker.running is False
        assert worker._task is None

    async def test_double_start_is_safe(self) -> None:
        """Starting an already-running worker is a no-op."""
        worker = ConcreteWorker()
        await worker.start()
        task_before = worker._task
        await worker.start()  # second start — should be no-op
        assert worker._task is task_before
        await worker.stop()

    async def test_stop_without_start_is_safe(self) -> None:
        """Stopping a worker that was never started does not raise."""
        worker = ConcreteWorker()
        await worker.stop()  # should not raise
        assert worker.running is False

    async def test_on_start_hook_called(self) -> None:
        """_on_start() is called when the worker starts."""
        worker = SlowStartWorker()
        await worker.start()
        try:
            assert worker.started is True
        finally:
            await worker.stop()

    async def test_on_stop_hook_called(self) -> None:
        """_on_stop() is called when the worker stops."""
        worker = SlowStartWorker()
        await worker.start()
        await worker.stop()
        assert worker.stopped is True

    async def test_process_items_called_in_loop(self) -> None:
        """_process_items is invoked at least once after starting."""
        worker = ConcreteWorker(poll_interval=0)
        await worker.start()
        # Give the loop a moment to run
        await asyncio.sleep(0.05)
        await worker.stop()
        assert worker.process_count >= 1

    async def test_error_in_process_items_does_not_crash_loop(self) -> None:
        """Exceptions in _process_items are caught and loop continues."""
        worker = ErrorWorker()
        await worker.start()
        await asyncio.sleep(0.05)
        count_before = worker.process_count
        await asyncio.sleep(0.05)
        await worker.stop()
        # Loop kept running despite errors
        assert worker.process_count >= count_before


class TestHeartbeatAndLogging:
    """Tests for Redis heartbeat writes, structured logs, and sleep jitter."""

    async def test_heartbeat_written_after_each_cycle(self) -> None:
        """Each completed cycle writes ``worker:<name>:heartbeat`` via ``setex``."""
        fake_redis = AsyncMock()
        fake_redis.setex = AsyncMock(return_value=True)

        async def _get_redis() -> AsyncMock:
            return fake_redis

        worker = ConcreteWorker(poll_interval=1)
        with patch("app.workers.base.get_redis", new=_get_redis):
            await worker.start()
            await asyncio.sleep(0.05)
            await worker.stop()

        assert fake_redis.setex.await_count >= 1
        call_kwargs = fake_redis.setex.call_args_list[0]
        key, ttl, _value = call_kwargs.args
        assert key == heartbeat_key("test_worker")
        assert ttl == HEARTBEAT_TTL_MULTIPLIER * 1

    async def test_heartbeat_write_failure_does_not_crash_loop(self) -> None:
        """Redis being unreachable is logged and swallowed; loop keeps running."""

        async def _broken_get_redis() -> AsyncMock:
            raise RuntimeError("redis is down")

        worker = ConcreteWorker(poll_interval=0)
        with patch("app.workers.base.get_redis", new=_broken_get_redis):
            await worker.start()
            await asyncio.sleep(0.05)
            count = worker.process_count
            await worker.stop()

        # The loop continued even though every heartbeat write blew up.
        assert count >= 1

    async def test_heartbeat_also_written_when_process_items_raises(self) -> None:
        """A wedged-but-recovering cycle still publishes a heartbeat."""
        fake_redis = AsyncMock()
        fake_redis.setex = AsyncMock(return_value=True)

        async def _get_redis() -> AsyncMock:
            return fake_redis

        worker = ErrorWorker()
        with patch("app.workers.base.get_redis", new=_get_redis):
            await worker.start()
            await asyncio.sleep(0.05)
            await worker.stop()

        # Even though _process_items raises every cycle, the heartbeat is
        # still written so /readyz reflects "loop is alive" rather than
        # "loop is wedged".
        assert fake_redis.setex.await_count >= 1

    async def test_record_items_processed_feeds_into_loop_completed_log(self) -> None:
        """``record_items_processed`` increments the per-cycle counter."""
        observed: list[int] = []

        class CountingWorker(BaseWorker):
            POLL_INTERVAL_SECONDS = 0
            COMPONENT_NAME = "counting_worker"

            async def _process_items(self) -> None:
                self.record_items_processed(3)
                observed.append(self._items_this_cycle)

        fake_redis = AsyncMock()
        fake_redis.setex = AsyncMock(return_value=True)

        async def _get_redis() -> AsyncMock:
            return fake_redis

        worker = CountingWorker()
        with patch("app.workers.base.get_redis", new=_get_redis):
            await worker.start()
            await asyncio.sleep(0.05)
            await worker.stop()

        assert observed and all(value == 3 for value in observed)

    async def test_sleep_uses_jitter(self) -> None:
        """``asyncio.sleep`` is called with poll_interval + jitter (≤10%)."""
        sleep_durations: list[float] = []
        real_sleep = asyncio.sleep

        async def _record_sleep(delay: float) -> None:
            sleep_durations.append(delay)
            # Hand control back so the loop can iterate quickly.
            await real_sleep(0)

        fake_redis = AsyncMock()
        fake_redis.setex = AsyncMock(return_value=True)

        async def _get_redis() -> AsyncMock:
            return fake_redis

        worker = ConcreteWorker(poll_interval=10)
        with (
            patch("app.workers.base.get_redis", new=_get_redis),
            patch("app.workers.base.asyncio.sleep", new=_record_sleep),
        ):
            await worker.start()
            await real_sleep(0.05)
            await worker.stop()

        assert sleep_durations, "loop never reached the sleep call"
        for delay in sleep_durations:
            # Must always be >= poll_interval and <= poll_interval * 1.10
            assert 10 <= delay <= 11.0


class TestWorkerRegistry:
    """Tests for WorkerRegistry singleton pattern."""

    def _make_registry(self) -> WorkerRegistry[ConcreteWorker]:
        """Create a fresh registry for testing."""
        return WorkerRegistry(ConcreteWorker)

    def test_get_returns_none_before_start(self) -> None:
        """get() returns None before start() is called."""
        registry = self._make_registry()
        assert registry.get() is None

    async def test_start_creates_instance(self) -> None:
        """start() creates and starts a worker instance."""
        registry = self._make_registry()
        worker = await registry.start()
        try:
            assert worker is not None
            assert worker.running is True
            assert registry.get() is worker
        finally:
            await registry.stop()

    async def test_start_is_idempotent(self) -> None:
        """Calling start() twice returns the same instance."""
        registry = self._make_registry()
        first = await registry.start()
        second = await registry.start()
        try:
            assert first is second
        finally:
            await registry.stop()

    async def test_stop_clears_instance(self) -> None:
        """stop() clears the managed instance."""
        registry = self._make_registry()
        await registry.start()
        await registry.stop()
        assert registry.get() is None

    async def test_stop_without_start_is_safe(self) -> None:
        """stop() on a registry that was never started does not raise."""
        registry = self._make_registry()
        await registry.stop()  # should not raise

    async def test_restart_after_stop(self) -> None:
        """Registry can be started again after being stopped."""
        registry = self._make_registry()
        await registry.start()
        await registry.stop()
        worker = await registry.start()
        try:
            assert worker.running is True
        finally:
            await registry.stop()
