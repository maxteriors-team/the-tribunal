"""Pre-booking campaign endpoints: offer terms, warm audience, slot reservations.

Mounted under an existing campaign
(``/workspaces/{workspace_id}/campaigns/{campaign_id}/pre-booking``) because that
is exactly what pre-booking is: an offer attached to a campaign that still sends
over SMS or email through the same workers, compliance checks and stats as every
other campaign. Nothing here creates a second campaign type.
"""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crud import get_or_404
from app.api.deps import (
    DB,
    CanReadCRM,
    CanWriteOutreach,
    CurrentUser,
    require_route_capabilities,
)
from app.core.permissions import Capability
from app.models.campaign import Campaign, CampaignContact, CampaignStatus
from app.models.prebooking import PreBookingCampaignConfig, PreBookingReservation
from app.schemas.prebooking import (
    PreBookingAudienceEnrollResponse,
    PreBookingAudiencePreview,
    PreBookingConfigCreate,
    PreBookingConfigResponse,
    PreBookingConfigUpdate,
    PreBookingLaunchRequest,
    PreBookingReservationResponse,
    PreBookingReserveRequest,
    PreBookingReserveResponse,
)
from app.services.prebooking.audience import PreBookingAudienceService
from app.services.prebooking.reservation_service import (
    ContactNotEligibleError,
    PreBookingError,
    PreBookingReservationService,
    SlotCapReachedError,
    load_config_for_campaign,
)
from app.services.prebooking.season import resolve_season_window

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.OUTREACH_WRITE))
    ]
)
# Workspace-level utilities that must answer *before* a campaign row exists —
# chiefly "how big is my warm database", which is the number that decides whether
# building the campaign is worth the afternoon.
workspace_router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.OUTREACH_WRITE))
    ]
)
logger = structlog.get_logger()


@workspace_router.get("/audience", response_model=PreBookingAudiencePreview)
async def preview_workspace_pre_booking_audience(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
    include_past_customers: bool = Query(True),
    include_unsold_quotes: bool = Query(True),
    include_prior_season_christmas: bool = Query(False),
    seasons_back: int | None = Query(None, gt=0, le=10),
    segment_id: uuid.UUID | None = Query(None),
) -> PreBookingAudiencePreview:
    """Size the warm database before a pre-booking campaign is created."""
    return await _audience_preview(
        db,
        workspace_id,
        campaign_id=None,
        include_past_customers=include_past_customers,
        include_unsold_quotes=include_unsold_quotes,
        include_prior_season_christmas=include_prior_season_christmas,
        seasons_back=seasons_back,
        segment_id=segment_id,
    )


async def _audience_preview(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None,
    include_past_customers: bool,
    include_unsold_quotes: bool,
    include_prior_season_christmas: bool,
    seasons_back: int | None,
    segment_id: uuid.UUID | None,
) -> PreBookingAudiencePreview:
    try:
        counts = await PreBookingAudienceService(db).preview(
            workspace_id,
            campaign_id,
            include_past_customers=include_past_customers,
            include_unsold_quotes=include_unsold_quotes,
            include_prior_season_christmas=include_prior_season_christmas,
            seasons_back=seasons_back,
            segment_id=segment_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return PreBookingAudiencePreview(
        total=counts.total,
        past_customers=counts.past_customers,
        unsold_quotes=counts.unsold_quotes,
        prior_season_christmas=counts.prior_season_christmas,
        excluded_opted_out=counts.excluded_opted_out,
        excluded_already_enrolled=counts.excluded_already_enrolled,
    )


async def _config_or_404(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> PreBookingCampaignConfig:
    config = await load_config_for_campaign(db, workspace_id, campaign_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This campaign has no pre-booking offer",
        )
    return config


async def _response(
    db: AsyncSession,
    config: PreBookingCampaignConfig,
    campaign: Campaign,
) -> PreBookingConfigResponse:
    """Build the offer response with live slot counts and the launch date."""
    usage = await PreBookingReservationService(db).slot_usage(config)
    response = PreBookingConfigResponse.model_validate(config)
    response.slots_held = usage.held
    response.slots_confirmed = usage.confirmed
    response.scheduled_start = campaign.scheduled_start
    return response


def _reject_past_season(start_month: int, end_month: int, year: int) -> None:
    """Refuse a season that has already finished.

    Pre-booking sells work that has not happened yet; a window that closed in
    March is a data-entry slip that would otherwise produce quotes promising
    dates in the past.
    """
    window = resolve_season_window(start_month=start_month, end_month=end_month, year=year)
    if window.end < datetime.now(UTC).date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"That season ended on {window.end.isoformat()}. "
                "Point this campaign at an upcoming season."
            ),
        )


