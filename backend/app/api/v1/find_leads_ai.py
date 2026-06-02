"""Find Leads AI endpoints with synchronous website enrichment."""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_workspace
from app.core.config import settings
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.schemas.find_leads_ai import (
    AIImportLeadsRequest,
    AIImportLeadsResponse,
    LeadImportDetail,
)
from app.schemas.scraping import (
    BusinessResult,
    BusinessSearchRequest,
    BusinessSearchResponse,
)
from app.services.rate_limiting.scraping_limiter import enforce_scraping_rate_limit
from app.services.scraping.enrichment_service import enrich_contact_data
from app.services.scraping.google_places import GooglePlacesError, GooglePlacesService
from app.services.tags import TagService
from app.utils.phone import normalize_phone_safe

router = APIRouter()


@router.post("/search", response_model=BusinessSearchResponse)
async def search_businesses_ai(
    workspace_id: uuid.UUID,
    request: BusinessSearchRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> BusinessSearchResponse:
    """Search for businesses using Google Places API.

    Same as regular Find Leads, but available at the /find-leads-ai endpoint.
    Returns a list of businesses matching the search query with their details.
    """
    # Per-workspace cap on paid Google Places calls (raises 429 if exceeded).
    await enforce_scraping_rate_limit(workspace_id)

    service = GooglePlacesService()
    try:
        results = await service.search_businesses(
            query=request.query,
            max_results=request.max_results,
        )

        business_results = [BusinessResult(**r) for r in results]

        return BusinessSearchResponse(
            results=business_results,
            total_found=len(business_results),
            query=request.query,
        )
    except GooglePlacesError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        ) from e
    finally:
        await service.close()


def _format_business_notes(lead: BusinessResult) -> str:
    """Format business context as notes."""
    lines = []

    # Categories
    if lead.types:
        # Clean up type names (remove underscores, title case)
        categories = [t.replace("_", " ").title() for t in lead.types[:5]]
        lines.append(f"Category: {', '.join(categories)}")

    # Address
    if lead.address:
        lines.append(f"Address: {lead.address}")

    # Rating
    if lead.rating:
        rating_str = f"{lead.rating}/5"
        if lead.review_count > 0:
            rating_str += f" ({lead.review_count} reviews)"
        lines.append(f"Rating: {rating_str}")

    # Website
    lines.append(f"Website: {lead.website or 'None'}")

    return "\n".join(lines)


