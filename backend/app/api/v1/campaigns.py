"""Campaign management endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crud import get_or_404
from app.api.deps import DB, CurrentUser, get_workspace
from app.core.config import settings
from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignContact, CampaignStatus, CampaignType
from app.models.contact import Contact
from app.models.phone_number import PhoneNumber
from app.models.workspace import Workspace
from app.schemas.campaign import (
    CampaignAnalytics,
    CampaignContactAdd,
    CampaignContactResponse,
    CampaignCreate,
    CampaignResponse,
    CampaignUpdate,
    GuaranteeProgressResponse,
    PaginatedCampaigns,
)
from app.services.campaigns.campaign_filters import apply_campaign_filters
from app.services.campaigns.campaign_lifecycle import (
    CampaignLifecycleError,
)
from app.services.campaigns.campaign_lifecycle import (
    pause_campaign as pause_campaign_lifecycle,
)
from app.services.campaigns.campaign_lifecycle import (
    resume_campaign as resume_campaign_lifecycle,
)
from app.services.campaigns.campaign_lifecycle import (
    start_campaign as start_campaign_lifecycle,
)
from app.services.campaigns.guarantee_tracker import check_guarantee_expiry
from app.utils.datetime import parse_time_string

router = APIRouter()


async def _validate_campaign_sender(db: AsyncSession, from_phone_number: str) -> None:
    """Ensure a campaign sender has a usable text channel."""
    sender_result = await db.execute(
        select(PhoneNumber).where(
            PhoneNumber.phone_number == from_phone_number,
            PhoneNumber.is_active.is_(True),
        )
    )
    sender = sender_result.scalar_one_or_none()
    if sender is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign sender phone number is not active",
        )

    if not sender.sms_enabled and not sender.imessage_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign sender must have SMS or iMessage enabled",
        )

    if sender.imessage_enabled and not (settings.mac_relay_base_url and settings.mac_relay_token):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="iMessage relay is not configured for campaign sending",
        )

    if sender.sms_enabled and not sender.imessage_enabled and not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Telnyx SMS is not configured for campaign sending",
        )


@router.get("", response_model=PaginatedCampaigns)
async def list_campaigns(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = None,
) -> PaginatedCampaigns:
    """List campaigns in a workspace."""
    query = apply_campaign_filters(
        select(Campaign),
        workspace_id,
        status=status_filter,
    )
    query = query.order_by(Campaign.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)

    return PaginatedCampaigns(**result.to_response(CampaignResponse))


@router.post("", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    workspace_id: uuid.UUID,
    campaign_in: CampaignCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Create a new campaign."""
    # Verify agent if provided
    if campaign_in.agent_id:
        agent_result = await db.execute(
            select(Agent).where(
                Agent.id == campaign_in.agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        if not agent_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            )

    # Email campaigns send via Resend and have no phone sender; SMS/voice
    # campaigns must resolve to a usable text channel.
    if campaign_in.campaign_type == CampaignType.EMAIL.value:
        if not campaign_in.email_subject or not campaign_in.email_subject.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Email campaigns require an email subject.",
            )
        if not campaign_in.initial_message or not campaign_in.initial_message.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Email campaigns require an email body.",
            )
    else:
        if not campaign_in.from_phone_number:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A sender phone number is required for this campaign type.",
            )
        await _validate_campaign_sender(db, campaign_in.from_phone_number)

    # Convert time strings to datetime.time objects
    campaign_data = campaign_in.model_dump()
    if "sending_hours_start" in campaign_data:
        campaign_data["sending_hours_start"] = parse_time_string(
            campaign_data["sending_hours_start"]
        )
    if "sending_hours_end" in campaign_data:
        campaign_data["sending_hours_end"] = parse_time_string(campaign_data["sending_hours_end"])

    campaign = Campaign(
        workspace_id=workspace_id,
        **campaign_data,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    return campaign


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Get a campaign by ID."""
    return await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)


@router.put("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    campaign_in: CampaignUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Update a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    # Only allow updates on draft/paused campaigns
    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update draft or paused campaigns",
        )

    # Update fields
    update_data = campaign_in.model_dump(exclude_unset=True)
    if "from_phone_number" in update_data and update_data["from_phone_number"] is not None:
        await _validate_campaign_sender(db, update_data["from_phone_number"])

    # Convert time strings to datetime.time objects
    if "sending_hours_start" in update_data:
        update_data["sending_hours_start"] = parse_time_string(update_data["sending_hours_start"])
    if "sending_hours_end" in update_data:
        update_data["sending_hours_end"] = parse_time_string(update_data["sending_hours_end"])

    for field, value in update_data.items():
        setattr(campaign, field, value)

    await db.commit()
    await db.refresh(campaign)

    return campaign


@router.post("/{campaign_id}/start")
async def start_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Start a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    try:
        if campaign.campaign_type != CampaignType.EMAIL:
            await _validate_campaign_sender(db, campaign.from_phone_number)
        lifecycle_result = await start_campaign_lifecycle(db, campaign)
    except CampaignLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await db.commit()

    return {"status": lifecycle_result.status.value, "message": lifecycle_result.message}


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Pause a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    try:
        lifecycle_result = await pause_campaign_lifecycle(campaign)
    except CampaignLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await db.commit()

    return {"status": lifecycle_result.status.value}


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Resume a paused campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    try:
        lifecycle_result = await resume_campaign_lifecycle(db, campaign)
    except CampaignLifecycleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    await db.commit()

    return {"status": lifecycle_result.status.value, "message": lifecycle_result.message}


@router.post("/{campaign_id}/cancel")
async def cancel_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Cancel a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only cancel draft or paused campaigns",
        )

    campaign.status = CampaignStatus.CANCELED
    await db.commit()

    return {"status": "canceled"}


@router.post("/{campaign_id}/contacts", response_model=dict[str, int])
async def add_contacts(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    contacts_in: CampaignContactAdd,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Add contacts to a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only add contacts to draft or paused campaigns",
        )

    # Verify contacts belong to workspace
    contacts_result = await db.execute(
        select(Contact).where(
            Contact.id.in_(contacts_in.contact_ids),
            Contact.workspace_id == workspace_id,
        )
    )
    valid_contacts = contacts_result.scalars().all()
    valid_contact_ids = {c.id for c in valid_contacts}

    # Get existing campaign contacts
    existing_result = await db.execute(
        select(CampaignContact.contact_id).where(CampaignContact.campaign_id == campaign_id)
    )
    existing_ids = {row[0] for row in existing_result.all()}

    # Add new contacts
    added_count = 0
    for contact_id in valid_contact_ids:
        if contact_id not in existing_ids:
            campaign_contact = CampaignContact(
                campaign_id=campaign_id,
                contact_id=contact_id,
            )
            db.add(campaign_contact)
            added_count += 1

    # Update campaign stats
    campaign.total_contacts += added_count
    await db.commit()

    return {"added": added_count}


@router.get("/{campaign_id}/contacts", response_model=list[CampaignContactResponse])
async def list_campaign_contacts(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    status_filter: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[CampaignContactResponse]:
    """List contacts in a campaign."""
    # Verify campaign exists
    await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    query = select(CampaignContact).where(CampaignContact.campaign_id == campaign_id)

    if status_filter:
        query = query.where(CampaignContact.status == status_filter)

    query = query.order_by(CampaignContact.created_at.desc()).limit(limit)

    contacts_result = await db.execute(query)
    contacts = contacts_result.scalars().all()

    return [CampaignContactResponse.model_validate(c) for c in contacts]


@router.get("/{campaign_id}/analytics", response_model=CampaignAnalytics)
async def get_analytics(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CampaignAnalytics:
    """Get campaign analytics."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    reply_rate = (
        campaign.replies_received / campaign.messages_sent if campaign.messages_sent > 0 else 0.0
    )
    delivery_rate = (
        campaign.messages_delivered / campaign.messages_sent if campaign.messages_sent > 0 else 0.0
    )
    qualification_rate = (
        campaign.contacts_qualified / campaign.total_contacts
        if campaign.total_contacts > 0
        else 0.0
    )

    return CampaignAnalytics(
        total_contacts=campaign.total_contacts,
        messages_sent=campaign.messages_sent,
        messages_delivered=campaign.messages_delivered,
        messages_failed=campaign.messages_failed,
        replies_received=campaign.replies_received,
        contacts_qualified=campaign.contacts_qualified,
        contacts_opted_out=campaign.contacts_opted_out,
        reply_rate=reply_rate,
        delivery_rate=delivery_rate,
        qualification_rate=qualification_rate,
    )


