"""Prospect promotion worker.

Promotes enriched, qualified :class:`LeadProspect` rows into CRM contacts via
:class:`ProspectPromotionService` — closing the missing prospect -> contact
path. Only auto-promotes prospects that carry a phone number (the CRM Contact
model requires one) and pass the suppression/opt-out gate; the rest are left for
manual promotion via the API.

Poll-based with ``with_for_update(skip_locked=True)`` so replicas don't double
promote.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.lead_prospect import LeadProspect, ProspectStatus
from app.services.outbound.promotion import ProspectPromotionService
from app.workers.base import BaseWorker, WorkerRegistry

MAX_PROSPECTS_PER_TICK = 10
# Only auto-promote prospects that clear this lead score after enrichment.
MIN_PROMOTION_SCORE = 50


class ProspectPromotionWorker(BaseWorker):
    """Auto-promote enriched, qualified prospects into contacts."""

    POLL_INTERVAL_SECONDS = getattr(settings, "prospect_promotion_poll_interval", 30)
    COMPONENT_NAME = "prospect_promotion_worker"
    MAX_CONCURRENCY = 1

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            prospects = await self._claim_prospects(db)
            if not prospects:
                return
            service = ProspectPromotionService(db)
            self.logger.debug("promoting_prospects", count=len(prospects))
            for prospect in prospects:
                await self._promote(service, prospect)
            await db.commit()

    async def _claim_prospects(self, db: AsyncSession) -> list[LeadProspect]:
        result = await db.execute(
            select(LeadProspect)
            .where(
                LeadProspect.status == ProspectStatus.ENRICHED,
                LeadProspect.contact_id.is_(None),
                LeadProspect.lead_score >= MIN_PROMOTION_SCORE,
                LeadProspect.phone_hash.isnot(None),
            )
            .order_by(LeadProspect.lead_score.desc())
            .limit(MAX_PROSPECTS_PER_TICK)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def _promote(self, service: ProspectPromotionService, prospect: LeadProspect) -> None:
        log = self.logger.bind(prospect_id=str(prospect.id))
        try:
            result = await service.promote(prospect)
            if result.promoted:
                self.record_items_processed(1)
            else:
                log.debug("prospect_promotion_skipped", reason=result.skipped_reason)
        except Exception as exc:  # noqa: BLE001 - record + continue batch
            prospect.last_failed_at = datetime.now(UTC)
            log.exception("prospect_promotion_failed", error=str(exc))


_registry = WorkerRegistry(ProspectPromotionWorker)
start_prospect_promotion_worker = _registry.start
stop_prospect_promotion_worker = _registry.stop
get_prospect_promotion_worker = _registry.get
