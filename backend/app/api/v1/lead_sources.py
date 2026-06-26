"""Lead Sources CRUD endpoints, plus attribution campaigns, manual spend, and
the unknown-attribution cleanup queue."""

import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import DB, CurrentUser, get_workspace
from app.core.config import settings
from app.models.lead_source import LeadSource, LeadSourceCampaign, LeadSourceSpendEntry
from app.schemas.lead_source import (
    LeadSourceCampaignCreate,
    LeadSourceCampaignResponse,
    LeadSourceCreate,
    LeadSourceResponse,
    LeadSourceSpendEntryCreate,
    LeadSourceSpendEntryResponse,
    LeadSourceUpdate,
    UnattributedLeadResponse,
)
from app.services.dashboard.dashboard_service import invalidate_dashboard_cache
from app.services.lead_sources.attribution_service import (
    AttributionCleanupService,
    suggest_source_type_for_contact,
)

router = APIRouter()
campaigns_router = APIRouter()
spend_router = APIRouter()


def _to_response(ls: LeadSource) -> LeadSourceResponse:
    """Convert a LeadSource model to response with computed endpoint_url."""
    api_base = settings.api_base_url or "http://localhost:8000"
    return LeadSourceResponse(
        id=ls.id,
        workspace_id=ls.workspace_id,
        name=ls.name,
        public_key=ls.public_key,
        allowed_domains=ls.allowed_domains,
        enabled=ls.enabled,
        source_type=ls.source_type,
        action=ls.action,
        action_config=ls.action_config,
        created_at=ls.created_at,
        updated_at=ls.updated_at,
        endpoint_url=f"{api_base}/api/v1/p/leads/{ls.public_key}",
    )


@router.get("", response_model=list[LeadSourceResponse])
async def list_lead_sources(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> list[LeadSourceResponse]:
    """List all lead sources for a workspace."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource)
        .where(LeadSource.workspace_id == workspace_id)
        .order_by(LeadSource.created_at.desc())
    )
    sources = list(result.scalars().all())
    return [_to_response(s) for s in sources]


@router.post("", response_model=LeadSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    body: LeadSourceCreate,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceResponse:
    """Create a new lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    lead_source = LeadSource(
        workspace_id=workspace_id,
        name=body.name,
        allowed_domains=body.allowed_domains,
        source_type=body.source_type,
        action=body.action,
        action_config=body.action_config,
    )
    db.add(lead_source)
    await db.flush()
    await db.refresh(lead_source)
    await db.commit()

    return _to_response(lead_source)


@router.get("/unattributed", response_model=list[UnattributedLeadResponse])
async def list_unattributed_leads(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    limit: int = Query(100, ge=1, le=500),
) -> list[UnattributedLeadResponse]:
    """List captured leads that have no known first-touch lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    service = AttributionCleanupService(db)
    contacts = await service.list_unattributed(workspace_id, limit=limit)
    suggestions = await service.default_source_by_type(workspace_id)

    rows: list[UnattributedLeadResponse] = []
    for contact in contacts:
        suggested_type = suggest_source_type_for_contact(contact)
        rows.append(
            UnattributedLeadResponse(
                contact_id=contact.id,
                first_name=contact.first_name,
                last_name=contact.last_name,
                phone_number=contact.phone_number,
                email=contact.email,
                source=contact.source,
                created_at=contact.created_at,
                suggested_source_type=suggested_type,
                suggested_lead_source_id=(
                    suggestions.get(suggested_type) if suggested_type else None
                ),
            )
        )
    return rows


@router.get("/{lead_source_id}/campaigns", response_model=list[LeadSourceCampaignResponse])
async def list_lead_source_campaigns(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> list[LeadSourceCampaignResponse]:
    """List attribution campaigns nested under a lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSourceCampaign)
        .where(
            LeadSourceCampaign.workspace_id == workspace_id,
            LeadSourceCampaign.lead_source_id == lead_source_id,
        )
        .order_by(LeadSourceCampaign.created_at.desc())
    )
    return [LeadSourceCampaignResponse.model_validate(c) for c in result.scalars().all()]


@router.get("/{lead_source_id}", response_model=LeadSourceResponse)
async def get_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceResponse:
    """Get a single lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    return _to_response(lead_source)


@router.put("/{lead_source_id}", response_model=LeadSourceResponse)
async def update_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    body: LeadSourceUpdate,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceResponse:
    """Update a lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(lead_source, field, value)

    await db.flush()
    await db.refresh(lead_source)
    await db.commit()

    # source_type changes re-bucket this source's spend/jobs across channels,
    # which changes the ROI ranking — refresh the cached dashboard.
    if "source_type" in update_data:
        await invalidate_dashboard_cache(workspace_id)

    return _to_response(lead_source)


