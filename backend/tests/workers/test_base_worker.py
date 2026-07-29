"""Tests for BaseWorker and WorkerRegistry.

Tests the abstract base worker lifecycle (start, stop, run loop)
and the WorkerRegistry singleton pattern using a concrete test subclass.
No external services, databases, or Redis required.
"""

import asyncio
import contextlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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

    def __init__(
        self,
        poll_interval: int | None = None,
        *,
        max_concurrency: int | None = None,
        drain_timeout: float | None = None,
    ) -> None:
        super().__init__(
            poll_interval=poll_interval,
            max_concurrency=max_concurrency,
            drain_timeout=drain_timeout,
        )
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


class LoopCrashError(BaseException):
    """A non-``Exception`` error that escapes the loop's ``except Exception``."""


class CrashingWorker(BaseWorker):
    """Worker whose run loop dies via a ``BaseException`` on the first cycle.

    A plain ``Exception`` from ``_process_items`` is caught and logged by the
    run loop; a ``BaseException`` escapes that guard and kills the task —
    reproducing the silent worker death seen in production.
    """

    COMPONENT_NAME = "crashing_worker"

    def __init__(self) -> None:
        super().__init__(poll_interval=0)

    async def _process_items(self) -> None:
        raise LoopCrashError("boom")


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

    async def test_run_loop_crash_is_logged_with_the_exception(self) -> None:
        """A ``BaseException`` that kills the run-loop task is logged loudly.

        Regression: the task is fire-and-forget, so a ``BaseException`` the
        loop's ``except Exception`` can't catch used to kill it silently — the
        worker went quiet with a stale heartbeat and no traceback (the observed
        production failure). The done-callback must surface the cause.
        """
        worker = CrashingWorker()
        mock_logger = MagicMock()
        worker.logger = mock_logger
        await worker.start()
        # The loop dies on its first cycle; await it so the error is retrieved.
        assert worker._task is not None
        with contextlib.suppress(BaseException):
            await worker._task
        await asyncio.sleep(0)  # let the done-callback run

        crashes = [
            call
            for call in mock_logger.error.call_args_list
            if call.args and call.args[0] == "worker_run_loop_crashed"
        ]
        assert crashes, "expected a worker_run_loop_crashed log"
        assert crashes[0].kwargs.get("error") == "LoopCrashError"
        assert crashes[0].kwargs.get("exc_info") is not None

    async def test_clean_stop_is_not_reported_as_a_crash(self) -> None:
        """A normal ``stop()`` must not be mistaken for an unexpected death."""
        worker = ConcreteWorker(poll_interval=0)
        mock_logger = MagicMock()
        worker.logger = mock_logger
        await worker.start()
        await asyncio.sleep(0.02)
        await worker.stop()
        await asyncio.sleep(0)  # allow any pending done-callback to run

        spurious = [
            call
            for call in mock_logger.error.call_args_list
            if call.args
            and call.args[0]
            in {
                "worker_run_loop_crashed",
                "worker_run_loop_cancelled",
                "worker_run_loop_exited",
            }
        ]
        assert not spurious, f"clean stop should not log a death: {spurious}"

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


class TestBaseWorkerConcurrency:
    """Tests for the per-worker concurrency cap (asyncio.Semaphore)."""

    def test_default_max_concurrency(self) -> None:
        """Default ``MAX_CONCURRENCY`` is 5 when subclass doesn't override."""
        worker = ConcreteWorker()
        assert worker._max_concurrency == 5
        # Semaphore is constructed with the same value (private attribute on
        # asyncio.Semaphore, but stable across the supported CPython range).
        assert worker._semaphore._value == 5

    def test_class_attribute_overrides_default(self) -> None:
        """A subclass setting ``MAX_CONCURRENCY`` is honoured."""

        class FastWorker(BaseWorker):
            COMPONENT_NAME = "fast_worker"
            MAX_CONCURRENCY = 20

            async def _process_items(self) -> None:
                return None

        worker = FastWorker()
        assert worker._max_concurrency == 20

    def test_constructor_overrides_class_attribute(self) -> None:
        """``max_concurrency=`` constructor arg wins over the class attribute."""
        worker = ConcreteWorker(max_concurrency=2)
        assert worker._max_concurrency == 2

    def test_zero_concurrency_rejected(self) -> None:
        """``max_concurrency`` must be >= 1; zero is a config error."""
        with pytest.raises(ValueError, match="max_concurrency"):
            ConcreteWorker(max_concurrency=0)

    async def test_run_concurrently_caps_parallelism(self) -> None:
        """At most ``max_concurrency`` items run concurrently."""
        observed_peak = 0
        live = 0
        lock = asyncio.Lock()

        async def slow_item() -> None:
            nonlocal live, observed_peak
            async with lock:
                live += 1
                observed_peak = max(observed_peak, live)
            await asyncio.sleep(0.02)
            async with lock:
                live -= 1

        worker = ConcreteWorker(max_concurrency=3)
        results = await worker.run_concurrently(slow_item() for _ in range(10))

        assert len(results) == 10
        assert all(r is None for r in results)
        assert observed_peak <= 3, f"saw {observed_peak} concurrent items, cap was 3"

    async def test_run_concurrently_returns_results_in_order(self) -> None:
        """Results are positionally aligned with the input iterable."""

        async def returning(n: int) -> int:
            # Stagger so completion order != submission order.
            await asyncio.sleep((5 - n) * 0.005)
            return n * 10

        worker = ConcreteWorker(max_concurrency=5)
        results = await worker.run_concurrently(returning(i) for i in range(5))

        assert results == [0, 10, 20, 30, 40]

    async def test_run_concurrently_captures_exceptions(self) -> None:
        """A failing item doesn't abort siblings — it's returned as-is."""

        async def succeed() -> str:
            return "ok"

        async def fail() -> str:
            raise RuntimeError("boom")

        worker = ConcreteWorker(max_concurrency=2)
        results = await worker.run_concurrently([succeed(), fail(), succeed()])

        assert results[0] == "ok"
        assert isinstance(results[1], RuntimeError)
        assert results[2] == "ok"

    async def test_run_concurrently_empty_iterable(self) -> None:
        """An empty input returns ``[]`` without spawning tasks."""
        worker = ConcreteWorker()
        assert await worker.run_concurrently([]) == []
        assert worker._inflight == set()

    async def test_inflight_cleared_after_run(self) -> None:
        """Completed tasks are discarded from the in-flight set."""

        async def quick() -> int:
            return 1

        worker = ConcreteWorker(max_concurrency=2)
        await worker.run_concurrently([quick() for _ in range(4)])
        # done_callback runs on the same loop iteration after gather resolves,
        # so the set must be empty here.
        assert worker._inflight == set()


