"""Voice campaign management endpoints."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, get_workspace
from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.models.workspace import Workspace
from app.schemas.campaign import (
    CampaignContactAdd,
    GuaranteeProgressResponse,
    PaginatedVoiceCampaigns,
    VoiceCampaignAnalytics,
    VoiceCampaignContactResponse,
    VoiceCampaignCreate,
    VoiceCampaignResponse,
    VoiceCampaignUpdate,
)
from app.services.campaigns.guarantee_tracker import check_guarantee_expiry
from app.utils.datetime import parse_time_string

router = APIRouter()


async def _get_voice_campaign(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Campaign:
    """Fetch a voice campaign by ID, raising 404 if not found."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.workspace_id == workspace_id,
            Campaign.campaign_type == CampaignType.VOICE_SMS_FALLBACK,
        )
    )
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice campaign not found",
        )

    return campaign


@router.get("", response_model=PaginatedVoiceCampaigns)
async def list_voice_campaigns(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    status_filter: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
) -> PaginatedVoiceCampaigns:
    """List voice campaigns in a workspace."""
    query = select(Campaign).where(
        and_(
            Campaign.workspace_id == workspace_id,
            Campaign.campaign_type == CampaignType.VOICE_SMS_FALLBACK,
        )
    )

    if status_filter:
        query = query.where(Campaign.status == status_filter)

    query = query.order_by(Campaign.created_at.desc())

    result = await paginate(db, query, page=page, page_size=page_size)
    return PaginatedVoiceCampaigns(**result.to_response(VoiceCampaignResponse))


@router.post("", response_model=VoiceCampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_in: VoiceCampaignCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Create a new voice campaign with SMS fallback."""
    # Verify voice agent exists and supports voice
    voice_agent_result = await db.execute(
        select(Agent).where(
            Agent.id == campaign_in.voice_agent_id,
            Agent.workspace_id == workspace_id,
        )
    )
    voice_agent = voice_agent_result.scalar_one_or_none()

    if not voice_agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice agent not found",
        )

    if voice_agent.channel_mode not in ("voice", "both"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent must support voice channel",
        )

    # Verify SMS fallback agent if provided
    if campaign_in.sms_fallback_agent_id:
        sms_agent_result = await db.execute(
            select(Agent).where(
                Agent.id == campaign_in.sms_fallback_agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        sms_agent = sms_agent_result.scalar_one_or_none()

        if not sms_agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="SMS fallback agent not found",
            )

        if sms_agent.channel_mode not in ("text", "both"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SMS fallback agent must support text channel",
            )

    # Create campaign with voice-specific settings
    campaign_data = campaign_in.model_dump()

    # Set campaign type
    campaign_data["campaign_type"] = CampaignType.VOICE_SMS_FALLBACK

    # Use voice agent as the primary agent for AI responses
    campaign_data["agent_id"] = campaign_in.sms_fallback_agent_id or campaign_in.voice_agent_id

    # Voice campaigns don't have initial_message (they make calls instead)
    campaign_data["initial_message"] = None

    # Convert time strings to datetime.time objects
    if "sending_hours_start" in campaign_data:
        campaign_data["sending_hours_start"] = parse_time_string(
            campaign_data["sending_hours_start"]
        )
    if "sending_hours_end" in campaign_data:
        campaign_data["sending_hours_end"] = parse_time_string(
            campaign_data["sending_hours_end"]
        )

    campaign = Campaign(
        workspace_id=workspace_id,
        **campaign_data,
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)

    return campaign


@router.get("/{campaign_id}", response_model=VoiceCampaignResponse)
async def get_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Get a voice campaign by ID."""
    # Use direct query for eager loading
    result = await db.execute(
        select(Campaign)
        .options(
            selectinload(Campaign.voice_agent),
            selectinload(Campaign.sms_fallback_agent),
        )
        .where(
            Campaign.id == campaign_id,
            Campaign.workspace_id == workspace_id,
            Campaign.campaign_type == CampaignType.VOICE_SMS_FALLBACK,
        )
    )
    campaign = result.scalar_one_or_none()

    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice campaign not found",
        )

    return campaign