@router.get("/{campaign_id}/guarantee", response_model=GuaranteeProgressResponse)
async def get_guarantee_progress(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> GuaranteeProgressResponse:
    """Get campaign guarantee progress."""
    log = structlog.get_logger().bind(campaign_id=str(campaign_id))
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    # Lazy expiry check
    if campaign.guarantee_status == "pending":
        await check_guarantee_expiry(db, campaign_id, log)
        await db.commit()
        await db.refresh(campaign)

    # Calculate days remaining
    days_remaining = None
    deadline = None
    if campaign.started_at and campaign.guarantee_window_days:
        from datetime import timedelta

        deadline_dt = campaign.started_at + timedelta(days=campaign.guarantee_window_days)
        deadline = deadline_dt.isoformat()
        remaining = (deadline_dt - datetime.now(UTC)).days
        days_remaining = max(0, remaining)

    return GuaranteeProgressResponse(
        campaign_id=str(campaign.id),
        guarantee_target=campaign.guarantee_target,
        appointments_booked=campaign.appointments_booked,
        appointments_completed=campaign.appointments_completed,
        guarantee_status=campaign.guarantee_status,
        guarantee_window_days=campaign.guarantee_window_days,
        days_remaining=days_remaining,
        deadline=deadline,
        started_at=campaign.started_at.isoformat() if campaign.started_at else None,
    )


@router.delete("/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    if campaign.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete running campaign. Pause it first.",
        )

    await db.delete(campaign)
    await db.commit()


@router.post(
    "/{campaign_id}/duplicate",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Duplicate a campaign."""
    campaign = await get_or_404(db, Campaign, campaign_id, workspace_id=workspace_id)

    # Create a new campaign with copied attributes
    new_campaign = Campaign(
        workspace_id=workspace_id,
        campaign_type=campaign.campaign_type,
        agent_id=campaign.agent_id,
        offer_id=campaign.offer_id,
        name=f"{campaign.name} (Copy)",
        status=CampaignStatus.DRAFT,
        from_phone_number=campaign.from_phone_number,
        initial_message=campaign.initial_message,
        ai_enabled=campaign.ai_enabled,
        qualification_criteria=campaign.qualification_criteria,
        sending_hours_start=campaign.sending_hours_start,
        sending_hours_end=campaign.sending_hours_end,
        sending_days=campaign.sending_days,
        timezone=campaign.timezone,
        messages_per_minute=campaign.messages_per_minute,
        follow_up_enabled=campaign.follow_up_enabled,
        follow_up_delay_hours=campaign.follow_up_delay_hours,
        follow_up_message=campaign.follow_up_message,
        max_follow_ups=campaign.max_follow_ups,
    )
    db.add(new_campaign)
    await db.commit()
    await db.refresh(new_campaign)

    return new_campaign
