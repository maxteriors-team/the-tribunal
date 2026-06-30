"""Automation schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Trigger identifiers accepted by the automation engine. Combines the legacy
# generic kinds (event/schedule/condition), the polling triggers evaluated
# against contacts, and the event triggers drained from ``automation_events``.
AUTOMATION_TRIGGER_TYPES: tuple[str, ...] = (
    # Generic / legacy kinds
    "event",
    "schedule",
    "condition",
    # Polling triggers (contact-centric)
    "appointment_booked",
    "booking_created",
    "no_show",
    "contact_tagged",
    "never_booked",
    # Event triggers (emitted by services)
    "review_received",
    "review_request_response",
    "opportunity_created",
    "deal_stage_changed",
    "missed_call",
    "roleplay_completed",
    "knowledge_document_uploaded",
    # Billing & field-service lifecycle triggers
    "quote_sent",
    "quote_approved",
    "quote_declined",
    "quote_converted",
    "invoice_sent",
    "invoice_paid",
    "job_scheduled",
    "job_completed",
)

_TRIGGER_PATTERN = "^(" + "|".join(AUTOMATION_TRIGGER_TYPES) + ")$"


class AutomationActionSchema(BaseModel):
    """Schema for automation action."""

    type: str = Field(
        ...,
        description=(
            "Action type: send_sms, send_email, make_call, enroll_campaign, "
            "apply_tag/add_tag, wait/delay"
        ),
    )
    config: dict[str, Any] = Field(
        default_factory=dict, description="Action-specific configuration"
    )


class AutomationCreate(BaseModel):
    """Schema for creating an automation."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str = Field(default="event", pattern=_TRIGGER_PATTERN)
    trigger_config: dict[str, Any] = Field(default_factory=dict)
    actions: list[AutomationActionSchema] = Field(default_factory=list)
    is_active: bool = True


class AutomationUpdate(BaseModel):
    """Schema for updating an automation."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    trigger_type: str | None = Field(default=None, pattern=_TRIGGER_PATTERN)
    trigger_config: dict[str, Any] | None = None
    actions: list[AutomationActionSchema] | None = None
    is_active: bool | None = None


class AutomationResponse(BaseModel):
    """Schema for automation response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    trigger_type: str
    trigger_config: dict[str, Any]
    actions: list[dict[str, Any]]
    is_active: bool
    last_triggered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedAutomations(BaseModel):
    """Paginated automations response."""

    items: list[AutomationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class AutomationStatsResponse(BaseModel):
    """Automation statistics response."""

    total: int
    active: int
    triggered_today: int
