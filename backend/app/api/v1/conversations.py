"""Conversations and messages endpoints."""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CanReadCRM, CanSendComms, CanWriteCRM, CurrentUser
from app.models.conversation import Message
from app.schemas.conversation import (
    AgentAssign,
    AIToggle,
    ConversationWithMessages,
    FollowupGenerateRequest,
    FollowupGenerateResponse,
    FollowupSendRequest,
    FollowupSendResponse,
    FollowupSettingsResponse,
    FollowupSettingsUpdate,
    MessageCreate,
    MessageResponse,
    PaginatedConversations,
)
from app.services.conversations import ConversationService

router = APIRouter()


@router.get("", response_model=PaginatedConversations)
async def list_conversations(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = None,
    channel_filter: str | None = None,
    unread_only: bool = False,
) -> PaginatedConversations:
    """List conversations in a workspace."""
    svc = ConversationService(db)
    return await svc.list_conversations(
        workspace_id=workspace_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        channel_filter=channel_filter,
        unread_only=unread_only,
    )


@router.get("/{conversation_id}", response_model=ConversationWithMessages)
async def get_conversation(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
    limit: int = Query(50, ge=1, le=200),
) -> ConversationWithMessages:
    """Get a conversation with its messages."""
    svc = ConversationService(db)
    return await svc.get_conversation(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        limit=limit,
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message_in: MessageCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
) -> Message:
    """Send a message in a conversation."""
    svc = ConversationService(db)
    return await svc.send_message(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        body=message_in.body,
    )


@router.post("/{conversation_id}/ai/toggle")
async def toggle_ai(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    toggle: AIToggle,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> dict[str, bool]:
    """Toggle AI for a conversation."""
    svc = ConversationService(db)
    return await svc.toggle_ai(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        enabled=toggle.enabled,
    )


@router.post("/{conversation_id}/ai/pause")
async def pause_ai(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> dict[str, bool]:
    """Pause AI for a conversation (temporary)."""
    svc = ConversationService(db)
    return await svc.pause_ai(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


@router.post("/{conversation_id}/ai/resume")
async def resume_ai(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> dict[str, bool]:
    """Resume AI for a conversation."""
    svc = ConversationService(db)
    return await svc.resume_ai(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


@router.post("/{conversation_id}/assign")
async def assign_agent(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    assign: AgentAssign,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> dict[str, uuid.UUID | None]:
    """Assign an agent to a conversation."""
    svc = ConversationService(db)
    return await svc.assign_agent(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        agent_id=assign.agent_id,
    )


@router.delete("/{conversation_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_conversation_history(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> None:
    """Clear all messages in a conversation."""
    svc = ConversationService(db)
    await svc.clear_history(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


@router.get(
    "/{conversation_id}/followup/status",
    response_model=FollowupSettingsResponse,
)
async def get_followup_status(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> FollowupSettingsResponse:
    """Get follow-up settings and status for a conversation."""
    svc = ConversationService(db)
    return await svc.get_followup_status(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


@router.patch(
    "/{conversation_id}/followup/settings",
    response_model=FollowupSettingsResponse,
)
async def update_followup_settings(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    settings_update: FollowupSettingsUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> FollowupSettingsResponse:
    """Update follow-up settings for a conversation."""
    svc = ConversationService(db)
    return await svc.update_followup_settings(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        enabled=settings_update.enabled,
        delay_hours=settings_update.delay_hours,
        max_count=settings_update.max_count,
    )


@router.post(
    "/{conversation_id}/followup/generate",
    response_model=FollowupGenerateResponse,
)
async def generate_followup(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: FollowupGenerateRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> FollowupGenerateResponse:
    """Generate a follow-up message preview (does not send)."""
    svc = ConversationService(db)
    return await svc.generate_followup(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        custom_instructions=request.custom_instructions,
    )


@router.post(
    "/{conversation_id}/followup/send",
    response_model=FollowupSendResponse,
)
async def send_followup(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: FollowupSendRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanSendComms,
) -> FollowupSendResponse:
    """Send a follow-up message. Generates one if not provided."""
    svc = ConversationService(db)
    return await svc.send_followup(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        message=request.message,
        custom_instructions=request.custom_instructions,
    )


@router.post("/{conversation_id}/followup/reset")
async def reset_followup_counter(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> dict[str, int]:
    """Reset the follow-up counter to 0."""
    svc = ConversationService(db)
    return await svc.reset_followup_counter(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )
