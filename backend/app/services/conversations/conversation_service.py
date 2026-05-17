"""Conversation service - business logic orchestration layer."""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.campaign import CampaignContact
from app.models.conversation import Conversation, Message
from app.schemas.conversation import (
    ConversationResponse,
    ConversationWithMessages,
    FollowupGenerateResponse,
    FollowupSendResponse,
    FollowupSettingsResponse,
    MessageResponse,
    PaginatedConversations,
)
from app.services.ai.text_response_generator import generate_followup_message
from app.services.campaigns.conversation_syncer import CampaignConversationSyncer
from app.services.telephony.telnyx import TelnyxSMSService

logger = structlog.get_logger()


class ConversationService:
    """High-level conversation service for orchestrating business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="conversation")
        self._syncer = CampaignConversationSyncer()

    async def _get_conversation(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> Conversation:
        """Fetch a conversation or raise 404."""
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
            )
        )
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        return conversation

    async def list_conversations(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        status_filter: str | None = None,
        channel_filter: str | None = None,
        unread_only: bool = False,
    ) -> PaginatedConversations:
        """List conversations in a workspace with batch campaign sync."""
        query = select(Conversation).where(Conversation.workspace_id == workspace_id)

        if status_filter:
            query = query.where(Conversation.status == status_filter)
        if channel_filter:
            query = query.where(Conversation.channel == channel_filter)
        if unread_only:
            query = query.where(Conversation.unread_count > 0)

        query = query.order_by(Conversation.last_message_at.desc().nullslast())
        result = await paginate(self.db, query, page=page, page_size=page_size)
        conversations = list(result.items)

        # Batch campaign agent sync
        if conversations:
            conversation_ids = [c.id for c in conversations]
            campaign_contacts_result = await self.db.execute(
                select(CampaignContact)
                .options(selectinload(CampaignContact.campaign))
                .where(CampaignContact.conversation_id.in_(conversation_ids))
            )
            campaign_contacts = campaign_contacts_result.scalars().all()

            campaign_by_conv_id = {
                cc.conversation_id: cc.campaign
                for cc in campaign_contacts
                if cc.campaign is not None
            }

            modified = False
            for conv in conversations:
                campaign = campaign_by_conv_id.get(conv.id)
                if campaign and campaign.agent_id:
                    if conv.assigned_agent_id != campaign.agent_id:
                        conv.assigned_agent_id = campaign.agent_id
                        modified = True
                    if campaign.ai_enabled and not conv.ai_enabled:
                        conv.ai_enabled = True
                        modified = True

            if modified:
                # Session is configured with expire_on_commit=False, so the
                # in-memory state we just set remains valid after commit.
                # No per-row refresh needed.
                await self.db.commit()

        return PaginatedConversations(
            items=[ConversationResponse.model_validate(c) for c in conversations],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
        )

    async def get_conversation(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        limit: int = 50,
    ) -> ConversationWithMessages:
        """Get a conversation with its messages."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        # Sync campaign agent (campaign always takes precedence)
        await self._syncer.sync_conversation(self.db, conversation, self.log)

        # Get messages
        messages_result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(reversed(messages_result.scalars().all()))

        # Mark as read
        conversation.unread_count = 0
        await self.db.commit()

        return ConversationWithMessages(
            **ConversationResponse.model_validate(conversation).model_dump(),
            messages=[MessageResponse.model_validate(m) for m in messages],
        )

    async def send_message(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        body: str,
    ) -> Message:
        """Send a message in a conversation via Telnyx SMS."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        telnyx_api_key = settings.telnyx_api_key
        if not telnyx_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SMS service not configured",
            )

        sms_service = TelnyxSMSService(telnyx_api_key)
        try:
            message = await sms_service.send_message(
                to_number=conversation.contact_phone,
                from_number=conversation.workspace_phone,
                body=body,
                db=self.db,
                workspace_id=workspace_id,
            )
            return message
        finally:
            await sms_service.close()

    async def toggle_ai(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        enabled: bool,
    ) -> dict[str, bool]:
        """Toggle AI for a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        conversation.ai_enabled = enabled
        await self.db.commit()
        return {"ai_enabled": conversation.ai_enabled}

    async def pause_ai(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, bool]:
        """Pause AI for a conversation (temporary)."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        conversation.ai_paused = True
        await self.db.commit()
        return {"ai_paused": True}

    async def resume_ai(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, bool]:
        """Resume AI for a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        conversation.ai_paused = False
        await self.db.commit()
        return {"ai_paused": False}

    async def assign_agent(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None,
    ) -> dict[str, uuid.UUID | None]:
        """Assign an agent to a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        if agent_id:
            agent_result = await self.db.execute(
                select(Agent).where(
                    Agent.id == agent_id,
                    Agent.workspace_id == workspace_id,
                )
            )
            agent = agent_result.scalar_one_or_none()
            if not agent:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found",
                )

        conversation.assigned_agent_id = agent_id
        await self.db.commit()
        return {"assigned_agent_id": conversation.assigned_agent_id}

    async def clear_history(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        """Clear all messages in a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        await self.db.execute(delete(Message).where(Message.conversation_id == conversation_id))

        conversation.last_message_preview = None
        conversation.last_message_at = None
        conversation.last_message_direction = None
        conversation.unread_count = 0
        await self.db.commit()

    async def get_followup_status(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> FollowupSettingsResponse:
        """Get follow-up settings and status for a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        return FollowupSettingsResponse(
            enabled=conversation.followup_enabled,
            delay_hours=conversation.followup_delay_hours,
            max_count=conversation.followup_max_count,
            count_sent=conversation.followup_count_sent,
            next_followup_at=conversation.next_followup_at,
            last_followup_at=conversation.last_followup_at,
        )

    async def update_followup_settings(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        enabled: bool | None = None,
        delay_hours: int | None = None,
        max_count: int | None = None,
    ) -> FollowupSettingsResponse:
        """Update follow-up settings for a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        if enabled is not None:
            conversation.followup_enabled = enabled
            if enabled and not conversation.next_followup_at:
                conversation.next_followup_at = datetime.now(UTC) + timedelta(
                    hours=conversation.followup_delay_hours
                )

        if delay_hours is not None:
            conversation.followup_delay_hours = delay_hours

        if max_count is not None:
            conversation.followup_max_count = max_count

        await self.db.commit()
        await self.db.refresh(conversation)

        return FollowupSettingsResponse(
            enabled=conversation.followup_enabled,
            delay_hours=conversation.followup_delay_hours,
            max_count=conversation.followup_max_count,
            count_sent=conversation.followup_count_sent,
            next_followup_at=conversation.next_followup_at,
            last_followup_at=conversation.last_followup_at,
        )

    async def generate_followup(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        custom_instructions: str | None = None,
    ) -> FollowupGenerateResponse:
        """Generate a follow-up message preview (does not send)."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        openai_key = settings.openai_api_key
        if not openai_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service not configured",
            )

        message = await generate_followup_message(
            conversation=conversation,
            db=self.db,
            openai_api_key=openai_key,
            custom_instructions=custom_instructions,
        )

        if not message:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate follow-up message",
            )

        return FollowupGenerateResponse(
            message=message,
            conversation_id=str(conversation_id),
        )

    async def send_followup(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        message: str | None = None,
        custom_instructions: str | None = None,
    ) -> FollowupSendResponse:
        """Send a follow-up message. Generates one if not provided."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        message_body = message
        if not message_body:
            openai_key = settings.openai_api_key
            if not openai_key:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="AI service not configured",
                )

            message_body = await generate_followup_message(
                conversation=conversation,
                db=self.db,
                openai_api_key=openai_key,
                custom_instructions=custom_instructions,
            )

            if not message_body:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to generate follow-up message",
                )

        telnyx_api_key = settings.telnyx_api_key
        if not telnyx_api_key:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="SMS service not configured",
            )

        sms_service = TelnyxSMSService(telnyx_api_key)
        try:
            sent_msg = await sms_service.send_message(
                to_number=conversation.contact_phone,
                from_number=conversation.workspace_phone,
                body=message_body,
                db=self.db,
                workspace_id=workspace_id,
            )

            # Update follow-up tracking
            conversation.followup_count_sent += 1
            conversation.last_followup_at = datetime.now(UTC)

            # Schedule next follow-up if still within limits
            if (
                conversation.followup_enabled
                and conversation.followup_count_sent < conversation.followup_max_count
            ):
                conversation.next_followup_at = datetime.now(UTC) + timedelta(
                    hours=conversation.followup_delay_hours
                )
            else:
                conversation.next_followup_at = None

            await self.db.commit()

            return FollowupSendResponse(
                success=True,
                message_id=str(sent_msg.id),
                message_body=message_body,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to send message: {e!s}",
            ) from e
        finally:
            await sms_service.close()

    async def reset_followup_counter(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, int]:
        """Reset the follow-up counter to 0."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        conversation.followup_count_sent = 0

        if conversation.followup_enabled:
            conversation.next_followup_at = datetime.now(UTC) + timedelta(
                hours=conversation.followup_delay_hours
            )

        await self.db.commit()
        return {"count_sent": 0}