@router.delete("/{lead_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_source(
    request: Request,
    workspace_id: uuid.UUID,
    lead_source_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> None:
    """Delete a lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")

    await db.delete(lead_source)
    await db.commit()

    # Deleting a lead source cascade-deletes its spend entries, changing ROI —
    # refresh the cached dashboard.
    await invalidate_dashboard_cache(workspace_id)


# ---------------------------------------------------------------------------
# Attribution campaigns (mounted at /workspaces/{workspace_id}/lead-source-campaigns)
# ---------------------------------------------------------------------------


async def _get_owned_lead_source(
    db: DB, workspace_id: uuid.UUID, lead_source_id: uuid.UUID
) -> LeadSource:
    """Fetch a lead source scoped to the workspace or raise 404."""
    result = await db.execute(
        select(LeadSource).where(
            LeadSource.id == lead_source_id,
            LeadSource.workspace_id == workspace_id,
        )
    )
    lead_source = result.scalar_one_or_none()
    if not lead_source:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead source not found")
    return lead_source


@campaigns_router.post(
    "", response_model=LeadSourceCampaignResponse, status_code=status.HTTP_201_CREATED
)
async def create_lead_source_campaign(
    request: Request,
    workspace_id: uuid.UUID,
    body: LeadSourceCampaignCreate,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceCampaignResponse:
    """Create an attribution campaign under a lead source."""
    await get_workspace(request, workspace_id, current_user, db)
    await _get_owned_lead_source(db, workspace_id, body.lead_source_id)

    campaign = LeadSourceCampaign(
        workspace_id=workspace_id,
        **body.model_dump(),
    )
    db.add(campaign)
    await db.flush()
    await db.refresh(campaign)
    await db.commit()

    return LeadSourceCampaignResponse.model_validate(campaign)


@campaigns_router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_source_campaign(
    request: Request,
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> None:
    """Delete an attribution campaign."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSourceCampaign).where(
            LeadSourceCampaign.id == campaign_id,
            LeadSourceCampaign.workspace_id == workspace_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    await db.delete(campaign)
    await db.commit()


# ---------------------------------------------------------------------------
# Manual spend (mounted at /workspaces/{workspace_id}/lead-source-spend)
# ---------------------------------------------------------------------------


@spend_router.get("", response_model=list[LeadSourceSpendEntryResponse])
async def list_lead_source_spend(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    lead_source_id: uuid.UUID | None = Query(default=None),
) -> list[LeadSourceSpendEntryResponse]:
    """List manual spend entries, optionally filtered to one lead source."""
    await get_workspace(request, workspace_id, current_user, db)

    query = select(LeadSourceSpendEntry).where(LeadSourceSpendEntry.workspace_id == workspace_id)
    if lead_source_id is not None:
        query = query.where(LeadSourceSpendEntry.lead_source_id == lead_source_id)
    query = query.order_by(LeadSourceSpendEntry.spend_starts_on.desc())

    result = await db.execute(query)
    return [LeadSourceSpendEntryResponse.model_validate(s) for s in result.scalars().all()]


@spend_router.post(
    "", response_model=LeadSourceSpendEntryResponse, status_code=status.HTTP_201_CREATED
)
async def create_lead_source_spend(
    request: Request,
    workspace_id: uuid.UUID,
    body: LeadSourceSpendEntryCreate,
    current_user: CurrentUser,
    db: DB,
) -> LeadSourceSpendEntryResponse:
    """Record a manual ad/source spend entry."""
    await get_workspace(request, workspace_id, current_user, db)
    await _get_owned_lead_source(db, workspace_id, body.lead_source_id)

    if body.lead_source_campaign_id is not None:
        campaign_result = await db.execute(
            select(LeadSourceCampaign).where(
                LeadSourceCampaign.id == body.lead_source_campaign_id,
                LeadSourceCampaign.workspace_id == workspace_id,
                LeadSourceCampaign.lead_source_id == body.lead_source_id,
            )
        )
        if campaign_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Campaign not found for this lead source",
            )

    entry = LeadSourceSpendEntry(
        workspace_id=workspace_id,
        **body.model_dump(),
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    await db.commit()

    # Spend feeds ROI ranking — drop the cached dashboard so it reflects now.
    await invalidate_dashboard_cache(workspace_id)

    return LeadSourceSpendEntryResponse.model_validate(entry)


@spend_router.delete("/{spend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_source_spend(
    request: Request,
    workspace_id: uuid.UUID,
    spend_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> None:
    """Delete a manual spend entry."""
    await get_workspace(request, workspace_id, current_user, db)

    result = await db.execute(
        select(LeadSourceSpendEntry).where(
            LeadSourceSpendEntry.id == spend_id,
            LeadSourceSpendEntry.workspace_id == workspace_id,
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spend entry not found")

    await db.delete(entry)
    await db.commit()

    # Removing spend changes ROI — refresh the dashboard cache.
    await invalidate_dashboard_cache(workspace_id)
