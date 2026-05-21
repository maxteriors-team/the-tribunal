"""Pydantic schemas for outbound sequences, enrollments, and step attempts."""

import uuid
from datetime import datetime, time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.outbound_sequence import (
    OutboundSequenceStatus,
    SequenceEnrollmentStatus,
    SequenceStepAttemptStatus,
    SequenceStepChannel,
)

# --- Sequence -------------------------------------------------------------


class OutboundSequenceStep(BaseModel):
    """A single step in an outbound sequence."""

    order: int = Field(ge=0)
    channel: SequenceStepChannel
    delay_hours: int = Field(default=0, ge=0)
    template: str | None = None
    subject: str | None = None
    agent_id: uuid.UUID | None = None
    stop_on_reply: bool = True


class OutboundSequenceCreate(BaseModel):
    """Request to create an outbound sequence template."""

    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    is_default: bool = False
    steps: list[OutboundSequenceStep] = Field(default_factory=list)
    channel_priority: list[str] | None = None
    max_attempts_per_step: int = Field(default=1, ge=1)
    sending_hours_start: time | None = None
    sending_hours_end: time | None = None
    sending_days: list[int] | None = None
    timezone: str = Field(default="America/New_York", max_length=50)


class OutboundSequenceUpdate(BaseModel):
    """Partial update for an outbound sequence."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: OutboundSequenceStatus | None = None
    is_default: bool | None = None
    steps: list[OutboundSequenceStep] | None = None
    channel_priority: list[str] | None = None
    max_attempts_per_step: int | None = Field(default=None, ge=1)
    sending_hours_start: time | None = None
    sending_hours_end: time | None = None
    sending_days: list[int] | None = None
    timezone: str | None = Field(default=None, max_length=50)


class OutboundSequenceResponse(BaseModel):
    """Response for an outbound sequence."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    status: OutboundSequenceStatus
    is_default: bool
    steps: list[dict[str, Any]]
    channel_priority: list[str] | None
    max_attempts_per_step: int
    sending_hours_start: time | None
    sending_hours_end: time | None
    sending_days: list[int] | None
    timezone: str
    total_enrollments: int
    total_completed: int
    total_replied: int
    total_converted: int
    created_at: datetime
    updated_at: datetime


# --- Enrollment -----------------------------------------------------------


class OutboundSequenceEnrollmentResponse(BaseModel):
    """Response for a sequence enrollment."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    mission_id: uuid.UUID | None
    sequence_id: uuid.UUID
    prospect_id: uuid.UUID
    status: SequenceEnrollmentStatus
    current_step: int
    next_step_at: datetime | None
    last_attempt_at: datetime | None
    last_outcome: str | None
    cancel_reason: str | None
    attempts_made: int
    successful_attempts: int
    failed_attempts: int
    enrolled_at: datetime
    completed_at: datetime | None
    paused_until: datetime | None
    created_at: datetime
    updated_at: datetime


# --- Step attempt ---------------------------------------------------------


class OutboundSequenceStepAttemptResponse(BaseModel):
    """Response for a per-step attempt record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    enrollment_id: uuid.UUID
    prospect_id: uuid.UUID
    step_index: int
    attempt_number: int
    channel: SequenceStepChannel
    status: SequenceStepAttemptStatus
    scheduled_at: datetime
    sent_at: datetime | None
    completed_at: datetime | None
    message_id: uuid.UUID | None
    conversation_id: uuid.UUID | None
    pending_action_id: uuid.UUID | None
    outcome: str | None
    outcome_detail: dict[str, Any] | None
    error_message: str | None
    template_snapshot: str | None
    rendered_body: str | None
    rendered_subject: str | None
    created_at: datetime
    updated_at: datetime