@router.put("/{campaign_id}", response_model=VoiceCampaignResponse)
async def update_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    campaign_in: VoiceCampaignUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Campaign:
    """Update a voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only update draft or paused campaigns",
        )

    # Validate voice agent if provided
    if campaign_in.voice_agent_id:
        voice_agent_result = await db.execute(
            select(Agent).where(
                Agent.id == campaign_in.voice_agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        voice_agent = voice_agent_result.scalar_one_or_none()

        if not voice_agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Voice agent not found",
            )

        if voice_agent.channel_mode not in ("voice", "both"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent must support voice channel",
            )

    # Validate SMS fallback agent if provided
    if campaign_in.sms_fallback_agent_id:
        sms_agent_result = await db.execute(
            select(Agent).where(
                Agent.id == campaign_in.sms_fallback_agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        sms_agent = sms_agent_result.scalar_one_or_none()

        if not sms_agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="SMS fallback agent not found",
            )

        if sms_agent.channel_mode not in ("text", "both"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="SMS fallback agent must support text channel",
            )

    # Update fields
    update_data = campaign_in.model_dump(exclude_unset=True)

    # Convert time strings to datetime.time objects
    if "sending_hours_start" in update_data:
        update_data["sending_hours_start"] = parse_time_string(
            update_data["sending_hours_start"]
        )
    if "sending_hours_end" in update_data:
        update_data["sending_hours_end"] = parse_time_string(
            update_data["sending_hours_end"]
        )

    for field, value in update_data.items():
        setattr(campaign, field, value)

    await db.commit()
    await db.refresh(campaign)

    return campaign


@router.post("/{campaign_id}/start")
async def start_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Start a voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status not in ("draft", "paused", "scheduled"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot start campaign with status: {campaign.status}",
        )

    # Check if campaign has contacts
    count_result = await db.execute(
        select(func.count(CampaignContact.id)).where(
            CampaignContact.campaign_id == campaign_id
        )
    )
    contact_count = count_result.scalar() or 0

    if contact_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign has no contacts",
        )

    # Verify voice agent is still valid
    if campaign.voice_agent_id:
        agent_result = await db.execute(
            select(Agent).where(Agent.id == campaign.voice_agent_id)
        )
        if not agent_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Voice agent no longer exists",
            )

    campaign.status = CampaignStatus.RUNNING
    campaign.started_at = datetime.now(UTC)
    if campaign.guarantee_target and campaign.guarantee_target > 0:
        campaign.guarantee_status = "pending"
    await db.commit()

    return {"status": "running", "message": f"Voice campaign started with {contact_count} contacts"}


@router.post("/{campaign_id}/pause")
async def pause_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Pause a voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status != "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only pause running campaigns",
        )

    campaign.status = CampaignStatus.PAUSED
    await db.commit()

    return {"status": "paused"}


@router.post("/{campaign_id}/resume")
async def resume_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Resume a paused voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status != "paused":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only resume paused campaigns",
        )

    campaign.status = CampaignStatus.RUNNING
    await db.commit()

    return {"status": "running", "message": "Voice campaign resumed"}


@router.post("/{campaign_id}/cancel")
async def cancel_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Cancel a voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only cancel draft or paused campaigns",
        )

    campaign.status = CampaignStatus.CANCELED
    await db.commit()

    return {"status": "canceled"}


@router.post("/{campaign_id}/contacts", response_model=dict[str, int])
async def add_contacts_to_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    contacts_in: CampaignContactAdd,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Add contacts to a voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status not in ("draft", "paused"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only add contacts to draft or paused campaigns",
        )

    # Verify contacts belong to workspace and have phone numbers
    contacts_result = await db.execute(
        select(Contact).where(
            Contact.id.in_(contacts_in.contact_ids),
            Contact.workspace_id == workspace_id,
            Contact.phone_number.isnot(None),
        )
    )
    valid_contacts = contacts_result.scalars().all()
    valid_contact_ids = {c.id for c in valid_contacts}

    # Get existing campaign contacts
    existing_result = await db.execute(
        select(CampaignContact.contact_id).where(
            CampaignContact.campaign_id == campaign_id
        )
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


@router.get("/{campaign_id}/contacts", response_model=list[VoiceCampaignContactResponse])
async def list_voice_campaign_contacts(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    status_filter: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[CampaignContact]:
    """List contacts in a voice campaign."""
    # Verify campaign exists
    await _get_voice_campaign(db, campaign_id, workspace_id)

    query = select(CampaignContact).where(CampaignContact.campaign_id == campaign_id)

    if status_filter:
        query = query.where(CampaignContact.status == status_filter)

    query = query.order_by(CampaignContact.created_at.desc()).limit(limit)

    contacts_result = await db.execute(query)
    contacts = contacts_result.scalars().all()

    return list(contacts)


@router.get("/{campaign_id}/analytics", response_model=VoiceCampaignAnalytics)
async def get_voice_campaign_analytics(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> VoiceCampaignAnalytics:
    """Get voice campaign analytics."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    # Calculate rates
    answer_rate = 0.0
    if campaign.calls_attempted > 0:
        answer_rate = (campaign.calls_answered / campaign.calls_attempted) * 100

    fallback_rate = 0.0
    failed_calls = (
        campaign.calls_no_answer + campaign.calls_busy + campaign.calls_voicemail
    )
    if failed_calls > 0:
        fallback_rate = (campaign.sms_fallbacks_sent / failed_calls) * 100

    qualification_rate = 0.0
    total_responses = campaign.calls_answered + campaign.replies_received
    if total_responses > 0:
        qualification_rate = (campaign.contacts_qualified / total_responses) * 100

    return VoiceCampaignAnalytics(
        total_contacts=campaign.total_contacts,
        calls_attempted=campaign.calls_attempted,
        calls_answered=campaign.calls_answered,
        calls_no_answer=campaign.calls_no_answer,
        calls_busy=campaign.calls_busy,
        calls_voicemail=campaign.calls_voicemail,
        sms_fallbacks_sent=campaign.sms_fallbacks_sent,
        messages_sent=campaign.messages_sent,
        replies_received=campaign.replies_received,
        contacts_qualified=campaign.contacts_qualified,
        contacts_opted_out=campaign.contacts_opted_out,
        appointments_booked=campaign.appointments_booked,
        answer_rate=answer_rate,
        fallback_rate=fallback_rate,
        qualification_rate=qualification_rate,
    )


@router.get("/{campaign_id}/guarantee", response_model=GuaranteeProgressResponse)
async def get_voice_guarantee_progress(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> GuaranteeProgressResponse:
    """Get voice campaign guarantee progress."""
    log = structlog.get_logger().bind(campaign_id=str(campaign_id))
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

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
async def delete_voice_campaign(
    workspace_id: uuid.UUID,
    campaign_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a voice campaign."""
    campaign = await _get_voice_campaign(db, campaign_id, workspace_id)

    if campaign.status == "running":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete running campaign. Pause it first.",
        )

    await db.delete(campaign)
    await db.commit()
