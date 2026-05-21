"""Shared campaign lifecycle transitions for API, assistant tools, and workers."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign, CampaignContact, CampaignStatus


class CampaignLifecycleError(Exception):
    """Raised when a campaign lifecycle transition is not allowed."""


@dataclass(frozen=True, slots=True)
class CampaignLifecycleResult:
    """Result of a campaign lifecycle transition."""

    status: CampaignStatus
    message: str
    contact_count: int | None = None


async def get_campaign_for_workspace(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Campaign | None:
    """Return a campaign scoped to a workspace."""
    result = await db.execute(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def count_campaign_contacts(db: AsyncSession, campaign_id: uuid.UUID) -> int:
    """Count contacts enrolled in a campaign."""
    count_result = await db.execute(
        select(func.count(CampaignContact.id)).where(CampaignContact.campaign_id == campaign_id)
    )
    return count_result.scalar() or 0


async def start_campaign(
    db: AsyncSession,
    campaign: Campaign,
    contact_count: int | None = None,
) -> CampaignLifecycleResult:
    """Start a draft, paused, or scheduled campaign with worker-compatible status."""
    if campaign.status not in {
        CampaignStatus.DRAFT,
        CampaignStatus.PAUSED,
        CampaignStatus.SCHEDULED,
    }:
        raise CampaignLifecycleError(f"Cannot start campaign with status: {campaign.status}")

    enrolled_count = (
        await count_campaign_contacts(db, campaign.id) if contact_count is None else contact_count
    )
    if enrolled_count == 0:
        raise CampaignLifecycleError("Campaign has no contacts")

    campaign.status = CampaignStatus.RUNNING
    campaign.started_at = datetime.now(UTC)
    if campaign.guarantee_target and campaign.guarantee_target > 0:
        campaign.guarantee_status = "pending"

    return CampaignLifecycleResult(
        status=CampaignStatus.RUNNING,
        message=f"Campaign started with {enrolled_count} contacts",
        contact_count=enrolled_count,
    )


async def pause_campaign(campaign: Campaign) -> CampaignLifecycleResult:
    """Pause a running campaign."""
    if campaign.status != CampaignStatus.RUNNING:
        raise CampaignLifecycleError("Can only pause running campaigns")

    campaign.status = CampaignStatus.PAUSED
    return CampaignLifecycleResult(status=CampaignStatus.PAUSED, message="Campaign paused")


async def resume_campaign(
    db: AsyncSession,
    campaign: Campaign,
    contact_count: int | None = None,
) -> CampaignLifecycleResult:
    """Resume a paused campaign with worker-compatible status."""
    if campaign.status != CampaignStatus.PAUSED:
        raise CampaignLifecycleError("Can only resume paused campaigns")

    enrolled_count = (
        await count_campaign_contacts(db, campaign.id) if contact_count is None else contact_count
    )
    if enrolled_count == 0:
        raise CampaignLifecycleError("Campaign has no contacts")

    campaign.status = CampaignStatus.RUNNING
    return CampaignLifecycleResult(
        status=CampaignStatus.RUNNING,
        message="Campaign resumed",
        contact_count=enrolled_count,
    )


def summarize_campaign(campaign: Campaign) -> dict[str, Any]:
    """Return campaign summary metrics and calculated rates."""
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

    return {
        "id": str(campaign.id),
        "name": campaign.name,
        "status": (
            campaign.status.value
            if isinstance(campaign.status, CampaignStatus)
            else campaign.status
        ),
        "type": campaign.campaign_type,
        "total_contacts": campaign.total_contacts,
        "messages_sent": campaign.messages_sent,
        "messages_delivered": campaign.messages_delivered,
        "messages_failed": campaign.messages_failed,
        "replies_received": campaign.replies_received,
        "contacts_qualified": campaign.contacts_qualified,
        "contacts_opted_out": campaign.contacts_opted_out,
        "appointments_booked": campaign.appointments_booked,
        "appointments_completed": campaign.appointments_completed,
        "calls_attempted": campaign.calls_attempted,
        "calls_answered": campaign.calls_answered,
        "sms_fallbacks_sent": campaign.sms_fallbacks_sent,
        "guarantee_target": campaign.guarantee_target,
        "guarantee_status": campaign.guarantee_status,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
        "rates": {
            "reply_rate": reply_rate,
            "delivery_rate": delivery_rate,
            "qualification_rate": qualification_rate,
        },
    }
