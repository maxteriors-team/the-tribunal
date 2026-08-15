"""Appointment schemas for API validation."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AppointmentBase(BaseModel):
    """Base appointment schema."""

    duration_minutes: int = Field(default=30, ge=15, le=480)
    service_type: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class AppointmentCreate(AppointmentBase):
    """Schema for creating an appointment and tagging a calendar user."""

    contact_id: int
    agent_id: str | None = None
    scheduled_at: datetime
    bookable_staff_id: uuid.UUID | None = None


class AppointmentUpdate(BaseModel):
    """Schema for updating an appointment."""

    status: str | None = Field(default=None, pattern="^(scheduled|completed|cancelled|no_show)$")
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    service_type: str | None = None
    notes: str | None = None
    business_location_id: uuid.UUID | None = None
    bookable_staff_id: uuid.UUID | None = None


class ContactSummary(BaseModel):
    """Minimal contact info for appointments."""

    id: int
    first_name: str
    last_name: str | None
    email: str | None
    phone_number: str

    model_config = ConfigDict(from_attributes=True)


class AppointmentResponse(AppointmentBase):
    """Schema for appointment response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: uuid.UUID
    contact_id: int
    contact: ContactSummary | None = None
    agent_id: uuid.UUID | None
    message_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    bookable_staff_id: uuid.UUID | None = None
    business_location_id: uuid.UUID | None = None
    scheduled_at: datetime
    status: str
    google_calendar_event_id: str | None
    google_calendar_event_url: str | None
    meeting_url: str | None = None
    sync_status: str
    last_synced_at: datetime | None
    sync_error: str | None = None
    reminder_sent_at: datetime | None = None
    reminders_sent: list[int] = []
    created_at: datetime
    updated_at: datetime


class PaginatedAppointments(BaseModel):
    """Paginated appointments response."""

    items: list[AppointmentResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ---------------------------------------------------------------------------
# Stats response schemas
# ---------------------------------------------------------------------------


class AppointmentOverallStats(BaseModel):
    """Overall appointment statistics for the workspace."""

    total: int
    scheduled: int
    completed: int
    no_show: int
    cancelled: int
    show_up_rate: float


class AppointmentAgentStat(BaseModel):
    """Per-agent appointment statistics."""

    agent_id: str
    agent_name: str
    total: int
    completed: int
    no_show: int
    show_up_rate: float


class AppointmentCampaignStat(BaseModel):
    """Per-campaign appointment statistics."""

    campaign_id: str
    campaign_name: str
    total: int
    completed: int
    no_show: int
    show_up_rate: float


class AppointmentStatsResponse(BaseModel):
    """Full show-up rate analytics response."""

    overall: AppointmentOverallStats
    by_agent: list[AppointmentAgentStat]
    by_campaign: list[AppointmentCampaignStat]
