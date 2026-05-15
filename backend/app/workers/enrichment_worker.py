"""Enrichment worker service for processing contact website scraping.

This background worker:
1. Polls for contacts with enrichment_status = "pending" and website_url IS NOT NULL
2. Scrapes website for social media links and metadata
3. Updates contact with linkedin_url, business_intel, enrichment_status
4. Handles errors gracefully with status tracking

The worker uses the shared enrichment_service for the core enrichment logic.
This allows the same logic to be used synchronously during AI Find Leads import.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.contact import Contact
from app.services.scraping.enrichment_service import enrich_contact_data
from app.workers.base import BaseWorker, WorkerRegistry
from app.workers.retryable import RetryableWorker

# Worker configuration
MAX_CONTACTS_PER_TICK = 10


class EnrichmentWorker(RetryableWorker, BaseWorker):
    """Background worker for enriching contacts with website data."""

    POLL_INTERVAL_SECONDS = getattr(settings, "enrichment_poll_interval", 30)
    COMPONENT_NAME = "enrichment_worker"
    max_retries = 3
    backoff_base_seconds = 2.0

    def __init__(self) -> None:
        super().__init__()

    async def _on_start(self) -> None:
        """Initialize worker (no services needed, they're created per-request)."""
        pass

    async def _on_stop(self) -> None:
        """Clean up (no services to clean up)."""
        pass

    async def _process_items(self) -> None:
        """Process all pending contacts for enrichment."""
        async with AsyncSessionLocal() as db:
            # Find contacts with pending enrichment that have a website
            result = await db.execute(
                select(Contact)
                .where(
                    and_(
                        Contact.enrichment_status == "pending",
                        Contact.website_url.isnot(None),
                        Contact.website_url != "",
                    )
                )
                .limit(MAX_CONTACTS_PER_TICK)
                .with_for_update(skip_locked=True)
            )
            contacts = result.scalars().all()

            if not contacts:
                return

            self.logger.debug("Processing pending enrichments", count=len(contacts))

            for contact in contacts:
                await self.execute_with_retry(
                    self._enrich_contact,
                    contact,
                    db,
                    item_key=f"contact:{contact.id}",
                )

            await db.commit()

    async def _enrich_contact(self, contact: Contact, db: AsyncSession) -> None:
        """Enrich a single contact with website data.

        Args:
            contact: Contact to enrich
            db: Database session
        """
        log = self.logger.bind(
            contact_id=contact.id,
            website_url=contact.website_url,
        )

        if not contact.website_url:
            contact.enrichment_status = "skipped"
            log.debug("No website URL, skipping")
            return

        try:
            log.info("Starting website enrichment")

            # Build google_places data from existing business_intel
            google_places_data: dict[str, Any] = {}
            if contact.business_intel:
                google_places_data = contact.business_intel.get("google_places", {})

            # Call the shared enrichment service
            enrichment_result = await enrich_contact_data(
                website_url=contact.website_url,
                company_name=contact.company_name or "",
                google_places_data=google_places_data,
                enable_ai=settings.enable_ai_enrichment,
            )

            # Update contact with enrichment results
            contact.business_intel = enrichment_result["business_intel"]
            contact.linkedin_url = enrichment_result["linkedin_url"]
            contact.lead_score = enrichment_result["lead_score"]
            contact.enrichment_status = enrichment_result["enrichment_status"]

            if enrichment_result["enrichment_status"] == "enriched":
                contact.enriched_at = datetime.now(UTC)

                # Extract info for logging
                business_intel = enrichment_result["business_intel"]
                social_links = business_intel.get("social_links", {})
                ad_pixels = business_intel.get("ad_pixels", {})

                log.info(
                    "Contact enriched successfully",
                    linkedin_found=bool(social_links.get("linkedin")),
                    social_count=sum(1 for v in social_links.values() if v),
                    lead_score=contact.lead_score,
                    has_ad_pixels=any(ad_pixels.values()),
                )
            else:
                log.warning(
                    "Enrichment failed",
                    error=enrichment_result.get("error"),
                )

        except Exception as e:
            log.exception("Unexpected enrichment error", error=str(e))

            business_intel = contact.business_intel or {}
            business_intel["enrichment_error"] = f"Unexpected error: {e}"
            business_intel["enrichment_failed_at"] = datetime.now(UTC).isoformat()
            contact.business_intel = business_intel

            contact.enrichment_status = "failed"


# Singleton registry
_registry = WorkerRegistry(EnrichmentWorker)
start_enrichment_worker = _registry.start
stop_enrichment_worker = _registry.stop
get_enrichment_worker = _registry.get
