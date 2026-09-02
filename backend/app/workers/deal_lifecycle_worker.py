"""Periodic maintenance for configured deal-lifecycle workflows."""

from app.db.session import system_session
from app.services.opportunities.deal_lifecycle_maintenance import (
    run_deal_lifecycle_maintenance,
)
from app.workers.base import BaseWorker, WorkerRegistry


class DealLifecycleWorker(BaseWorker):
    """Expire unpaid deals and enforce the daily New Lead cleanup."""

    POLL_INTERVAL_SECONDS = 300
    COMPONENT_NAME = "deal_lifecycle_worker"

    async def _process_items(self) -> None:
        async with system_session("deal lifecycle worker sweeps configured workspaces") as db:
            result = await run_deal_lifecycle_maintenance(db)
            await db.commit()
        processed = result.expired_invoices + result.nudges_created + result.nudges_resolved
        self.record_items_processed(processed)
        if processed:
            self.logger.info(
                "Deal lifecycle maintenance completed",
                expired_invoices=result.expired_invoices,
                nudges_created=result.nudges_created,
                nudges_resolved=result.nudges_resolved,
            )


_registry = WorkerRegistry(DealLifecycleWorker)
start_deal_lifecycle_worker = _registry.start
stop_deal_lifecycle_worker = _registry.stop
get_deal_lifecycle_worker = _registry.get
