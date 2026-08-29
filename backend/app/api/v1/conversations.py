"""Conversations and messages endpoints."""

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CanReadCRM, CanSendComms, CanWriteCRM, CurrentUser
from app.models.conversation import Message
from app.schemas.conversation import (
    AgentAssign,
    AIToggle,
    ConversationResponse,
    ConversationWithMessages,
    FollowupGenerateRequest,
    FollowupGenerateResponse,
    FollowupSendRequest,
    FollowupSendResponse,
    FollowupSettingsResponse,
    FollowupSettingsUpdate,
    MarkAllReadResponse,
    MessageCreate,
    MessageResponse,
    PaginatedConversations,
    TeachAIRequest,
    TeachAIResponse,
    UnreadSummary,
)
from app.schemas.conversation_note import (
    ConversationNoteCreate,
    ConversationNoteResponse,
    ConversationNoteUpdate,
    NoteReminderCreate,
)
from app.services.ai.teach_ai import save_training_example
from app.services.conversations import ConversationService
from app.services.conversations.note_service import ConversationNoteService

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


# NOTE: the two static paths below must stay ABOVE `/{conversation_id}`. FastAPI
# matches routes in declaration order, so a later `GET /unread` would be
# swallowed by the UUID path param and fail validation with a 422.
@router.get("/unread", response_model=UnreadSummary)
async def get_unread_summary(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> UnreadSummary:
    """Unread rollup for the workspace, polled by the header chat badge."""
    svc = ConversationService(db)
    return await svc.get_unread_summary(workspace_id=workspace_id)


@router.post("/read", response_model=MarkAllReadResponse)
async def mark_all_conversations_read(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> MarkAllReadResponse:
    """Mark every conversation in the workspace as read."""
    svc = ConversationService(db)
    return await svc.mark_all_read(workspace_id=workspace_id)


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


# Unread state is shared across the workspace and `GET /{conversation_id}`
# already clears it, so this deliberately requires only CRM read — anyone who
# can open the inbox can clear its badge.
@router.post("/{conversation_id}/read", response_model=ConversationResponse)
async def mark_conversation_read(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ConversationResponse:
    """Mark a single conversation as read."""
    svc = ConversationService(db)
    return await svc.mark_read(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


@router.post("/{conversation_id}/teach-ai", response_model=TeachAIResponse)
async def teach_ai(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: TeachAIRequest,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteCRM,
) -> TeachAIResponse:
    """Save or update a human-approved correction for one AI SMS reply."""
    saved = await save_training_example(
        db,
        workspace_id=workspace_id,
        conversation_id=conversation_id,
        source_message_id=request.source_message_id,
        ideal_response=request.ideal_response.strip(),
        note=request.note.strip() if request.note else None,
        user_id=current_user.id,
    )
    example = saved.example
    return TeachAIResponse(
        id=example.id,
        workspace_id=example.workspace_id,
        agent_id=example.agent_id,
        conversation_id=example.conversation_id,
        source_message_id=example.source_message_id,
        ideal_response=example.ideal_response,
        note=example.operator_note,
        is_active=example.is_active,
        agent_name=saved.agent_name,
        created_at=example.created_at,
        updated_at=example.updated_at,
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
        sender_user_id=current_user.id,
        sender_display_name=current_user.full_name or current_user.email,
        client_request_id=message_in.client_request_id,
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
        sender_user_id=current_user.id,
        sender_display_name=current_user.full_name or current_user.email,
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


# ── Notes ────────────────────────────────────────────────────────────────────
# All four ride on CRM read: `crm:write` is deliberately the *destructive*
# contact tier (delete/bulk-delete/import, manager and above), so gating notes
# behind it would lock out the sales reps and techs who actually take them
# mid-call. Annotating a conversation you can already open is not a destructive
# contact power, and `mark_conversation_read` above sets the same precedent.
#
# The blast radius stays small because the service restricts edits and deletes
# to the note's author, so no one can rewrite a colleague's record of a call.


@router.get("/{conversation_id}/notes", response_model=list[ConversationNoteResponse])
async def list_conversation_notes(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> list[ConversationNoteResponse]:
    """List the notes on a conversation, oldest first."""
    svc = ConversationNoteService(db)
    return await svc.list_notes(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
    )


@router.post(
    "/{conversation_id}/notes",
    response_model=ConversationNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_note(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    request: ConversationNoteCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ConversationNoteResponse:
    """Add a note to a conversation."""
    svc = ConversationNoteService(db)
    return await svc.create_note(
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        author_user_id=current_user.id,
        body=request.body,
    )


@router.patch(
    "/{conversation_id}/notes/{note_id}",
    response_model=ConversationNoteResponse,
)
async def update_conversation_note(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    note_id: uuid.UUID,
    request: ConversationNoteUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ConversationNoteResponse:
    """Edit a note you wrote."""
    svc = ConversationNoteService(db)
    return await svc.update_note(
        note_id=note_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        body=request.body,
    )


@router.delete(
    "/{conversation_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_conversation_note(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    note_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> None:
    """Delete a note you wrote."""
    svc = ConversationNoteService(db)
    await svc.delete_note(
        note_id=note_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
    )


@router.put(
    "/{conversation_id}/notes/{note_id}/reminder",
    response_model=ConversationNoteResponse,
)
async def set_conversation_note_reminder(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    note_id: uuid.UUID,
    request: NoteReminderCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ConversationNoteResponse:
    """Set or move the follow-up reminder on a note you wrote."""
    svc = ConversationNoteService(db)
    return await svc.set_reminder(
        note_id=note_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
        due_at=request.due_at,
    )


@router.delete(
    "/{conversation_id}/notes/{note_id}/reminder",
    response_model=ConversationNoteResponse,
)
async def clear_conversation_note_reminder(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    note_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadCRM,
) -> ConversationNoteResponse:
    """Cancel the reminder on a note you wrote, keeping the note itself."""
    svc = ConversationNoteService(db)
    return await svc.clear_reminder(
        note_id=note_id,
        conversation_id=conversation_id,
        workspace_id=workspace_id,
        actor_user_id=current_user.id,
    )
