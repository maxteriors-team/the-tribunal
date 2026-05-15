"""Drip campaign worker — polls every 15 minutes to advance enrollments.

Delegates all logic to drip_runner.process_active_drip_campaigns().
"""

from app.db.session import AsyncSessionLocal
from app.services.reactivation.drip_runner import process_active_drip_campaigns
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker


class DripCampaignWorker(RetryableWorker, BaseWorker):
    """Background worker for drip campaign step advancement."""

    POLL_INTERVAL_SECONDS = 900  # 15 minutes
    COMPONENT_NAME = "drip_campaign_worker"
    max_retries = 3
    backoff_base_seconds = 2.0

    async def _process_items(self) -> None:
        """Process all active drip campaigns."""
        async with AsyncSessionLocal() as db:
            await self.execute_with_retry(
                process_active_drip_campaigns,
                db,
                item_key="drip_campaigns_cycle",
            )


# Singleton registry
_registry = WorkerRegistry(DripCampaignWorker)
start_drip_campaign_worker = _registry.start
stop_drip_campaign_worker = _registry.stop
get_drip_campaign_worker = _registry.get
