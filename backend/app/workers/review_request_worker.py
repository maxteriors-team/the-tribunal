"""Review-request dispatch worker.

Polls for PENDING review requests whose per-workspace send delay has elapsed and
dispatches the review-request SMS via the shared :class:`ReviewService`. Keeping
the actual send out of appointment outcome handling means a happy customer is asked for a
review a sensible interval after the job (configurable per workspace) rather than
the instant the meeting ends.
"""

from app.db.session import system_session
from app.services.idempotency import derive_worker_retry_key
from app.services.reviews import ReviewService
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

MAX_REQUESTS_PER_TICK = 20


class ReviewRequestWorker(RetryableWorker, BaseWorker):
    """Background worker that dispatches due review-request SMS."""

    POLL_INTERVAL_SECONDS = 120
    COMPONENT_NAME = "review_request_worker"
    MAX_CONCURRENCY = 5
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Find and dispatch review requests whose delay window has elapsed."""
        async with system_session("review_request_worker sweeps every workspace") as db:
            service = ReviewService(db)
            due = await service.find_due_pending_requests(limit=MAX_REQUESTS_PER_TICK)

            if not due:
                return

            self.logger.info("dispatching_review_requests", count=len(due))

            for review_request, workspace, contact in due:
                await self.execute_with_retry(
                    service.dispatch_request,
                    workspace,
                    review_request,
                    contact,
                    item_key=derive_worker_retry_key("review_request", review_request.id),
                )
                self.record_items_processed()


# Singleton registry (consistent with all other workers)
_registry = WorkerRegistry(ReviewRequestWorker)
start_review_request_worker = _registry.start
stop_review_request_worker = _registry.stop
get_review_request_worker = _registry.get