@router.post("", response_model=PreBookingConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_pre_booking_offer(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: PreBookingConfigCreate,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> PreBookingConfigResponse:
    """Attach a pre-booking offer to a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    if await load_config_for_campaign(db, workspace_id, campaign_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This campaign already has a pre-booking offer",
        )
    _reject_past_season(
        payload.service_season_start_month,
        payload.service_season_end_month,
        payload.service_season_year,
    )

    config = PreBookingCampaignConfig(
        workspace_id=workspace_id,
        campaign_id=campaign_id,
        **payload.model_dump(),
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)

    return await _response(db, config, campaign)


@router.get("", response_model=PreBookingConfigResponse)
async def get_pre_booking_offer(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
) -> PreBookingConfigResponse:
    """Read a campaign's pre-booking offer, slot usage and lead time."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)
    config = await _config_or_404(db, workspace_id, campaign_id)
    return await _response(db, config, campaign)


@router.put("", response_model=PreBookingConfigResponse)
async def update_pre_booking_offer(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: PreBookingConfigUpdate,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> PreBookingConfigResponse:
    """Update the offer terms. Lowering the cap below what is already sold is
    allowed — it stops further sales without cancelling anyone."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)
    config = await _config_or_404(db, workspace_id, campaign_id)

    updates = payload.model_dump(exclude_unset=True)
    _reject_past_season(
        updates.get("service_season_start_month", config.service_season_start_month),
        updates.get("service_season_end_month", config.service_season_end_month),
        updates.get("service_season_year", config.service_season_year),
    )
    for field, value in updates.items():
        setattr(config, field, value)

    await db.commit()
    await db.refresh(config)
    return await _response(db, config, campaign)


@router.post("/launch", response_model=PreBookingConfigResponse)
async def schedule_pre_booking_launch(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: PreBookingLaunchRequest,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> PreBookingConfigResponse:
    """Arm the campaign to start sending on a future date.

    The whole point of pre-booking is building the January campaign in
    September, so the launch date is a first-class setting rather than a
    reminder in someone's phone: the campaign parks in ``scheduled`` and
    :class:`~app.workers.prebooking_worker.PreBookingWorker` starts it when the
    date arrives.
    """
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)
    config = await _config_or_404(db, workspace_id, campaign_id)

    if campaign.status not in {CampaignStatus.DRAFT, CampaignStatus.SCHEDULED}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Can only schedule a draft campaign (this one is {campaign.status})",
        )
    launch_at = payload.scheduled_start
    if launch_at.tzinfo is None:
        launch_at = launch_at.replace(tzinfo=UTC)
    if launch_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A scheduled launch must be in the future. Start the campaign now instead.",
        )
    window = resolve_season_window(
        start_month=config.service_season_start_month,
        end_month=config.service_season_end_month,
        year=config.service_season_year,
    )
    if launch_at.date() > window.end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"That launch date is after the season ends ({window.end.isoformat()}). "
                "Nobody would receive the offer in time to book."
            ),
        )

    campaign.scheduled_start = launch_at
    campaign.status = CampaignStatus.SCHEDULED
    await db.commit()
    await db.refresh(campaign)

    logger.info(
        "prebooking_launch_scheduled",
        workspace_id=str(workspace_id),
        campaign_id=str(campaign_id),
        scheduled_start=launch_at.isoformat(),
        season_start=window.start.isoformat(),
    )
    return await _response(db, config, campaign)


@router.get("/audience", response_model=PreBookingAudiencePreview)
async def preview_pre_booking_audience(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
    include_past_customers: bool = Query(True),
    include_unsold_quotes: bool = Query(True),
    include_prior_season_christmas: bool = Query(False),
    seasons_back: int | None = Query(None, gt=0, le=10),
    segment_id: uuid.UUID | None = Query(None),
) -> PreBookingAudiencePreview:
    """Count the warm database this offer would reach."""
    await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)
    return await _audience_preview(
        db,
        workspace_id,
        campaign_id=campaign_id,
        include_past_customers=include_past_customers,
        include_unsold_quotes=include_unsold_quotes,
        include_prior_season_christmas=include_prior_season_christmas,
        seasons_back=seasons_back,
        segment_id=segment_id,
    )


@router.post("/audience/enroll", response_model=PreBookingAudienceEnrollResponse)
async def enroll_pre_booking_audience(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
    include_past_customers: bool = Query(True),
    include_unsold_quotes: bool = Query(True),
    include_prior_season_christmas: bool = Query(False),
    seasons_back: int | None = Query(None, gt=0, le=10),
    segment_id: uuid.UUID | None = Query(None),
    limit: int | None = Query(None, gt=0, le=5000),
) -> PreBookingAudienceEnrollResponse:
    """Enroll the warm audience into the campaign, skipping opted-out contacts."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)
    enrollable = {CampaignStatus.DRAFT, CampaignStatus.SCHEDULED, CampaignStatus.PAUSED}
    if campaign.status not in enrollable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only add contacts to a draft, scheduled or paused campaign",
        )

    service = PreBookingAudienceService(db)
    try:
        counts = await service.preview(
            workspace_id,
            campaign_id,
            include_past_customers=include_past_customers,
            include_unsold_quotes=include_unsold_quotes,
            include_prior_season_christmas=include_prior_season_christmas,
            seasons_back=seasons_back,
            segment_id=segment_id,
        )
        contact_ids = await service.resolve_contact_ids(
            workspace_id,
            campaign_id,
            include_past_customers=include_past_customers,
            include_unsold_quotes=include_unsold_quotes,
            include_prior_season_christmas=include_prior_season_christmas,
            seasons_back=seasons_back,
            segment_id=segment_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    for contact_id in contact_ids:
        db.add(CampaignContact(campaign_id=campaign_id, contact_id=contact_id))
    campaign.total_contacts += len(contact_ids)
    await db.commit()

    logger.info(
        "prebooking_audience_enrolled",
        workspace_id=str(workspace_id),
        campaign_id=str(campaign_id),
        enrolled=len(contact_ids),
        excluded_opted_out=counts.excluded_opted_out,
    )
    return PreBookingAudienceEnrollResponse(
        enrolled=len(contact_ids),
        skipped_already_enrolled=counts.excluded_already_enrolled,
        excluded_opted_out=counts.excluded_opted_out,
        total_contacts=campaign.total_contacts,
    )


@router.post(
    "/reservations",
    response_model=PreBookingReserveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reserve_pre_booking_slot(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    payload: PreBookingReserveRequest,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteOutreach,
) -> PreBookingReserveResponse:
    """Hold a season slot for a contact and issue the deposit-bearing proposal.

    Returns the public proposal link. A confirmed card payment or an authenticated
    operator's offline deposit record is what confirms the booking and puts a
    provisional job into backlog.
    """
    await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)
    config = await _config_or_404(db, workspace_id, campaign_id)

    try:
        held = await PreBookingReservationService(db).hold_slot(
            workspace_id,
            config,
            contact_id=payload.contact_id,
            source_quote_id=payload.source_quote_id,
            base_amount=payload.base_amount,
            service_location_id=payload.service_location_id,
            notes=payload.notes,
            created_by_id=current_user.id,
        )
    except SlotCapReachedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ContactNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except PreBookingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return PreBookingReserveResponse(
        reservation=PreBookingReservationResponse.model_validate(held.reservation),
        quote_id=held.quote.id,
        quote_number=held.quote.number,
        deposit_amount=held.deposit_amount,
        proposal_url=held.proposal_url,
        slots_remaining=held.slots_remaining,
    )


@router.get("/reservations", response_model=list[PreBookingReservationResponse])
async def list_pre_booking_reservations(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
    status_filter: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> list[PreBookingReservationResponse]:
    """List the slots sold by this campaign."""
    await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    query = select(PreBookingReservation).where(
        PreBookingReservation.campaign_id == campaign_id,
        PreBookingReservation.workspace_id == workspace_id,
    )
    if status_filter:
        query = query.where(PreBookingReservation.status == status_filter)
    query = query.order_by(PreBookingReservation.created_at.desc()).limit(limit)

    rows = (await db.execute(query)).scalars().all()
    return [PreBookingReservationResponse.model_validate(row) for row in rows]


__all__ = ["router", "workspace_router"]
