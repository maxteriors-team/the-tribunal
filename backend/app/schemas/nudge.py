"""Nudge schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NudgeResponse(BaseModel):
    """Response schema for a single nudge."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    # None for workspace-level operator nudges (not tied to a contact).
    contact_id: int | None
    nudge_type: str
    title: str
    message: str
    suggested_action: str | None
    priority: str
    due_date: datetime
    source_date_field: str | None
    status: str
    snoozed_until: datetime | None
    delivered_via: str | None
    delivered_at: datetime | None
    acted_at: datetime | None
    assigned_to_user_id: int | None
    created_at: datetime

    # Populated from relationship
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_company: str | None = None

    model_config = ConfigDict(from_attributes=True)


class NudgeListResponse(BaseModel):
    """Paginated nudge list."""

    items: list[NudgeResponse]
    total: int
    page: int
    page_size: int


class NudgeStatsResponse(BaseModel):
    """Nudge counts by status."""

    pending: int = 0
    sent: int = 0
    acted: int = 0
    dismissed: int = 0
    snoozed: int = 0
    total: int = 0


class NudgeSnoozeRequest(BaseModel):
    """Request to snooze a nudge."""

    snooze_until: datetime


class NudgeSettingsResponse(BaseModel):
    """Workspace nudge settings."""

    enabled: bool = True
    lead_days: int = 3
    nudge_types: list[str] = Field(
        default_factory=lambda: [
            "birthday",
            "anniversary",
            "custom",
            "cooling",
            "follow_up",
            "deal_milestone",
            "noshow_recovery",
            "unresponsive",
            "hot_lead",
            "referral_ask",
            "outbound_batch_ready",
            "approvals_waiting",
            "monitor_idle",
        ]
    )
    delivery_channels: list[str] = Field(default_factory=lambda: ["sms", "push"])
    cooling_days: int = 30
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "08:00"


class NudgeActRequest(BaseModel):
    """Request body for acting on a nudge."""

    action_taken: str | None = None  # "send_card", "call", "text", "email", or None


class NudgeSettingsUpdate(BaseModel):
    """Update nudge settings."""

    enabled: bool | None = None
    lead_days: int | None = Field(None, ge=1, le=30)
    nudge_types: list[str] | None = None
    delivery_channels: list[str] | None = None
    cooling_days: int | None = Field(None, ge=7, le=365)
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
