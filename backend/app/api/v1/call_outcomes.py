"""Call outcome management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.call_outcome import CallOutcome
from app.models.conversation import Message
from app.models.workspace import Workspace
from app.schemas.call_outcome import (
    CallOutcomeResponse,
    CallOutcomeUpdate,
    CallOutcomeWithContextResponse,
)
from app.services.ai.call_outcome_service import CallOutcomeService

router = APIRouter()


async def _get_message_for_workspace(
    db: DB,
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Message:
    """Get a message and verify it belongs to the workspace."""
    result = await db.execute(
        select(Message).options(selectinload(Message.conversation)).where(Message.id == message_id)
    )
    message = result.scalar_one_or_none()

    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    # Verify message belongs to workspace via conversation
    if not message.conversation or message.conversation.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    return message


@router.get("", response_model=CallOutcomeWithContextResponse | None)
async def get_call_outcome(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CallOutcomeWithContextResponse | None:
    """Get the call outcome for a message."""
    message = await _get_message_for_workspace(db, workspace_id, message_id)

    result = await db.execute(
        select(CallOutcome)
        .options(selectinload(CallOutcome.prompt_version))
        .where(CallOutcome.message_id == message_id)
    )
    outcome = result.scalar_one_or_none()

    if not outcome:
        return None

    # Build response with context
    response = CallOutcomeWithContextResponse(
        id=outcome.id,
        message_id=outcome.message_id,
        prompt_version_id=outcome.prompt_version_id,
        outcome_type=outcome.outcome_type,
        signals=outcome.signals,
        classified_by=outcome.classified_by,
        classification_confidence=outcome.classification_confidence,
        raw_hangup_cause=outcome.raw_hangup_cause,
        created_at=outcome.created_at,
        updated_at=outcome.updated_at,
        call_duration_seconds=message.duration_seconds,
        call_direction=message.direction,
        booking_outcome=message.booking_outcome,
    )

    # Add prompt version context
    if outcome.prompt_version:
        response.prompt_version_number = outcome.prompt_version.version_number
        response.prompt_is_baseline = outcome.prompt_version.is_baseline

    return response


@router.put("", response_model=CallOutcomeResponse)
async def update_call_outcome(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    body: CallOutcomeUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CallOutcomeResponse:
    """Update or reclassify a call outcome."""
    await _get_message_for_workspace(db, workspace_id, message_id)

    result = await db.execute(select(CallOutcome).where(CallOutcome.message_id == message_id))
    outcome = result.scalar_one_or_none()

    if not outcome:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call outcome not found",
        )

    service = CallOutcomeService()
    updated = await service.update_outcome(
        db=db,
        outcome_id=outcome.id,
        outcome_type=body.outcome_type,
        signals=body.signals,
        classified_by=body.classified_by or "user",  # Mark as user-classified
        classification_confidence=body.classification_confidence,
    )

    return CallOutcomeResponse.model_validate(updated)
