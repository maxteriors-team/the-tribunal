"""Recurring-job materializer worker.

Periodically turns active recurring job templates into concrete scheduled jobs as
their due dates approach. The heavy lifting (and all idempotency) lives in
:meth:`app.services.recurring_jobs.RecurringJobService.materialize_due`, which
generates each occurrence exactly once per period regardless of how often this
worker ticks — so a missed tick (deploy, restart) simply catches up on the next
run, and a double tick creates nothing extra.

Single-process safe: the deployment runs one ``backend-api`` so there is no
multi-replica double-fire to guard against beyond the per-occurrence idempotency
the service already enforces.
"""

from app.core.config import settings
from app.db.session import AsyncSessionLocal, transaction_boundary
from app.services.recurring_jobs import RecurringJobService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class RecurringJobWorker(RetryableWorker, BaseWorker):
    """Background worker that materializes due recurring jobs across workspaces."""

    POLL_INTERVAL_SECONDS = getattr(settings, "recurring_job_poll_interval", 3600)
    COMPONENT_NAME = "recurring_job_worker"
    # One coherent generation pass per tick — no per-item fan-out.
    MAX_CONCURRENCY = 1
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Generate every recurring job whose next occurrence is due."""
        created = await self.execute_with_retry(self._materialize, item_key="recurring_jobs")
        if created:
            self.record_items_processed(created)

    async def _materialize(self) -> int:
        """Run one materialization pass in its own committed transaction."""
        async with AsyncSessionLocal() as db, transaction_boundary(db):
            created = await RecurringJobService(db).materialize_due()
        if created:
            self.logger.info("recurring_jobs_materialized", count=created)
        return created


# Singleton registry (consistent with all other workers)
_registry = WorkerRegistry(RecurringJobWorker)
start_recurring_job_worker = _registry.start
stop_recurring_job_worker = _registry.stop
get_recurring_job_worker = _registry.get
