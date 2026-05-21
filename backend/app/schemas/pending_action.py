"""Pending action schemas for HITL approval gate endpoints."""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict


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
