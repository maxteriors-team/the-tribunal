"""Shared enrichment service for synchronous and asynchronous contact enrichment.

This service provides the core enrichment logic that can be called:
1. Synchronously during AI Find Leads import (before saving to database)
2. Asynchronously by the EnrichmentWorker (for existing pending contacts)
"""

from datetime import UTC, datetime
from typing import Any, Final

import structlog

from app.core.config import settings
from app.services.scraping.ai_content_analyzer import AIContentAnalyzerService
from app.services.scraping.lead_scorer import compute_lead_score_breakdown
from app.services.scraping.website_scraper import WebsiteScraperError, WebsiteScraperService

logger = structlog.get_logger()

# Opaque, non-reflective failure text. Upstream exception strings can carry
# internal network detail (and are attacker-steerable via the submitted URL),
# and this value is both persisted in ``business_intel`` and re-served to API
# callers via ``ContactResponse.business_intel`` / the import ``errors[]`` list.
# Full detail is logged server-side instead.
ENRICHMENT_ERROR_MESSAGE: Final[str] = "Website enrichment failed"


async def enrich_contact_data(
    website_url: str,
    company_name: str,
    google_places_data: dict[str, Any],
    enable_ai: bool = True,
) -> dict[str, Any]:
    """Enrich a contact with website data synchronously.

    Args:
        website_url: The website URL to scrape
        company_name: The company name for context
        google_places_data: Google Places data to include in business_intel
        enable_ai: Whether to enable AI content analysis

    Returns:
        Dictionary with keys:
            - business_intel: Combined data from all sources
            - linkedin_url: Extracted LinkedIn URL or None
            - lead_score: Computed lead score (0-160)
            - enrichment_status: "enriched" or "failed"
            - error: Error message if failed, None otherwise
    """
    if not website_url:
        return {
            "business_intel": google_places_data,
            "linkedin_url": None,
            "lead_score": 0,
            "revenue_tier": None,
            "decision_maker_name": None,
            "decision_maker_title": None,
            "enrichment_status": "failed",
            "error": "No website URL provided",
        }

    scraper = WebsiteScraperService()
    ai_analyzer: AIContentAnalyzerService | None = None

    try:
        # Scrape website
        result = await scraper.scrape_website(website_url)

        # Extract data
        social_links: dict[str, Any] = result.get("social_links", {})
        website_meta: dict[str, Any] = result.get("website_meta", {})

        # Build business_intel JSONB
        business_intel: dict[str, Any] = google_places_data.copy()
        business_intel["social_links"] = social_links
        business_intel["website_meta"] = website_meta

        # Extract ad pixels from scrape result
        ad_pixels = result.get("ad_pixels", {})
        business_intel["ad_pixels"] = ad_pixels

        # Generate AI website summary if enabled
        html_content = result.get("html_content")
        if enable_ai and settings.enable_ai_enrichment and html_content:
            ai_analyzer = AIContentAnalyzerService()
            website_summary = await ai_analyzer.generate_website_summary(
                html_content=html_content,
                website_url=website_url,
                business_name=company_name,
            )
            if website_summary:
                business_intel["website_summary"] = website_summary.model_dump()

        # Compute lead score with breakdown
        score_data = compute_lead_score_breakdown(business_intel)
        lead_score = score_data["score"]

        # Store revenue tier in business_intel for later use
        business_intel["revenue_tier"] = score_data["revenue_tier"]
        business_intel["score_breakdown"] = score_data["breakdown"]

        return {
            "business_intel": business_intel,
            "linkedin_url": social_links.get("linkedin"),
            "lead_score": lead_score,
            "revenue_tier": score_data["revenue_tier"],
            "decision_maker_name": score_data.get("decision_maker_name"),
            "decision_maker_title": score_data.get("decision_maker_title"),
            "enrichment_status": "enriched",
            "error": None,
        }

    except WebsiteScraperError as e:
        logger.warning(
            "enrichment_scrape_failed",
            website_url=website_url,
            company_name=company_name,
            error_type=type(e).__name__,
            error=str(e),
        )
        # Store an opaque error in business_intel (see ENRICHMENT_ERROR_MESSAGE).
        business_intel = google_places_data.copy()
        business_intel["enrichment_error"] = ENRICHMENT_ERROR_MESSAGE
        business_intel["enrichment_failed_at"] = datetime.now(UTC).isoformat()

        return {
            "business_intel": business_intel,
            "linkedin_url": None,
            "lead_score": 0,
            "revenue_tier": None,
            "decision_maker_name": None,
            "decision_maker_title": None,
            "enrichment_status": "failed",
            "error": ENRICHMENT_ERROR_MESSAGE,
        }

    except Exception as e:
        # Unexpected error — full traceback server-side, opaque text to callers.
        logger.exception(
            "enrichment_unexpected_error",
            website_url=website_url,
            company_name=company_name,
            error_type=type(e).__name__,
        )
        business_intel = google_places_data.copy()
        business_intel["enrichment_error"] = ENRICHMENT_ERROR_MESSAGE
        business_intel["enrichment_failed_at"] = datetime.now(UTC).isoformat()

        return {
            "business_intel": business_intel,
            "linkedin_url": None,
            "lead_score": 0,
            "revenue_tier": None,
            "decision_maker_name": None,
            "decision_maker_title": None,
            "enrichment_status": "failed",
            "error": ENRICHMENT_ERROR_MESSAGE,
        }

    finally:
        await scraper.close()