@router.post("/import", response_model=AIImportLeadsResponse)
async def import_leads_ai(  # noqa: PLR0912, PLR0915
    workspace_id: uuid.UUID,
    request: AIImportLeadsRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AIImportLeadsResponse:
    """Import selected leads as contacts with parallel AI enrichment.

    Enrichment happens synchronously during import:
    - Leads are enriched in parallel (up to 10 concurrent) before saving
    - Only leads with a lead score >= min_lead_score are imported
    - Leads below the threshold are rejected immediately
    - No background processing for new imports
    """

    # Get existing phone numbers for duplicate detection
    phone_result = await db.execute(
        select(Contact.phone_number).where(Contact.workspace_id == workspace.id)
    )
    existing_phones: set[str] = set()
    for row in phone_result:
        if row[0]:
            normalized = normalize_phone_safe(row[0])
            if normalized:
                existing_phones.add(normalized)

    imported = 0
    rejected_low_score = 0
    enrichment_failed = 0
    skipped_duplicates = 0
    skipped_no_phone = 0
    errors: list[str] = []
    lead_details: list[LeadImportDetail] = []

    # Separate leads needing enrichment from those that can be skipped early
    leads_to_enrich: list[tuple[BusinessResult, str]] = []

    for lead in request.leads:
        if not lead.phone_number:
            skipped_no_phone += 1
            lead_details.append(LeadImportDetail(name=lead.name, status="skipped_no_phone"))
            continue

        normalized_phone = normalize_phone_safe(lead.phone_number)
        if not normalized_phone:
            skipped_no_phone += 1
            lead_details.append(LeadImportDetail(name=lead.name, status="skipped_no_phone"))
            continue
        if normalized_phone in existing_phones:
            skipped_duplicates += 1
            lead_details.append(LeadImportDetail(name=lead.name, status="skipped_duplicate"))
            continue

        # Mark phone as seen to prevent duplicates within this batch
        existing_phones.add(normalized_phone)
        leads_to_enrich.append((lead, normalized_phone))

    # Parallel enrichment with semaphore
    semaphore = asyncio.Semaphore(10)

    async def enrich_single(lead: BusinessResult, normalized_phone: str) -> dict[str, Any]:
        """Enrich a single lead with semaphore rate limiting."""
        async with semaphore:
            google_places_data: dict[str, Any] = {
                "google_places": {
                    "place_id": lead.place_id,
                    "rating": lead.rating,
                    "review_count": lead.review_count,
                    "types": lead.types,
                    "business_status": lead.business_status,
                },
            }

            enrichment_result: dict[str, Any] = {
                "business_intel": google_places_data,
                "linkedin_url": None,
                "lead_score": 0,
                "revenue_tier": None,
                "decision_maker_name": None,
                "decision_maker_title": None,
                "enrichment_status": "skipped",
                "error": None,
            }

            if request.enable_enrichment and lead.website:
                enrichment_result = await enrich_contact_data(
                    website_url=lead.website,
                    company_name=lead.name,
                    google_places_data=google_places_data,
                    enable_ai=settings.enable_ai_enrichment,
                )

            return {
                "lead": lead,
                "normalized_phone": normalized_phone,
                "enrichment": enrichment_result,
            }

    # Run all enrichments in parallel
    enrichment_results: list[dict[str, Any] | BaseException] = []
    if leads_to_enrich:
        enrichment_tasks = [enrich_single(lead, phone) for lead, phone in leads_to_enrich]
        enrichment_results = await asyncio.gather(*enrichment_tasks, return_exceptions=True)

    # Process results and create contacts
    for i, result in enumerate(enrichment_results):
        if isinstance(result, BaseException):
            lead_name = leads_to_enrich[i][0].name if i < len(leads_to_enrich) else "unknown"
            error_type = type(result).__name__
            errors.append(f"Enrichment failed for {lead_name}: {error_type}: {result!s}")
            enrichment_failed += 1
            lead_details.append(LeadImportDetail(name=lead_name, status="enrichment_failed"))
            continue

        lead = result["lead"]
        enrichment_result = result["enrichment"]

        if enrichment_result["enrichment_status"] == "failed":
            enrichment_failed += 1
            lead_details.append(
                LeadImportDetail(
                    name=lead.name,
                    status="enrichment_failed",
                )
            )
            continue

        lead_score: int = enrichment_result["lead_score"]
        revenue_tier: str | None = enrichment_result.get("revenue_tier")
        dm_name: str | None = enrichment_result.get("decision_maker_name")
        dm_title: str | None = enrichment_result.get("decision_maker_title")

        if lead_score < request.min_lead_score:
            rejected_low_score += 1
            lead_details.append(
                LeadImportDetail(
                    name=lead.name,
                    status="rejected_low_score",
                    lead_score=lead_score,
                    revenue_tier=revenue_tier,
                    decision_maker_name=dm_name,
                    decision_maker_title=dm_title,
                )
            )
            continue

        try:
            tags = list(request.add_tags) if request.add_tags else []
            if lead.types:
                type_tags = [t.replace("_", " ").title() for t in lead.types[:3]]
                tags.extend(type_tags)

            # Use decision maker name if found, otherwise "Owner"
            first_name = dm_name if dm_name else "Owner"

            normalized_phone = result["normalized_phone"]
            contact = Contact(
                workspace_id=workspace.id,
                first_name=first_name,
                company_name=lead.name,
                phone_number=normalized_phone,
                status=request.default_status,
                source="scraped_ai",
                notes=_format_business_notes(lead),
                website_url=lead.website,
                linkedin_url=enrichment_result["linkedin_url"],
                enrichment_status=enrichment_result["enrichment_status"],
                business_intel=enrichment_result["business_intel"],
                lead_score=lead_score,
                enriched_at=(
                    None
                    if enrichment_result["enrichment_status"] == "skipped"
                    else datetime.now(UTC)
                ),
            )
            db.add(contact)
            await db.flush()
            await TagService(db).add_tags_to_contact(
                workspace_id=workspace.id,
                contact_id=contact.id,
                names=tags,
            )
            imported += 1
            lead_details.append(
                LeadImportDetail(
                    name=lead.name,
                    status="imported",
                    lead_score=lead_score,
                    revenue_tier=revenue_tier,
                    decision_maker_name=dm_name,
                    decision_maker_title=dm_title,
                )
            )
        except Exception as e:
            errors.append(f"Failed to import {lead.name}: {e!s}")

    if imported > 0:
        await db.commit()

    return AIImportLeadsResponse(
        total=len(request.leads),
        imported=imported,
        rejected_low_score=rejected_low_score,
        enrichment_failed=enrichment_failed,
        skipped_duplicates=skipped_duplicates,
        skipped_no_phone=skipped_no_phone,
        queued_for_enrichment=0,
        errors=errors[:10],
        lead_details=lead_details,
    )
