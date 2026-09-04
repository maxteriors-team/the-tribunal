"""Campaign conversation syncer for syncing agent assignments."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.campaign import CampaignContact

logger = structlog.get_logger()


class CampaignConversationSyncer:
    """Syncs conversation settings with campaign configuration.

    Ensures conversations linked to campaigns have the correct agent
    assigned and AI enabled when appropriate.
    """

    def __init__(self) -> None:
        self.logger = logger.bind(service="campaign_conversation_syncer")

    async def sync_conversation(
        self,
        db: AsyncSession,
        conversation: Any,
        log: Any | None = None,
    ) -> bool:
        """Sync conversation with campaign agent and AI settings.

        If the conversation is part of a campaign:
        - Assigns the campaign's agent to the conversation (campaign overrides)
        - Enables AI if the campaign has AI enabled

        Args:
            db: Database session
            conversation: Conversation model instance
            log: Optional logger instance

        Returns:
            True if changes were made, False otherwise
        """
        if log is None:
            log = self.logger
        if conversation.source_provider is not None:
            log.info("imported_conversation_read_only", conversation_id=str(conversation.id))
            return False

        # Check if conversation is part of a campaign
        campaign_contact_result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.campaign))
            .where(CampaignContact.conversation_id == conversation.id)
        )
        campaign_contact = campaign_contact_result.scalar_one_or_none()

        if not campaign_contact or not campaign_contact.campaign:
            return False

        campaign = campaign_contact.campaign
        changes_made = False

        # Sync campaign's agent to the conversation (campaign agent always overrides)
        if campaign.agent_id and conversation.assigned_agent_id != campaign.agent_id:
            conversation.assigned_agent_id = campaign.agent_id
            changes_made = True
            log.info(
                "synced_campaign_agent",
                conversation_id=str(conversation.id),
                campaign_id=str(campaign_contact.campaign_id),
                agent_id=str(campaign.agent_id),
            )

        # Ensure AI is enabled for campaign conversations
        if not conversation.ai_enabled and campaign.ai_enabled:
            conversation.ai_enabled = True
            changes_made = True
            log.info(
                "enabled_ai_for_campaign_conversation",
                conversation_id=str(conversation.id),
            )

        if changes_made:
            await db.commit()
            await db.refresh(conversation)

        return changes_made

    async def get_campaign_for_conversation(
        self,
        db: AsyncSession,
        conversation_id: uuid.UUID,
    ) -> CampaignContact | None:
        """Get the campaign contact record for a conversation.

        Args:
            db: Database session
            conversation_id: Conversation ID

        Returns:
            CampaignContact with campaign loaded, or None
        """
        result = await db.execute(
            select(CampaignContact)
            .options(selectinload(CampaignContact.campaign))
            .where(CampaignContact.conversation_id == conversation_id)
        )
        return result.scalar_one_or_none()
