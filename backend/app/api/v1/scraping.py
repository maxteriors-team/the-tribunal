"""Lead scraping endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.contact import Contact
from app.schemas.scraping import (
    BusinessResult,
    BusinessSearchRequest,
    BusinessSearchResponse,
    ImportLeadsRequest,
    ImportLeadsResponse,
)
from app.services.rate_limiting.scraping_limiter import enforce_scraping_rate_limit
from app.services.scraping.google_places import GooglePlacesError, GooglePlacesService
from app.services.tags import TagService
from app.utils.phone import normalize_phone_safe

router = APIRouter()


@router.post("/search", response_model=BusinessSearchResponse)
async def search_businesses(
    http_request: Request,
    workspace_id: uuid.UUID,
    request: BusinessSearchRequest,
    current_user: CurrentUser,
    db: DB,
) -> BusinessSearchResponse:
    """Search for businesses using Google Places API.

    Returns a list of businesses matching the search query with their details.
    """
    # Verify workspace access
    await get_workspace(http_request, workspace_id, current_user, db)

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


@router.post("/import", response_model=ImportLeadsResponse)
async def import_leads(
    http_request: Request,
    workspace_id: uuid.UUID,
    request: ImportLeadsRequest,
    current_user: CurrentUser,
    db: DB,
) -> ImportLeadsResponse:
    """Import selected leads as contacts.

    Creates contacts from the selected business results.
    Skips duplicates based on phone number.
    """
    # Verify workspace access
    workspace = await get_workspace(http_request, workspace_id, current_user, db)

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
    skipped_duplicates = 0
    skipped_no_phone = 0
    errors: list[str] = []

    for lead in request.leads:
        # Skip if no phone number
        if not lead.phone_number:
            skipped_no_phone += 1
            continue

        # Normalize and check for duplicates
        normalized_phone = normalize_phone_safe(lead.phone_number)
        if not normalized_phone:
            skipped_no_phone += 1
            continue
        if normalized_phone in existing_phones:
            skipped_duplicates += 1
            continue

        try:
            # Build tags from business types
            tags = list(request.add_tags) if request.add_tags else []
            if lead.types:
                # Add first 3 business types as tags
                type_tags = [t.replace("_", " ").title() for t in lead.types[:3]]
                tags.extend(type_tags)

            # Create contact
            contact = Contact(
                workspace_id=workspace.id,
                first_name="Owner",
                company_name=lead.name,
                phone_number=normalized_phone,
                status=request.default_status,
                source="scraped",
                notes=_format_business_notes(lead),
            )
            db.add(contact)
            await db.flush()
            await TagService(db).add_tags_to_contact(
                workspace_id=workspace.id,
                contact_id=contact.id,
                names=tags,
            )
            existing_phones.add(normalized_phone)
            imported += 1

        except Exception as e:
            errors.append(f"Failed to import {lead.name}: {e!s}")

    if imported > 0:
        await db.commit()

    return ImportLeadsResponse(
        total=len(request.leads),
        imported=imported,
        skipped_duplicates=skipped_duplicates,
        skipped_no_phone=skipped_no_phone,
        errors=errors[:10],  # Limit errors in response
    )
