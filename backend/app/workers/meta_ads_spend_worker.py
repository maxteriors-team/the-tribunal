"""Synchronize optional Meta Ads campaign spend into live ROI reporting."""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.workspace import WorkspaceIntegration
from app.services.dashboard.dashboard_service import invalidate_dashboard_cache
from app.services.lead_sources.meta_lead_ads_service import (
    META_LEAD_ADS_INTEGRATION,
    MetaLeadAdsError,
    sync_meta_campaign_spend,
)
from app.workers.base import BaseWorker, WorkerRegistry


class MetaAdsSpendWorker(BaseWorker):
    """Refresh provider-owned spend rows for configured Meta ad accounts."""

    POLL_INTERVAL_SECONDS = settings.meta_ads_spend_sync_interval_seconds
    COMPONENT_NAME = "meta_ads_spend_worker"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            integration_ids = (
                (
                    await db.execute(
                        select(WorkspaceIntegration.id)
                        .where(
                            WorkspaceIntegration.integration_type == META_LEAD_ADS_INTEGRATION,
                            WorkspaceIntegration.is_active.is_(True),
                        )
                        .order_by(WorkspaceIntegration.updated_at.asc())
                    )
                )
                .scalars()
                .all()
            )

        for integration_id in integration_ids:
            async with AsyncSessionLocal() as db:
                integration = await db.get(WorkspaceIntegration, integration_id)
                if integration is None or not integration.is_active:
                    continue
                try:
                    synced = await sync_meta_campaign_spend(db, integration)
                    await db.commit()
                except MetaLeadAdsError as exc:
                    await db.rollback()
                    self.logger.warning(
                        "meta_ads_spend_sync_failed",
                        workspace_id=str(integration.workspace_id),
                        error=str(exc),
                    )
                    continue
                except Exception:
                    await db.rollback()
                    self.logger.exception(
                        "meta_ads_spend_sync_unexpected_failure",
                        workspace_id=str(integration.workspace_id),
                    )
                    continue

                if synced:
                    await invalidate_dashboard_cache(integration.workspace_id)
                    self.record_items_processed(synced)
                    self.logger.info(
                        "meta_ads_spend_synced",
                        workspace_id=str(integration.workspace_id),
                        campaigns=synced,
                    )


_registry = WorkerRegistry(MetaAdsSpendWorker)
start_meta_ads_spend_worker = _registry.start
stop_meta_ads_spend_worker = _registry.stop
get_meta_ads_spend_worker = _registry.get
