"""Guarantee tracking service for campaigns."""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaign import Campaign


async def increment_completed_and_check_guarantee(
    db: AsyncSession,
    campaign_id: object,
    log: structlog.BoundLogger,
) -> None:
    """Increment appointments_completed and check if guarantee is met.

    Does NOT commit — caller must commit.
    """
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        log.warning("guarantee_check_campaign_not_found", campaign_id=str(campaign_id))
        return

    campaign.appointments_completed += 1
    log.info(
        "appointments_completed_incremented",
        campaign_id=str(campaign_id),
        appointments_completed=campaign.appointments_completed,
    )

    if (
        campaign.guarantee_target
        and campaign.guarantee_status == "pending"
        and campaign.appointments_completed >= campaign.guarantee_target
    ):
        campaign.guarantee_status = "met"
        log.info(
            "guarantee_met",
            campaign_id=str(campaign_id),
            target=campaign.guarantee_target,
            completed=campaign.appointments_completed,
        )


async def check_guarantee_expiry(
    db: AsyncSession,
    campaign_id: object,
    log: structlog.BoundLogger,
) -> None:
    """Check if guarantee window has expired. Sets status to 'missed' if so.

    Does NOT commit — caller must commit.
    """
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if not campaign:
        return

    if (
        campaign.guarantee_status == "pending"
        and campaign.guarantee_target
        and campaign.guarantee_window_days
        and campaign.started_at
    ):
        deadline = campaign.started_at + timedelta(days=campaign.guarantee_window_days)
        if datetime.now(UTC) > deadline:
            campaign.guarantee_status = "missed"
            log.info(
                "guarantee_missed",
                campaign_id=str(campaign_id),
                target=campaign.guarantee_target,
                completed=campaign.appointments_completed,
            )
