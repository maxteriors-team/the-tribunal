"""Call feedback management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.call_feedback import CallFeedback
from app.models.call_outcome import CallOutcome
from app.models.conversation import Message
from app.models.workspace import Workspace
from app.schemas.call_feedback import (
    CallFeedbackCreate,
    CallFeedbackListResponse,
    CallFeedbackResponse,
    CallFeedbackSummary,
)

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

    if not message.conversation or message.conversation.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found",
        )

    return message


@router.post("", response_model=CallFeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    body: CallFeedbackCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CallFeedbackResponse:
    """Submit feedback for a call."""
    await _get_message_for_workspace(db, workspace_id, message_id)

    # Get call outcome ID if it exists
    outcome_result = await db.execute(
        select(CallOutcome.id).where(CallOutcome.message_id == message_id)
    )
    outcome_id = outcome_result.scalar_one_or_none()

    feedback = CallFeedback(
        message_id=message_id,
        call_outcome_id=outcome_id,
        source=body.source,
        user_id=current_user.id if body.source == "user" else None,
        rating=body.rating,
        thumbs=body.thumbs,
        feedback_text=body.feedback_text,
        feedback_signals=body.feedback_signals,
        quality_score=body.quality_score,
        quality_reasoning=body.quality_reasoning,
    )

    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return CallFeedbackResponse.model_validate(feedback)


@router.get("", response_model=CallFeedbackListResponse)
async def list_feedback(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CallFeedbackListResponse:
    """List all feedback for a call."""
    await _get_message_for_workspace(db, workspace_id, message_id)

    result = await db.execute(
        select(CallFeedback)
        .where(CallFeedback.message_id == message_id)
        .order_by(CallFeedback.created_at.desc())
    )
    feedback_list = result.scalars().all()

    return CallFeedbackListResponse(
        items=[CallFeedbackResponse.model_validate(f) for f in feedback_list],
        total=len(feedback_list),
    )


@router.get("/summary", response_model=CallFeedbackSummary)
async def get_feedback_summary(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> CallFeedbackSummary:
    """Get aggregated feedback summary for a call."""
    await _get_message_for_workspace(db, workspace_id, message_id)

    # Aggregate feedback
    result = await db.execute(
        select(
            func.count(CallFeedback.id).label("total"),
            func.avg(CallFeedback.rating).label("avg_rating"),
            func.avg(CallFeedback.quality_score).label("avg_quality"),
            func.sum(func.case((CallFeedback.thumbs == "up", 1), else_=0)).label("thumbs_up"),
            func.sum(func.case((CallFeedback.thumbs == "down", 1), else_=0)).label("thumbs_down"),
            func.sum(func.case((CallFeedback.source == "user", 1), else_=0)).label("user_count"),
            func.sum(func.case((CallFeedback.source == "auto_quality", 1), else_=0)).label(
                "auto_count"
            ),
        ).where(CallFeedback.message_id == message_id)
    )
    row = result.one()

    return CallFeedbackSummary(
        message_id=message_id,
        total_feedback=row.total or 0,
        avg_rating=float(row.avg_rating) if row.avg_rating else None,
        avg_quality_score=float(row.avg_quality) if row.avg_quality else None,
        thumbs_up_count=row.thumbs_up or 0,
        thumbs_down_count=row.thumbs_down or 0,
        has_user_feedback=(row.user_count or 0) > 0,
        has_auto_quality=(row.auto_count or 0) > 0,
    )
