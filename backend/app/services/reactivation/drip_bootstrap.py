"""Auto-create a default realtor drip campaign for freshly imported contacts.

Extracted from ``app/api/v1/realtor.py`` so the CSV upload flow (and any
future import flows) can share the same helper.
"""

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.drip_campaign import DripCampaign, DripCampaignStatus
from app.models.phone_number import PhoneNumber
from app.services.reactivation.drip_runner import enroll_contacts
from app.services.reactivation.sequence_config import get_realtor_drip_config

logger = structlog.get_logger()


async def auto_create_drip_for_imports(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    contact_ids: list[int],
) -> None:
    """Create an active drip campaign and enroll the given contacts.

    Looks up the workspace's realtor agent (falling back to any text-channel
    agent) and the first active SMS-enabled phone number. If either is
    missing, logs a warning and returns — matching the legacy behavior.
    """
    # Find agent
    agent_result = await db.execute(
        select(Agent)
        .where(
            Agent.workspace_id == workspace_id,
            Agent.name == "Realtor Lead Reactivation Agent",
        )
        .limit(1)
    )
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        fallback_result = await db.execute(
            select(Agent)
            .where(Agent.workspace_id == workspace_id, Agent.channel_mode == "text")
            .order_by(Agent.created_at.asc())
            .limit(1)
        )
        agent = fallback_result.scalar_one_or_none()

    if agent is None:
        logger.warning("no_agent_for_drip", workspace_id=str(workspace_id))
        return

    # Find phone number
    phone_result = await db.execute(
        select(PhoneNumber)
        .where(
            PhoneNumber.workspace_id == workspace_id,
            PhoneNumber.is_active.is_(True),
            PhoneNumber.sms_enabled.is_(True),
        )
        .order_by(PhoneNumber.created_at.asc())
        .limit(1)
    )
    phone_record = phone_result.scalar_one_or_none()
    if phone_record is None:
        logger.warning("no_phone_for_drip", workspace_id=str(workspace_id))
        return

    drip_config = get_realtor_drip_config()
    drip_campaign = DripCampaign(
        workspace_id=workspace_id,
        agent_id=agent.id,
        from_phone_number=phone_record.phone_number,
        status=DripCampaignStatus.ACTIVE.value,
        started_at=datetime.now(UTC),
        **drip_config,
    )
    db.add(drip_campaign)
    await db.flush()

    enrolled = await enroll_contacts(drip_campaign, contact_ids, db)
    logger.info(
        "drip_auto_created_for_imports",
        workspace_id=str(workspace_id),
        drip_campaign_id=str(drip_campaign.id),
        enrolled=enrolled,
    )
