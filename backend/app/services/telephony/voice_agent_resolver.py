"""Voice agent resolver for incoming calls."""

import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agent import Agent
from app.models.campaign import CampaignContact
from app.models.phone_number import PhoneNumber

logger = structlog.get_logger()


@dataclass
class ResolvedAgent:
    """Result of resolving a voice agent for a call.

    Attributes:
        agent: The resolved Agent model instance
        source: Description of where the agent came from
    """

    agent: Agent
    source: str


class VoiceAgentResolver:
    """Resolves the appropriate voice agent for incoming calls.

    Priority order:
    1. Campaign voice agent (campaign.voice_agent_id)
    2. Campaign general agent (campaign.agent_id) if it supports voice
    3. Conversation's assigned agent (from test call or manual assignment)
    4. Phone number's assigned agent (phone_record.assigned_agent_id)
    """

    def __init__(self) -> None:
        self.logger = logger.bind(service="voice_agent_resolver")

    async def resolve(
        self,
        db: AsyncSession,
        conversation: Any | None,
        phone_record: PhoneNumber,
        log: Any | None = None,
    ) -> ResolvedAgent | None:
        """Resolve the voice agent for an incoming call.

        Args:
            db: Database session
            conversation: Conversation model instance (optional)
            phone_record: PhoneNumber record for the destination number
            log: Optional logger instance

        Returns:
            ResolvedAgent with agent and source, or None if no valid agent found
        """
        if log is None:
            log = self.logger

        # Priority 1 & 2: Check if conversation is part of a campaign
        if conversation:
            result = await self._resolve_from_campaign(db, conversation, log)
            if result:
                return result

        # Priority 3: Conversation's assigned agent (from test call or manual assignment)
        if conversation and conversation.assigned_agent_id:
            result = await self._check_agent(
                db, conversation.assigned_agent_id, "conversation_agent", log
            )
            if result:
                return result

        # Priority 4: Phone number's assigned agent
        if phone_record.assigned_agent_id:
            result = await self._check_agent(
                db, phone_record.assigned_agent_id, "phone_number_agent", log
            )
            if result:
                return result

        return None

    async def _resolve_from_campaign(
        self,
        db: AsyncSession,
        conversation: Any,
        log: Any,
    ) -> ResolvedAgent | None:
        """Try to resolve agent from campaign configuration.

        Args:
            db: Database session
            conversation: Conversation model instance
            log: Logger instance

        Returns:
            ResolvedAgent if found, None otherwise
        """
        campaign_contact_result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.campaign))
            .where(CampaignContact.conversation_id == conversation.id)
        )
        campaign_contact = campaign_contact_result.scalar_one_or_none()

        if not campaign_contact or not campaign_contact.campaign:
            return None

        campaign = campaign_contact.campaign
        voice_agent_str = str(campaign.voice_agent_id) if campaign.voice_agent_id else None
        agent_str = str(campaign.agent_id) if campaign.agent_id else None

        log.info(
            "found_campaign_for_voice_call",
            campaign_id=str(campaign.id),
            campaign_type=campaign.campaign_type,
            voice_agent_id=voice_agent_str,
            agent_id=agent_str,
        )

        # Priority 1: Voice campaign's voice agent
        if campaign.voice_agent_id:
            result = await self._check_agent(
                db, campaign.voice_agent_id, "campaign_voice_agent", log
            )
            if result:
                return result

        # Priority 2: Campaign's general agent (if it supports voice)
        if campaign.agent_id:
            result = await self._check_agent(db, campaign.agent_id, "campaign_agent", log)
            if result:
                return result

        return None

    async def _check_agent(
        self,
        db: AsyncSession,
        agent_id: uuid.UUID,
        source: str,
        log: Any,
    ) -> ResolvedAgent | None:
        """Check if an agent is valid for voice calls.

        Args:
            db: Database session
            agent_id: Agent ID to check
            source: Source description for logging
            log: Logger instance

        Returns:
            ResolvedAgent if agent is active and voice-capable, None otherwise
        """
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            log.debug("agent_not_found", agent_id=str(agent_id), source=source)
            return None

        if not agent.is_active:
            log.debug("agent_not_active", agent_id=str(agent_id), source=source)
            return None

        if agent.channel_mode not in ("voice", "both"):
            log.debug(
                "agent_not_voice_capable",
                agent_id=str(agent_id),
                channel_mode=agent.channel_mode,
                source=source,
            )
            return None

        return ResolvedAgent(agent=agent, source=source)
