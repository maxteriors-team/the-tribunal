"""Drip campaign API endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.drip_campaign import (
    DripCampaign,
    DripCampaignStatus,
    DripEnrollment,
    DripEnrollmentStatus,
)
from app.models.workspace import Workspace
from app.schemas.drip_campaign import (
    DripCampaignCreate,
    DripCampaignResponse,
    DripCampaignStats,
    DripEnrollmentResponse,
    EnrollContactsRequest,
)
from app.services.reactivation.drip_runner import enroll_contacts

router = APIRouter()
logger = structlog.get_logger()


@router.get("", response_model=list[DripCampaignResponse])
async def list_drip_campaigns(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[DripCampaignResponse]:
    """List all drip campaigns for a workspace."""
    result = await db.execute(
        select(DripCampaign)
        .where(DripCampaign.workspace_id == workspace_id)
        .order_by(DripCampaign.created_at.desc())
    )
    campaigns = result.scalars().all()
    return [DripCampaignResponse.model_validate(c) for c in campaigns]


@router.post(
    "",
    response_model=DripCampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_drip_campaign(
    workspace_id: uuid.UUID,
    request: DripCampaignCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> DripCampaignResponse:
    """Create a new drip campaign."""
    campaign = DripCampaign(
        workspace_id=workspace_id,
        agent_id=request.agent_id,
        name=request.name,
        description=request.description,
        from_phone_number=request.from_phone_number,
        sequence_steps=[s.model_dump() for s in request.sequence_steps],
        sending_hours_start=request.sending_hours_start,
        sending_hours_end=request.sending_hours_end,
        sending_days=request.sending_days,
        timezone=request.timezone,
        messages_per_minute=request.messages_per_minute,
        status=DripCampaignStatus.DRAFT,
    )

    if request.auto_start:
        campaign.status = DripCampaignStatus.ACTIVE
        campaign.started_at = datetime.now(UTC)

    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    logger.info(
        "drip_campaign_created",
        campaign_id=str(campaign.id),
        workspace_id=str(workspace_id),
    )
    return DripCampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}", response_model=DripCampaignResponse)
async def get_drip_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> DripCampaignResponse:
    """Get a drip campaign by ID."""
    campaign = await _get_campaign(workspace_id, campaign_id, db)
    return DripCampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/start", response_model=DripCampaignResponse)
async def start_drip_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> DripCampaignResponse:
    """Start a drip campaign."""
    campaign = await _get_campaign(workspace_id, campaign_id, db)

    if campaign.status not in (
        DripCampaignStatus.DRAFT,
        DripCampaignStatus.PAUSED,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start campaign in '{campaign.status}' status",
        )

    campaign.status = DripCampaignStatus.ACTIVE
    campaign.started_at = campaign.started_at or datetime.now(UTC)
    await db.commit()
    await db.refresh(campaign)

    return DripCampaignResponse.model_validate(campaign)


@router.post("/{campaign_id}/pause", response_model=DripCampaignResponse)
async def pause_drip_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> DripCampaignResponse:
    """Pause a drip campaign."""
    campaign = await _get_campaign(workspace_id, campaign_id, db)

    if campaign.status != DripCampaignStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only pause active campaigns",
        )

    campaign.status = DripCampaignStatus.PAUSED
    await db.commit()
    await db.refresh(campaign)

    return DripCampaignResponse.model_validate(campaign)


@router.get("/{campaign_id}/stats", response_model=DripCampaignStats)
async def get_drip_campaign_stats(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> DripCampaignStats:
    """Get aggregated stats for a drip campaign."""
    campaign = await _get_campaign(workspace_id, campaign_id, db)

    # Count by status
    status_counts = await db.execute(
        select(
            DripEnrollment.status,
            func.count(DripEnrollment.id),
        )
        .where(DripEnrollment.drip_campaign_id == campaign_id)
        .group_by(DripEnrollment.status)
    )
    counts: dict[str, int] = {
        row[0]: row[1] for row in status_counts.all()
    }

    total = campaign.total_enrolled or 1  # avoid division by zero
    responded = counts.get(DripEnrollmentStatus.RESPONDED, 0)
    completed = counts.get(DripEnrollmentStatus.COMPLETED, 0)

    return DripCampaignStats(
        total_enrolled=campaign.total_enrolled,
        active=counts.get(DripEnrollmentStatus.ACTIVE, 0),
        responded=responded,
        completed=completed,
        cancelled=counts.get(DripEnrollmentStatus.CANCELLED, 0),
        messages_sent=campaign.total_messages_sent,
        appointments_booked=campaign.total_appointments_booked,
        response_rate=round(responded / total * 100, 1),
        completion_rate=round(completed / total * 100, 1),
    )


@router.post("/{campaign_id}/enroll", response_model=dict[str, int])
async def enroll_contacts_endpoint(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    request: EnrollContactsRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Enroll contacts in a drip campaign."""
    campaign = await _get_campaign(workspace_id, campaign_id, db)
    count = await enroll_contacts(campaign, request.contact_ids, db)
    await db.commit()
    return {"enrolled": count}


@router.get(
    "/{campaign_id}/enrollments",
    response_model=list[DripEnrollmentResponse],
)
async def list_enrollments(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[DripEnrollmentResponse]:
    """List enrollments for a drip campaign."""
    await _get_campaign(workspace_id, campaign_id, db)

    result = await db.execute(
        select(DripEnrollment)
        .where(DripEnrollment.drip_campaign_id == campaign_id)
        .order_by(DripEnrollment.enrolled_at.desc())
        .limit(200)
    )
    enrollments = result.scalars().all()
    return [DripEnrollmentResponse.model_validate(e) for e in enrollments]


async def _get_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    db: AsyncSession,
) -> DripCampaign:
    """Get campaign or raise 404."""
    result = await db.execute(
        select(DripCampaign).where(
            DripCampaign.id == campaign_id,
            DripCampaign.workspace_id == workspace_id,
        )
    )
    campaign = result.scalar_one_or_none()
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Drip campaign not found",
        )
    return campaign