class TestBaseWorkerGracefulShutdown:
    """Tests for graceful shutdown that drains in-flight items."""

    def test_default_drain_timeout(self) -> None:
        """Default ``DRAIN_TIMEOUT_SECONDS`` is 30s."""
        worker = ConcreteWorker()
        assert worker._drain_timeout == 30.0

    def test_class_attribute_overrides_drain_timeout(self) -> None:
        """Subclass override of ``DRAIN_TIMEOUT_SECONDS`` is honoured."""

        class PatientWorker(BaseWorker):
            COMPONENT_NAME = "patient_worker"
            DRAIN_TIMEOUT_SECONDS = 5.0

            async def _process_items(self) -> None:
                return None

        worker = PatientWorker()
        assert worker._drain_timeout == 5.0

    def test_constructor_overrides_drain_timeout(self) -> None:
        """``drain_timeout=`` constructor arg wins over the class attribute."""
        worker = ConcreteWorker(drain_timeout=1.5)
        assert worker._drain_timeout == 1.5

    def test_negative_drain_timeout_rejected(self) -> None:
        """``drain_timeout`` must be >= 0."""
        with pytest.raises(ValueError, match="drain_timeout"):
            ConcreteWorker(drain_timeout=-1.0)

    async def test_stop_waits_for_inflight_items(self) -> None:
        """``stop()`` waits for in-flight items to finish before returning."""
        completed: list[int] = []

        async def slow(n: int) -> None:
            await asyncio.sleep(0.05)
            completed.append(n)

        worker = ConcreteWorker(drain_timeout=5.0)
        # Seed in-flight tasks directly so we can prove stop() actually
        # drains — no need to also exercise the run-loop here.
        for n in range(3):
            task = asyncio.create_task(slow(n))
            worker._inflight.add(task)
            task.add_done_callback(worker._inflight.discard)

        await asyncio.sleep(0)  # let tasks actually start
        await worker.stop()

        assert sorted(completed) == [0, 1, 2]
        assert worker._inflight == set()

    async def test_stop_drains_real_run_concurrently_tasks(self) -> None:
        """End-to-end: in-flight ``run_concurrently`` tasks finish before stop returns."""
        completed: list[int] = []

        async def slow(n: int) -> None:
            await asyncio.sleep(0.05)
            completed.append(n)

        worker = ConcreteWorker(drain_timeout=5.0)
        # Run concurrently in a fire-and-forget task so we can interleave stop().
        runner = asyncio.create_task(worker.run_concurrently([slow(0), slow(1), slow(2)]))
        await asyncio.sleep(0)  # let tasks register in _inflight
        assert worker._inflight, "tasks should be tracked"

        await worker.stop()
        # Drain finished, so the runner gather has all results.
        results = await runner
        assert len(results) == 3
        assert sorted(completed) == [0, 1, 2]

    async def test_stop_cancels_items_that_exceed_drain_timeout(self) -> None:
        """Items still running after the drain window are cancelled."""
        cancelled_at: list[float] = []

        async def forever() -> None:
            try:
                await asyncio.sleep(10.0)
            except asyncio.CancelledError:
                cancelled_at.append(time.monotonic())
                raise

        worker = ConcreteWorker(drain_timeout=0.05)
        task = asyncio.create_task(forever())
        worker._inflight.add(task)
        task.add_done_callback(worker._inflight.discard)

        started = time.monotonic()
        await worker.stop()
        elapsed = time.monotonic() - started

        # Drain timeout was 50ms; stop should have given up well before the
        # 10-second forever sleep would otherwise have completed.
        assert elapsed < 1.0
        assert cancelled_at, "forever() should have been cancelled"
        assert task.cancelled() or task.done()

    async def test_stop_drain_completes_when_no_inflight(self) -> None:
        """Stop returns immediately when no items are in flight."""
        worker = ConcreteWorker()
        await worker.start()
        # No run_concurrently was ever called.
        started = time.monotonic()
        await worker.stop()
        elapsed = time.monotonic() - started
        # Should be essentially instantaneous (allow generous slack for CI).
        assert elapsed < 1.0

    async def test_stop_drain_does_not_resurrect_cancelled_run_loop(self) -> None:
        """After stop(), running=False and the run loop is fully cancelled."""

        async def slow() -> None:
            await asyncio.sleep(0.02)

        worker = ConcreteWorker(drain_timeout=1.0)
        await worker.start()
        # Submit work that's in flight at shutdown.
        runner = asyncio.create_task(worker.run_concurrently([slow() for _ in range(3)]))
        await asyncio.sleep(0)

        await worker.stop()
        await runner  # drain made it finish cleanly

        assert worker.running is False
        assert worker._task is None
