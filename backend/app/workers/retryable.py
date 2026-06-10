"""Retryable worker mixin — exponential backoff with jitter for transient failures.

Provides ``RetryableWorker``, a mixin intended to be combined with ``BaseWorker``
(or any class exposing a bound ``self.logger``). Wrap per-item processing in
``execute_with_retry`` so transient errors are retried with exponential backoff
and jittered sleeps. Terminal failures land in the ``failed_jobs`` table via
``_dead_letter`` — see ``backend/scripts/inspect_dlq.py`` for inspection and
replay tooling.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, ClassVar, TypeVar

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.failed_job import FAILED_JOB_STATUS_PENDING, FailedJob

logger = structlog.get_logger()

T = TypeVar("T")

# Cap serialized payload size so an accidentally huge object can't blow up the
# DLQ row. The full failure is still in logs; the DB copy is for triage.
_MAX_PAYLOAD_REPR = 4_000
_MAX_ERROR_LEN = 4_000


def _safe_jsonable(value: Any) -> Any:
    """Best-effort coercion of an arbitrary value into JSON-serializable form.

    Anything that isn't a primitive, list, or dict is reduced to its ``repr``
    so the DLQ row always inserts cleanly — we never want a logging path to
    raise. Long reprs are truncated to keep DB rows bounded.
    """
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, list | tuple):
        return [_safe_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_jsonable(v) for k, v in value.items()}
    try:
        text = repr(value)
    except Exception:
        # e.g. an expired ORM instance whose __repr__ triggers a lazy load
        # (MissingGreenlet under the async engine). Never let logging raise.
        text = f"<unrepresentable {type(value).__name__}>"
    if len(text) > _MAX_PAYLOAD_REPR:
        text = text[:_MAX_PAYLOAD_REPR] + "…(truncated)"
    return text


class RetryableWorker:
    """Mixin that adds exponential-backoff retries to a worker.

    Class attributes:
    - max_retries: Maximum retry attempts after the initial call (default: 3).
      A value of 3 means up to 4 total attempts.
    - backoff_base_seconds: Base delay for exponential backoff (default: 2.0).
      Delay for attempt N is ``base * 2**N`` plus uniform jitter in [0, base).
    - dlq_worker_name: Override for the ``worker_name`` column written to the
      DLQ. Defaults to ``COMPONENT_NAME`` or the class name lowercased.

    Example:
        class MyWorker(RetryableWorker, BaseWorker):
            max_retries = 5

            async def _process_items(self) -> None:
                for item in items:
                    await self.execute_with_retry(
                        self._handle, item, item_key=str(item.id)
                    )
    """

    max_retries: ClassVar[int] = 3
    backoff_base_seconds: ClassVar[float] = 2.0
    dlq_worker_name: ClassVar[str | None] = None

    # Provided by BaseWorker (or any host class).
    logger: Any
    COMPONENT_NAME: ClassVar[str | None]

    async def execute_with_retry(
        self,
        fn: Callable[..., Awaitable[T]],
        *args: Any,
        item_key: str | None = None,
        **kwargs: Any,
    ) -> T | None:
        """Invoke ``fn(*args, **kwargs)`` with exponential backoff on failure.

        Returns the function's result on success, or ``None`` after all retries
        are exhausted (the terminal exception is forwarded to ``_dead_letter``).

        ``item_key`` is the stable identity of the item being processed (e.g.
        a contact id, a campaign-contact id). It's used to dedupe DLQ rows so
        repeated terminal failures on the same item update one row instead of
        spamming the table. Defaults to the function name when omitted.
        """
        attempt = 0
        last_exc: BaseException | None = None
        while attempt <= self.max_retries:
            try:
                return await fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                delay = self.backoff_base_seconds * (2**attempt) + random.uniform(
                    0, self.backoff_base_seconds
                )
                self.logger.warning(
                    "Retryable error, backing off",
                    fn=getattr(fn, "__name__", repr(fn)),
                    attempt=attempt + 1,
                    max_retries=self.max_retries,
                    delay_seconds=round(delay, 3),
                    error=str(exc),
                )
                await asyncio.sleep(delay)
                attempt += 1

        await self._dead_letter(fn, args, kwargs, last_exc, item_key=item_key)
        return None

    def _resolve_worker_name(self) -> str:
        """Pick the ``worker_name`` value written to the DLQ row."""
        if self.dlq_worker_name:
            return str(self.dlq_worker_name)
        component = getattr(self, "COMPONENT_NAME", None)
        if component:
            return str(component)
        return self.__class__.__name__.lower()

    async def _dead_letter(
        self,
        fn: Callable[..., Awaitable[Any]],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        exc: BaseException | None,
        *,
        item_key: str | None = None,
    ) -> None:
        """Record a permanently failed task in the ``failed_jobs`` table.

        The DB write is best-effort: a failure here is logged but never
        propagates, because the caller has already given up on the original
        task and the worker loop must keep running.
        """
        fn_name = getattr(fn, "__name__", repr(fn))
        worker_name = self._resolve_worker_name()
        resolved_item_key = item_key or fn_name
        error_text = str(exc) if exc else None
        if error_text and len(error_text) > _MAX_ERROR_LEN:
            error_text = error_text[:_MAX_ERROR_LEN] + "…(truncated)"

        payload: dict[str, Any] = {
            "fn": fn_name,
            "args": _safe_jsonable(list(args)),
            "kwargs": _safe_jsonable(kwargs),
        }

        # Always log first — guarantees a record even if the DB write fails.
        self.logger.error(
            "Dead letter: retries exhausted",
            worker=worker_name,
            item_key=resolved_item_key,
            fn=fn_name,
            error=error_text,
            exc_info=exc,
        )

        try:
            session_factory = self._dlq_session_factory()
            async with session_factory() as session:
                await self._record_dead_letter(
                    session,
                    worker_name=worker_name,
                    item_key=resolved_item_key,
                    payload=payload,
                    error=error_text,
                )
        except Exception:
            # Never let DLQ persistence failures escape — the original work
            # has already been abandoned and the worker loop must keep going.
            self.logger.exception(
                "Failed to persist dead-letter row",
                worker=worker_name,
                item_key=resolved_item_key,
            )

    def _dlq_session_factory(self) -> Callable[[], Any]:
        """Hook so tests can inject an alternate session factory."""
        return AsyncSessionLocal

    @staticmethod
    async def _record_dead_letter(
        session: AsyncSession,
        *,
        worker_name: str,
        item_key: str,
        payload: dict[str, Any],
        error: str | None,
    ) -> FailedJob:
        """Upsert a DLQ row keyed by ``(worker_name, item_key)``.

        Repeated failures bump ``attempts`` and refresh ``last_failed_at``
        rather than inserting duplicate rows. Status is reset to ``pending``
        on re-failure so previously-retried-but-failed-again items resurface
        in the inspector.
        """
        now = datetime.now(UTC)
        existing_q = select(FailedJob).where(
            FailedJob.worker_name == worker_name,
            FailedJob.item_key == item_key,
        )
        existing = (await session.execute(existing_q)).scalar_one_or_none()

        if existing is None:
            row = FailedJob(
                worker_name=worker_name,
                item_key=item_key,
                payload=payload,
                error=error,
                attempts=1,
                first_failed_at=now,
                last_failed_at=now,
                status=FAILED_JOB_STATUS_PENDING,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

        await session.execute(
            update(FailedJob)
            .where(FailedJob.id == existing.id)
            .values(
                attempts=FailedJob.attempts + 1,
                last_failed_at=now,
                error=error,
                payload=payload,
                status=FAILED_JOB_STATUS_PENDING,
            )
        )
        await session.commit()
        await session.refresh(existing)
        return existing
