"""Pending action schemas for HITL approval gate endpoints."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from app.models.pending_action import PendingAction


class PendingActionResponse(BaseModel):
    """Schema for pending action response."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None
    action_type: str
    action_payload: dict[str, Any]
    description: str
    context: dict[str, Any]
    status: str
    urgency: str
    reviewed_by_id: int | None
    reviewed_at: str | None
    review_channel: str | None
    rejection_reason: str | None
    executed_at: str | None
    execution_result: dict[str, Any] | None
    expires_at: str | None
    notification_sent: bool
    notification_sent_at: str | None
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


def pending_action_response(action: PendingAction) -> PendingActionResponse:
    """Serialize one pending-action ORM row for HTTP and stream responses."""
    return PendingActionResponse(
        id=action.id,
        workspace_id=action.workspace_id,
        agent_id=action.agent_id,
        action_type=action.action_type,
        action_payload=action.action_payload,
        description=action.description,
        context=action.context,
        status=action.status,
        urgency=action.urgency,
        reviewed_by_id=action.reviewed_by_id,
        reviewed_at=action.reviewed_at.isoformat() if action.reviewed_at else None,
        review_channel=action.review_channel,
        rejection_reason=action.rejection_reason,
        executed_at=action.executed_at.isoformat() if action.executed_at else None,
        execution_result=action.execution_result,
        expires_at=action.expires_at.isoformat() if action.expires_at else None,
        notification_sent=action.notification_sent,
        notification_sent_at=(
            action.notification_sent_at.isoformat() if action.notification_sent_at else None
        ),
        created_at=action.created_at.isoformat(),
        updated_at=action.updated_at.isoformat(),
    )


class PendingActionListResponse(BaseModel):
    """Schema for paginated pending action list."""

    items: list[PendingActionResponse]
    total: int
    page: int
    page_size: int
    pages: int


class ApproveActionRequest(BaseModel):
    """Schema for approving a pending action."""

    notes: str | None = None


class RejectActionRequest(BaseModel):
    """Schema for rejecting a pending action."""

    reason: str | None = None
