"""CRM assistant endpoints — operator chat with AI assistant."""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.assistant_conversation import AssistantConversation, AssistantMessage
from app.models.workspace import Workspace
from app.schemas.crm_assistant import (
    ActionSummary,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantConversationMetaResponse,
    AssistantConversationResponse,
    AssistantMessageResponse,
    AssistantRole,
)
from app.services.ai.crm_assistant import process_assistant_message, stream_assistant_message

router = APIRouter()


def _message_response(message: AssistantMessage) -> AssistantMessageResponse:
    """Serialize an assistant message row for API responses."""
    return AssistantMessageResponse(
        id=str(message.id),
        role=cast(AssistantRole, message.role),
        content=message.content,
        tool_calls=message.tool_calls,
        tool_call_id=message.tool_call_id,
        created_at=message.created_at,
    )


async def _conversation_response(
    db: AsyncSession,
    conversation: AssistantConversation,
) -> AssistantConversationResponse:
    """Serialize a full assistant conversation with ordered messages."""
    messages_result = await db.execute(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conversation.id)
        .order_by(AssistantMessage.created_at)
    )
    messages = messages_result.scalars().all()
    return AssistantConversationResponse(
        id=str(conversation.id),
        messages=[_message_response(message) for message in messages],
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def _get_scoped_conversation(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
    conversation_id: uuid.UUID,
) -> AssistantConversation:
    """Load one assistant conversation scoped to the workspace and current user."""
    result = await db.execute(
        select(AssistantConversation).where(
            AssistantConversation.id == conversation_id,
            AssistantConversation.workspace_id == workspace_id,
            AssistantConversation.user_id == user_id,
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assistant conversation not found",
        )
    return conversation


def _conversation_title(first_user_message: str | None) -> str:
    """Build a compact sidebar title from the first user message."""
    if not first_user_message:
        return "New chat"
    normalized = " ".join(first_user_message.split())
    if len(normalized) <= 64:
        return normalized
    return f"{normalized[:61]}…"


def _sse_frame(event: dict[str, Any]) -> str:
    """Encode one assistant stream event as an SSE data frame."""
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    workspace_id: uuid.UUID,
    request: AssistantChatRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AssistantChatResponse:
    """Send a message to the CRM assistant and get a response."""
    result = await process_assistant_message(
        db=db,
        workspace_id=workspace_id,
        user_id=current_user.id,
        message=request.message,
        conversation_id=request.conversation_id,
        image=request.image,
    )
    return AssistantChatResponse(
        response=result["response"],
        actions_taken=[ActionSummary(**a) for a in result["actions_taken"]],
        conversation_id=cast(str | None, result.get("conversation_id")),
    )


@router.post("/chat/stream")
async def stream_chat_with_assistant(
    workspace_id: uuid.UUID,
    request: AssistantChatRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> StreamingResponse:
    """Stream an assistant response as server-sent events."""

    async def event_stream() -> AsyncIterator[str]:
        async for event in stream_assistant_message(
            db=db,
            workspace_id=workspace_id,
            user_id=current_user.id,
            message=request.message,
            conversation_id=request.conversation_id,
            image=request.image,
        ):
            yield _sse_frame(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", response_model=AssistantConversationResponse | None)
async def get_assistant_history(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AssistantConversationResponse | None:
    """Get the latest conversation history with the CRM assistant."""
    conv_result = await db.execute(
        select(AssistantConversation)
        .where(
            AssistantConversation.workspace_id == workspace_id,
            AssistantConversation.user_id == current_user.id,
        )
        .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.created_at.desc())
        .limit(1)
    )
    conversation = conv_result.scalar_one_or_none()
    if conversation is None:
        return None
    return await _conversation_response(db, conversation)


@router.get("/conversations", response_model=list[AssistantConversationMetaResponse])
async def list_assistant_conversations(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[AssistantConversationMetaResponse]:
    """List assistant conversations for the current workspace and user."""
    message_counts_subquery = (
        select(
            AssistantMessage.conversation_id.label("conversation_id"),
            func.count(AssistantMessage.id).label("message_count"),
        )
        .group_by(AssistantMessage.conversation_id)
        .subquery()
    )
    first_user_message = (
        select(AssistantMessage.content)
        .where(
            AssistantMessage.conversation_id == AssistantConversation.id,
            AssistantMessage.role == "user",
        )
        .order_by(AssistantMessage.created_at)
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(
            AssistantConversation,
            func.coalesce(message_counts_subquery.c.message_count, 0),
            first_user_message,
        )
        .outerjoin(
            message_counts_subquery,
            message_counts_subquery.c.conversation_id == AssistantConversation.id,
        )
        .where(
            AssistantConversation.workspace_id == workspace_id,
            AssistantConversation.user_id == current_user.id,
        )
        .order_by(AssistantConversation.updated_at.desc(), AssistantConversation.created_at.desc())
    )
    return [
        AssistantConversationMetaResponse(
            id=str(conversation.id),
            title=_conversation_title(cast(str | None, first_user_message)),
            message_count=int(message_count or 0),
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
        )
        for conversation, message_count, first_user_message in result.all()
    ]


@router.get(
    "/conversations/{conversation_id}",
    response_model=AssistantConversationResponse,
)
async def get_assistant_conversation(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AssistantConversationResponse:
    """Load one assistant conversation with messages."""
    conversation = await _get_scoped_conversation(
        db,
        workspace_id,
        current_user.id,
        conversation_id,
    )
    return await _conversation_response(db, conversation)


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_assistant_conversation(
    workspace_id: uuid.UUID,
    conversation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete one assistant conversation for the current workspace and user."""
    conversation = await _get_scoped_conversation(
        db,
        workspace_id,
        current_user.id,
        conversation_id,
    )
    await db.delete(conversation)
    await db.commit()
