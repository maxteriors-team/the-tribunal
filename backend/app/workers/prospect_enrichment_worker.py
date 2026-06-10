"""Prospect enrichment worker.

Enriches :class:`LeadProspect` rows (status ``new`` -> ``enriched``) — the gap
distinct from the contact ``enrichment_worker``, which only enriches ``Contact``
rows. For each prospect it:

1. Traces public contact identifiers from the landing website (email / phone /
   socials) via :class:`ContactTracer`.
2. Enriches business intel + lead score from the website via the shared
   ``enrich_contact_data`` service.
3. Optionally asks a config-gated email-finder (Hunter/Apollo) when no public
   email was found.
4. Writes append-only :class:`LeadEnrichmentResult` audit rows and updates the
   prospect's encrypted identifiers + ``lead_score``.

PII (email/phone) is written to the prospect's encrypted columns + lookup
hashes, never to plaintext.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal
from app.models.lead_prospect import (
    EnrichmentProvider,
    EnrichmentResultStatus,
    LeadEnrichmentResult,
    LeadProspect,
    ProspectStatus,
)
from app.services.ad_intelligence import email_finder
from app.services.ad_intelligence.contact_tracing import ContactTracer, TracedContact
from app.services.scraping.enrichment_service import enrich_contact_data
from app.workers.base import BaseWorker, WorkerRegistry

MAX_PROSPECTS_PER_TICK = 5


class ProspectEnrichmentWorker(BaseWorker):
    """Enrich new lead prospects with traced contact + website intel."""

    POLL_INTERVAL_SECONDS = getattr(settings, "prospect_enrichment_poll_interval", 30)
    COMPONENT_NAME = "prospect_enrichment_worker"
    MAX_CONCURRENCY = 3

    async def _process_items(self) -> None:
        async with AsyncSessionLocal() as db:
            prospects = await self._claim_prospects(db)
            if not prospects:
                return
            self.logger.debug("enriching_prospects", count=len(prospects))
            for prospect in prospects:
                await self._enrich(db, prospect)
            await db.commit()

    async def _claim_prospects(self, db: AsyncSession) -> list[LeadProspect]:
        result = await db.execute(
            select(LeadProspect)
            .where(LeadProspect.status == ProspectStatus.NEW)
            .order_by(LeadProspect.lead_score.desc(), LeadProspect.discovered_at)
            .limit(MAX_PROSPECTS_PER_TICK)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def _enrich(self, db: AsyncSession, prospect: LeadProspect) -> None:
        log = self.logger.bind(prospect_id=str(prospect.id))
        prospect.status = ProspectStatus.ENRICHING
        prospect.enrichment_attempts = (prospect.enrichment_attempts or 0) + 1

        try:
            traced = await self._trace_contact(db, prospect)
            await self._enrich_business_intel(db, prospect)
            await self._maybe_find_email(db, prospect, traced)

            prospect.status = ProspectStatus.ENRICHED
            prospect.last_enriched_at = datetime.now(UTC)
            log.info(
                "prospect_enriched",
                has_email=prospect.has_email,
                has_phone=prospect.has_phone,
                lead_score=prospect.lead_score,
            )
            self.record_items_processed(1)
        except Exception as exc:  # noqa: BLE001 - record + continue batch
            prospect.status = ProspectStatus.NEW
            prospect.last_failed_at = datetime.now(UTC)
            log.exception("prospect_enrichment_failed", error=str(exc))

    async def _trace_contact(self, db: AsyncSession, prospect: LeadProspect) -> TracedContact:
        """Trace email/phone/socials from the prospect's landing website."""
        if not (prospect.website_url or prospect.website_host):
            return TracedContact(provenance={"traced": False, "reason": "no_website"})

        tracer = ContactTracer()
        try:
            traced = await tracer.trace(
                website_url=prospect.website_url,
                website_host=prospect.website_host,
            )
        finally:
            await tracer.close()

        extracted: dict[str, Any] = {}
        if traced.email and not prospect.email_hash:
            prospect.email = traced.email
            prospect.email_hash = hash_value(traced.email)
            extracted["email"] = True
        if traced.phone_number and not prospect.phone_hash:
            prospect.phone_number = traced.phone_number
            prospect.phone_hash = hash_phone(traced.phone_number)
            extracted["phone"] = True
        if traced.linkedin_url and not prospect.linkedin_url:
            prospect.linkedin_url = traced.linkedin_url
            extracted["linkedin"] = True

        self._record_result(
            db,
            prospect,
            provider=EnrichmentProvider.AD_LIBRARY_CONTACT_TRACE,
            status=(
                EnrichmentResultStatus.SUCCESS if traced.has_any else EnrichmentResultStatus.PARTIAL
            ),
            extracted=extracted,
            response={"provenance": traced.provenance, "social_links": traced.social_links},
        )
        return traced

    async def _enrich_business_intel(self, db: AsyncSession, prospect: LeadProspect) -> None:
        """Enrich business intel + lead score from the prospect's website."""
        if not prospect.website_url:
            return
        result = await enrich_contact_data(
            website_url=prospect.website_url,
            company_name=prospect.company_name or "",
            google_places_data={},
            enable_ai=settings.enable_ai_enrichment,
        )
        status = (
            EnrichmentResultStatus.SUCCESS
            if result.get("enrichment_status") == "enriched"
            else EnrichmentResultStatus.FAILED
        )
        new_score = int(result.get("lead_score") or 0)
        score_delta = max(0, new_score - prospect.lead_score)
        prospect.lead_score = max(prospect.lead_score, new_score)
        if not prospect.linkedin_url and result.get("linkedin_url"):
            prospect.linkedin_url = result["linkedin_url"]

        self._record_result(
            db,
            prospect,
            provider=EnrichmentProvider.WEBSITE_SCRAPER,
            status=status,
            extracted={"lead_score": new_score},
            response={"enrichment_status": result.get("enrichment_status")},
            score_delta=score_delta,
        )

    async def _maybe_find_email(
        self, db: AsyncSession, prospect: LeadProspect, traced: TracedContact
    ) -> None:
        """Ask a config-gated email-finder when no public email was traced."""
        if prospect.email_hash or not email_finder.is_enabled():
            return
        domain = prospect.website_host or traced.website_host
        if not domain:
            return
        found = await email_finder.find_email_for_domain(domain, full_name=prospect.full_name)
        if found is None:
            self._record_result(
                db,
                prospect,
                provider=EnrichmentProvider.EMAIL_LOOKUP,
                status=EnrichmentResultStatus.FAILED,
                extracted={},
                response={"domain": domain},
            )
            return
        prospect.email = found.email
        prospect.email_hash = hash_value(found.email)
        self._record_result(
            db,
            prospect,
            provider=EnrichmentProvider.EMAIL_LOOKUP,
            status=EnrichmentResultStatus.SUCCESS,
            extracted={"email": True, "confidence": found.confidence},
            response={"domain": domain, "source": found.source},
        )

    def _record_result(
        self,
        db: AsyncSession,
        prospect: LeadProspect,
        *,
        provider: EnrichmentProvider,
        status: EnrichmentResultStatus,
        extracted: dict[str, Any],
        response: dict[str, Any] | None = None,
        score_delta: int = 0,
    ) -> None:
        db.add(
            LeadEnrichmentResult(
                workspace_id=prospect.workspace_id,
                prospect_id=prospect.id,
                mission_id=prospect.mission_id,
                provider=provider,
                status=status,
                extracted=extracted,
                response_payload=response,
                score_delta=score_delta,
            )
        )


_registry = WorkerRegistry(ProspectEnrichmentWorker)
start_prospect_enrichment_worker = _registry.start
stop_prospect_enrichment_worker = _registry.stop
get_prospect_enrichment_worker = _registry.get
