"""Conversation service - business logic orchestration layer."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import structlog
from fastapi import HTTPException, status
from sqlalchemy import CursorResult, delete, func, inspect, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import ColumnElement

from app.core.encryption import hash_phone
from app.db.pagination import paginate
from app.models.agent import Agent
from app.models.campaign import CampaignContact
from app.models.contact import Contact
from app.models.conversation import (
    Conversation,
    Message,
    MessageChannel,
    MessageDirection,
)
from app.models.workspace import WorkspaceIntegration
from app.schemas.conversation import (
    ConversationResponse,
    ConversationWithMessages,
    FollowupGenerateResponse,
    FollowupSendResponse,
    FollowupSettingsResponse,
    MarkAllReadResponse,
    MessageResponse,
    PaginatedConversations,
    PaginatedMessages,
    UnreadSummary,
)
from app.services.ai.openai_credentials import (
    OpenAICredentialContext,
    OpenAICredentialError,
    resolve_openai_credentials,
)
from app.services.ai.text_response_generator import generate_followup_message
from app.services.campaigns.conversation_syncer import CampaignConversationSyncer
from app.services.quo.line import (
    get_active_quo_line,
    visible_conversation_provider_clause,
)
from app.services.quo.outbound import (
    QuoOutboundSender,
    QuoRequestConflictError,
    QuoSendRejectedError,
    QuoSendStatusUnknownError,
    claim_quo_send_attempt,
    execute_quo_send,
    get_quo_send_replay,
    reconcile_accepted_quo_send,
)
from app.services.rate_limiting.opt_out_manager import OptOutManager
from app.services.telephony.text_provider import (
    get_text_message_provider,
    provider_for_conversation,
)

logger = structlog.get_logger()


def _quo_status_unknown_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "quo_send_status_unknown",
            "message": "Delivery status unknown—wait for the message to appear before retrying",
        },
    )


def _quo_rejected_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail={"code": "quo_send_rejected", "message": "Quo rejected the message"},
    )


def _quo_manual_only_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Quo conversations support manual messaging only",
    )


async def _quo_replay_message(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    client_request_id: uuid.UUID,
) -> Message | None:
    try:
        replay = await get_quo_send_replay(
            db,
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            client_request_id=client_request_id,
        )
    except QuoRequestConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client request ID is already in use",
        ) from exc
    except QuoSendRejectedError as exc:
        raise _quo_rejected_http_error() from exc
    except QuoSendStatusUnknownError as exc:
        raise _quo_status_unknown_http_error() from exc
    if replay is None:
        return None
    if replay.replay_message is None:  # pragma: no cover - helper invariant
        raise _quo_status_unknown_http_error()
    return replay.replay_message


def serialize_conversation(conversation: Conversation) -> ConversationResponse:
    """Serialize a conversation, adding the linked contact's display name.

    ``Conversation.contact`` lazy-loads by default, and a lazy load on an async
    session raises ``MissingGreenlet``. Callers that want the name must eager
    load the relationship (``selectinload(Conversation.contact)``); when it is
    not loaded we return ``None`` rather than blowing up a whole response over
    a display label.
    """
    response = ConversationResponse.model_validate(conversation)
    if "contact" not in inspect(conversation).unloaded:
        contact = conversation.contact
        response.contact_name = contact.full_name if contact else None
    return response


class ConversationService:
    """High-level conversation service for orchestrating business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="conversation")
        self._syncer = CampaignConversationSyncer()

    async def _visible_provider_clause(
        self,
        workspace_id: uuid.UUID,
    ) -> ColumnElement[bool]:
        return await visible_conversation_provider_clause(self.db, workspace_id)

    async def _get_conversation(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        load_contact: bool = False,
    ) -> Conversation:
        """Fetch a conversation or raise 404.

        ``load_contact`` eager loads the contact for callers that serialize the
        thread for the UI; senders and workers skip the extra SELECT.
        """
        query = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
        )
        if load_contact:
            query = query.options(selectinload(Conversation.contact))
        result = await self.db.execute(query)
        conversation = result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if getattr(conversation, "source_provider", None) == "quo":
            active_line = await get_active_quo_line(self.db, workspace_id)
            if active_line is None or conversation.workspace_phone_hash != hash_phone(
                active_line.phone_number
            ):
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
        search: str | None = None,
    ) -> PaginatedConversations:
        """List conversations in a workspace with batch campaign sync.

        ``search`` matches the contact's name only. Message bodies and phone
        numbers are encrypted at rest under a non-deterministic cipher, so
        neither can be matched in SQL -- searching them would mean decrypting
        every row in the workspace on every keystroke.
        """
        visible_provider = await self._visible_provider_clause(workspace_id)
        query = (
            select(Conversation)
            .options(selectinload(Conversation.contact))
            .where(
                Conversation.workspace_id == workspace_id,
                visible_provider,
            )
        )

        if status_filter:
            query = query.where(Conversation.status == status_filter)
        if channel_filter:
            query = query.where(Conversation.channel == channel_filter)
        if unread_only:
            query = query.where(Conversation.unread_count > 0)
        if search:
            # Inner join: a thread with no linked contact has no name to match,
            # so dropping it is the right answer rather than a lost row.
            query = query.join(Contact, Conversation.contact_id == Contact.id).where(
                (Contact.first_name.ilike(f"%{search}%"))
                | (Contact.last_name.ilike(f"%{search}%"))
            )

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
                if conv.source_provider == "quo":
                    continue
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
            items=[serialize_conversation(c) for c in conversations],
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
        conversation = await self._get_conversation(
            conversation_id, workspace_id, load_contact=True
        )

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
            **serialize_conversation(conversation).model_dump(),
            messages=[MessageResponse.model_validate(m) for m in messages],
        )

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedMessages:
        """Page back through one thread's messages, newest page first.

        Separate from ``get_conversation`` on purpose. That method marks the
        thread read and caps the thread at its newest ``limit`` messages, which
        makes it wrong for an archive: browsing old threads would silently clear
        unread badges the operator never looked at, and history older than the
        cap would be unreachable.

        Each page is ordered newest-first for paging, then reversed so callers
        render it in reading order.
        """
        # Scope check first: raises 404 for another workspace's thread, so this
        # never leaks messages across tenants.
        await self._get_conversation(conversation_id, workspace_id)

        query = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
        )
        result = await paginate(self.db, query, page=page, page_size=page_size)
        return PaginatedMessages(
            items=[
                MessageResponse.model_validate(m) for m in reversed(list(result.items))
            ],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
        )

    async def get_unread_summary(self, workspace_id: uuid.UUID) -> UnreadSummary:
        """Roll up unread counts for the workspace.

        One aggregate query rather than paging the thread list, because the
        header badge polls this from every screen in the app.
        """
        visible_provider = await self._visible_provider_clause(workspace_id)
        result = await self.db.execute(
            select(
                func.count(Conversation.id),
                func.coalesce(func.sum(Conversation.unread_count), 0),
            ).where(
                Conversation.workspace_id == workspace_id,
                visible_provider,
                Conversation.unread_count > 0,
            )
        )
        conversations, messages = result.one()
        return UnreadSummary(
            unread_conversations=int(conversations or 0),
            unread_messages=int(messages or 0),
        )

    async def mark_read(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> ConversationResponse:
        """Clear the unread counter on one thread.

        Returns the updated thread so the caller can patch its cache without a
        refetch. Idempotent: already-read threads skip the write entirely.
        """
        conversation = await self._get_conversation(
            conversation_id, workspace_id, load_contact=True
        )
        if conversation.unread_count:
            conversation.unread_count = 0
            await self.db.commit()
        return serialize_conversation(conversation)

    async def mark_all_read(self, workspace_id: uuid.UUID) -> MarkAllReadResponse:
        """Clear unread counters across the workspace in a single statement."""
        visible_provider = await self._visible_provider_clause(workspace_id)
        result = await self.db.execute(
            update(Conversation)
            .where(
                Conversation.workspace_id == workspace_id,
                visible_provider,
                Conversation.unread_count > 0,
            )
            .values(unread_count=0)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        # ``execute`` is typed as returning ``Result``; a bulk UPDATE always
        # yields a ``CursorResult``, which is where ``rowcount`` lives. The cast
        # target is written as an expression rather than a string so static
        # analysis can see both names being used.
        rowcount = cast(CursorResult[Any], result).rowcount
        return MarkAllReadResponse(conversations_marked=rowcount or 0)

    async def send_message(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        body: str,
        sender_user_id: int | None = None,
        sender_display_name: str | None = None,
        client_request_id: uuid.UUID | None = None,
    ) -> Message:
        """Send through the provider bound to the workspace-scoped conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)

        if getattr(conversation, "source_provider", None) == "quo":
            message = await self._send_quo_message(
                conversation=conversation,
                workspace_id=workspace_id,
                body=body,
                sender_user_id=sender_user_id,
                sender_display_name=sender_display_name,
                client_request_id=client_request_id,
            )
        else:
            sms_service = get_text_message_provider(provider_for_conversation(conversation))
            try:
                message = await sms_service.send_message(
                    to_number=conversation.contact_phone,
                    from_number=conversation.workspace_phone,
                    body=body,
                    db=self.db,
                    workspace_id=workspace_id,
                    sender_user_id=sender_user_id,
                    sender_display_name=sender_display_name,
                )
            finally:
                await sms_service.close()

        # A successful human outbound reply completes the current SMS exchange.
        # Memory is best-effort and must never turn a delivered message into a 500.
        try:
            from app.services.ai.contact_ai_memory_service import (
                refresh_contact_ai_memory_from_sms,
            )

            updated = await refresh_contact_ai_memory_from_sms(
                self.db,
                workspace_id=workspace_id,
                conversation_id=conversation_id,
                completed_message_id=message.id,
            )
            if updated:
                await self.db.commit()
        except Exception as exc:  # noqa: BLE001 - post-send enrichment must degrade safely
            await self.db.rollback()
            self.log.warning(
                "contact_ai_memory_sms_refresh_failed",
                workspace_id=str(workspace_id),
                conversation_id=str(conversation_id),
                message_id=str(message.id),
                error_type=type(exc).__name__,
            )
        return message

    async def _send_quo_message(
        self,
        *,
        conversation: Conversation,
        workspace_id: uuid.UUID,
        body: str,
        sender_user_id: int | None,
        sender_display_name: str | None,
        client_request_id: uuid.UUID | None,
    ) -> Message:
        if conversation.channel != MessageChannel.SMS or not body.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Quo manual messaging supports non-empty text only",
            )
        if client_request_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A client request ID is required for Quo messages",
            )

        replay_message = await _quo_replay_message(
            self.db,
            workspace_id=workspace_id,
            conversation_id=conversation.id,
            client_request_id=client_request_id,
        )
        if replay_message is not None:
            return replay_message

        api_key, selected_phone = await self._quo_send_credentials(
            workspace_id=workspace_id,
            conversation=conversation,
        )
        await self._enforce_quo_consent(
            workspace_id=workspace_id,
            conversation=conversation,
        )
        try:
            claim = await claim_quo_send_attempt(
                self.db,
                workspace_id=workspace_id,
                conversation_id=conversation.id,
                client_request_id=client_request_id,
            )
        except QuoRequestConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Client request ID is already in use",
            ) from exc
        except QuoSendRejectedError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Quo rejected the message",
            ) from exc
        except QuoSendStatusUnknownError as exc:
            raise _quo_status_unknown_http_error() from exc
        if claim.replay_message is not None:
            return claim.replay_message

        quo_sender = QuoOutboundSender(api_key)
        try:
            accepted = await execute_quo_send(
                self.db,
                attempt=claim.attempt,
                sender=quo_sender,
                content=body,
                from_number=selected_phone,
                to_number=conversation.contact_phone,
            )
            return await reconcile_accepted_quo_send(
                self.db,
                workspace_id=workspace_id,
                conversation=conversation,
                attempt=claim.attempt,
                accepted=accepted,
                content=body,
                from_number=selected_phone,
                to_number=conversation.contact_phone,
                sender_user_id=sender_user_id,
                sender_display_name=sender_display_name,
            )
        except QuoSendRejectedError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Quo rejected the message",
            ) from exc
        except QuoSendStatusUnknownError as exc:
            raise _quo_status_unknown_http_error() from exc
        finally:
            await quo_sender.close()

    async def _quo_send_credentials(
        self,
        *,
        workspace_id: uuid.UUID,
        conversation: Conversation,
    ) -> tuple[str, str]:
        integration = await self.db.scalar(
            select(WorkspaceIntegration).where(
                WorkspaceIntegration.workspace_id == workspace_id,
                WorkspaceIntegration.integration_type == "quo",
                WorkspaceIntegration.is_active.is_(True),
            )
        )
        credentials = integration.safe_credentials() if integration is not None else None
        api_key = credentials.get("api_key") if credentials else None
        phone_number_id = credentials.get("phone_number_id") if credentials else None
        selected_phone = credentials.get("phone_number") if credentials else None
        if (
            not isinstance(api_key, str)
            or not api_key.strip()
            or not isinstance(phone_number_id, str)
            or not phone_number_id.strip()
            or not isinstance(selected_phone, str)
            or selected_phone != conversation.workspace_phone
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Select this conversation's Quo phone number in Settings before sending",
            )
        return api_key, selected_phone

    async def _enforce_quo_consent(
        self,
        *,
        workspace_id: uuid.UUID,
        conversation: Conversation,
    ) -> None:
        consent_status: str | None = None
        if conversation.contact_id is not None:
            consent_status = await self.db.scalar(
                select(Contact.sms_consent_status).where(
                    Contact.id == conversation.contact_id,
                    Contact.workspace_id == workspace_id,
                )
            )
        globally_opted_out = await OptOutManager().check_opt_out(
            workspace_id,
            conversation.contact_phone,
            self.db,
        )
        if consent_status == "opted_out" or globally_opted_out:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This contact has opted out of SMS",
            )
        if consent_status == "opted_in":
            return
        if consent_status not in {None, "unknown"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Recorded SMS consent is required before sending",
            )

        inbound_message_id = await self.db.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == conversation.id,
                Message.channel == MessageChannel.SMS,
                Message.direction == MessageDirection.INBOUND,
            )
            .limit(1)
        )
        if inbound_message_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Recorded SMS consent or an inbound reply is required before sending",
            )

    async def toggle_ai(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        enabled: bool,
    ) -> dict[str, bool]:
        """Toggle AI for a conversation."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        if getattr(conversation, "source_provider", None) == "quo" and enabled:
            raise _quo_manual_only_http_error()
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
        if getattr(conversation, "source_provider", None) == "quo":
            raise _quo_manual_only_http_error()
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
        if getattr(conversation, "source_provider", None) == "quo":
            raise _quo_manual_only_http_error()

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

    async def _resolve_followup_openai_credential(
        self,
        workspace_id: uuid.UUID,
    ) -> OpenAICredentialContext:
        try:
            return await resolve_openai_credentials(self.db, workspace_id)
        except OpenAICredentialError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI service not configured",
            ) from exc

    async def generate_followup(
        self,
        conversation_id: uuid.UUID,
        workspace_id: uuid.UUID,
        custom_instructions: str | None = None,
    ) -> FollowupGenerateResponse:
        """Generate a follow-up message preview (does not send)."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        if getattr(conversation, "source_provider", None) == "quo":
            raise _quo_manual_only_http_error()

        credential = await self._resolve_followup_openai_credential(workspace_id)
        message = await generate_followup_message(
            conversation=conversation,
            db=self.db,
            openai_api_key=credential.bearer_token,
            custom_instructions=custom_instructions,
            credential=credential,
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
        sender_user_id: int | None = None,
        sender_display_name: str | None = None,
    ) -> FollowupSendResponse:
        """Send a follow-up message. Generates one if not provided."""
        conversation = await self._get_conversation(conversation_id, workspace_id)
        if getattr(conversation, "source_provider", None) == "quo":
            raise _quo_manual_only_http_error()

        message_body = message
        if not message_body:
            credential = await self._resolve_followup_openai_credential(workspace_id)
            message_body = await generate_followup_message(
                conversation=conversation,
                db=self.db,
                openai_api_key=credential.bearer_token,
                custom_instructions=custom_instructions,
                credential=credential,
            )

            if not message_body:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to generate follow-up message",
                )

        sms_service = get_text_message_provider(provider_for_conversation(conversation))
        try:
            sent_msg = await sms_service.send_message(
                to_number=conversation.contact_phone,
                from_number=conversation.workspace_phone,
                body=message_body,
                db=self.db,
                workspace_id=workspace_id,
                sender_user_id=sender_user_id,
                sender_display_name=sender_display_name,
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
        if getattr(conversation, "source_provider", None) == "quo":
            raise _quo_manual_only_http_error()

        conversation.followup_count_sent = 0

        if conversation.followup_enabled:
            conversation.next_followup_at = datetime.now(UTC) + timedelta(
                hours=conversation.followup_delay_hours
            )

        await self.db.commit()
        return {"count_sent": 0}
