"""Shared helpers for RetryableWorker-contract tests.

These helpers exist to keep per-worker test files focused on the
worker-specific failure path rather than re-declaring the same boilerplate.
"""

from __future__ import annotations

from typing import Any


class Recorder:
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


class NullSession:
    """No-op async context manager standing in for ``AsyncSessionLocal()``."""

    async def __aenter__(self) -> NullSession:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None


def null_session_factory() -> NullSession:
    return NullSession()


def wire_worker_for_retry_test(worker: Any, *, max_retries: int = 1) -> Recorder:
    """Configure a worker so retries are instant and DLQ writes are captured.

    Returns the ``Recorder`` so the test can assert on captured calls.
    """
    recorder = Recorder()
    worker.max_retries = max_retries
    worker.backoff_base_seconds = 0.0
    worker._dlq_session_factory = lambda: null_session_factory
    worker._record_dead_letter = recorder
    return recorder
