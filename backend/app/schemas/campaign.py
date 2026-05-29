"""Campaign schemas."""

import uuid
from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator


class CampaignCreate(BaseModel):
    """Schema for creating a campaign."""

    name: str
    agent_id: uuid.UUID | None = None
    offer_id: uuid.UUID | None = None
    from_phone_number: str
    initial_message: str
    ai_enabled: bool = True
    qualification_criteria: str | None = None
    scheduled_start: datetime | None = None
    sending_hours_start: str | None = None  # "09:00"
    sending_hours_end: str | None = None  # "17:00"
    sending_days: list[int] | None = None  # [0,1,2,3,4] = Mon-Fri
    timezone: str = "America/New_York"
    messages_per_minute: int = 10
    follow_up_enabled: bool = False
    follow_up_delay_hours: int = 24
    follow_up_message: str | None = None
    max_follow_ups: int = 2
    guarantee_target: int | None = None
    guarantee_window_days: int | None = None


class CampaignUpdate(BaseModel):
    """Schema for updating a campaign."""

    name: str | None = None
    agent_id: uuid.UUID | None = None
    offer_id: uuid.UUID | None = None
    from_phone_number: str | None = None
    initial_message: str | None = None
    ai_enabled: bool | None = None
    qualification_criteria: str | None = None
    scheduled_start: datetime | None = None
    sending_hours_start: str | None = None
    sending_hours_end: str | None = None
    sending_days: list[int] | None = None
    timezone: str | None = None
    messages_per_minute: int | None = None
    follow_up_enabled: bool | None = None
    follow_up_delay_hours: int | None = None
    follow_up_message: str | None = None
    max_follow_ups: int | None = None
    guarantee_target: int | None = None
    guarantee_window_days: int | None = None


class CampaignResponse(BaseModel):
    """Campaign response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    campaign_type: str
    agent_id: uuid.UUID | None
    offer_id: uuid.UUID | None
    name: str
    status: str
    from_phone_number: str
    initial_message: str | None
    ai_enabled: bool
    qualification_criteria: str | None
    scheduled_start: datetime | None
    sending_hours_start: str | None
    sending_hours_end: str | None
    sending_days: list[int] | None
    timezone: str
    messages_per_minute: int
    follow_up_enabled: bool
    follow_up_delay_hours: int
    follow_up_message: str | None
    max_follow_ups: int
    total_contacts: int
    messages_sent: int
    messages_delivered: int
    messages_failed: int
    replies_received: int
    contacts_qualified: int
    contacts_opted_out: int
    appointments_booked: int
    appointments_completed: int = 0
    guarantee_target: int | None = None
    guarantee_window_days: int | None = None
    guarantee_status: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("sending_hours_start", "sending_hours_end", mode="before")
    @classmethod
    def validate_sending_hours(cls, v: time | str | None) -> str | None:
        """Convert time objects to string format during validation."""
        if v is None:
            return None
        if isinstance(v, time):
            return v.strftime("%H:%M")
        return v

    @field_serializer("sending_hours_start", "sending_hours_end")
    def serialize_time(self, v: time | str | None) -> str | None:
        """Serialize time to string format."""
        if v is None:
            return None
        if isinstance(v, time):
            return v.strftime("%H:%M")
        return v


class CampaignContactAdd(BaseModel):
    """Schema for adding contacts to a campaign."""

    contact_ids: list[int]


class CampaignContactResponse(BaseModel):
    """Campaign contact response schema."""

    id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: int
    conversation_id: uuid.UUID | None
    status: str
    messages_sent: int
    is_qualified: bool
    opted_out: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedCampaigns(BaseModel):
    """Paginated campaigns response."""

    items: list[CampaignResponse]
    total: int
    page: int
    page_size: int
    pages: int


class CampaignAnalytics(BaseModel):
    """Campaign analytics response."""

    total_contacts: int
    messages_sent: int
    messages_delivered: int
    messages_failed: int
    replies_received: int
    contacts_qualified: int
    contacts_opted_out: int
    reply_rate: float = 0.0
    delivery_rate: float = 0.0
    qualification_rate: float = 0.0


# Voice Campaign Schemas


class VoiceCampaignCreate(BaseModel):
    """Schema for creating a voice campaign with SMS fallback."""

    name: str
    description: str | None = None
    from_phone_number: str

    # Voice settings
    voice_agent_id: uuid.UUID
    voice_connection_id: str | None = None
    enable_machine_detection: bool = True
    max_call_duration_seconds: int = 120

    # SMS fallback settings
    sms_fallback_enabled: bool = True
    sms_fallback_template: str | None = None
    sms_fallback_use_ai: bool = False
    sms_fallback_agent_id: uuid.UUID | None = None

    # AI settings (for responses to SMS replies)
    ai_enabled: bool = True
    qualification_criteria: str | None = None

    # Scheduling
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    sending_hours_start: str | None = None  # "09:00"
    sending_hours_end: str | None = None  # "17:00"
    sending_days: list[int] | None = None  # [0,1,2,3,4] = Mon-Fri
    timezone: str = "America/New_York"
    calls_per_minute: int = 5
    guarantee_target: int | None = None
    guarantee_window_days: int | None = None


class VoiceCampaignUpdate(BaseModel):
    """Schema for updating a voice campaign."""

    name: str | None = None
    description: str | None = None

    # Voice settings
    voice_agent_id: uuid.UUID | None = None
    voice_connection_id: str | None = None
    enable_machine_detection: bool | None = None
    max_call_duration_seconds: int | None = None

    # SMS fallback settings
    sms_fallback_enabled: bool | None = None
    sms_fallback_template: str | None = None
    sms_fallback_use_ai: bool | None = None
    sms_fallback_agent_id: uuid.UUID | None = None

    # AI settings
    ai_enabled: bool | None = None
    qualification_criteria: str | None = None

    # Scheduling
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    sending_hours_start: str | None = None
    sending_hours_end: str | None = None
    sending_days: list[int] | None = None
    timezone: str | None = None
    calls_per_minute: int | None = None
    guarantee_target: int | None = None
    guarantee_window_days: int | None = None


class VoiceCampaignResponse(BaseModel):
    """Voice campaign response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    campaign_type: str
    name: str
    description: str | None
    status: str
    from_phone_number: str

    # Voice settings
    voice_agent_id: uuid.UUID | None
    voice_connection_id: str | None
    enable_machine_detection: bool
    max_call_duration_seconds: int
    calls_per_minute: int

    # SMS fallback settings
    sms_fallback_enabled: bool
    sms_fallback_template: str | None
    sms_fallback_use_ai: bool
    sms_fallback_agent_id: uuid.UUID | None

    # AI settings
    ai_enabled: bool
    agent_id: uuid.UUID | None
    qualification_criteria: str | None

    # Scheduling
    scheduled_start: datetime | None
    scheduled_end: datetime | None
    sending_hours_start: str | None
    sending_hours_end: str | None
    sending_days: list[int] | None
    timezone: str

    # Statistics
    total_contacts: int
    calls_attempted: int
    calls_answered: int
    calls_no_answer: int
    calls_busy: int
    calls_voicemail: int
    sms_fallbacks_sent: int
    messages_sent: int
    replies_received: int
    contacts_qualified: int
    contacts_opted_out: int
    appointments_booked: int
    appointments_completed: int = 0
    guarantee_target: int | None = None
    guarantee_window_days: int | None = None
    guarantee_status: str | None = None

    # Timestamps
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("sending_hours_start", "sending_hours_end", mode="before")
    @classmethod
    def validate_sending_hours(cls, v: time | str | None) -> str | None:
        """Convert time objects to string format during validation."""
        if v is None:
            return None
        if isinstance(v, time):
            return v.strftime("%H:%M")
        return v

    @field_serializer("sending_hours_start", "sending_hours_end")
    def serialize_time(self, v: time | str | None) -> str | None:
        """Serialize time to string format."""
        if v is None:
            return None
        if isinstance(v, time):
            return v.strftime("%H:%M")
        return v


class GuaranteeProgressResponse(BaseModel):
    """Guarantee progress response."""

    campaign_id: str
    guarantee_target: int | None
    appointments_booked: int
    appointments_completed: int
    guarantee_status: str | None
    guarantee_window_days: int | None
    days_remaining: int | None
    deadline: str | None
    started_at: str | None


class PaginatedVoiceCampaigns(BaseModel):
    """Paginated voice campaigns response."""

    items: list[VoiceCampaignResponse]
    total: int
    page: int
    page_size: int
    pages: int


class VoiceCampaignContactResponse(BaseModel):
    """Voice campaign contact response schema."""

    id: uuid.UUID
    campaign_id: uuid.UUID
    contact_id: int
    conversation_id: uuid.UUID | None
    status: str

    # Call tracking
    call_attempts: int
    last_call_at: datetime | None
    last_call_status: str | None
    call_duration_seconds: int | None

    # SMS fallback
    sms_fallback_sent: bool
    sms_fallback_sent_at: datetime | None

    # Standard fields
    messages_sent: int
    is_qualified: bool
    opted_out: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VoiceCampaignAnalytics(BaseModel):
    """Voice campaign analytics response."""

    total_contacts: int
    calls_attempted: int
    calls_answered: int
    calls_no_answer: int
    calls_busy: int
    calls_voicemail: int
    sms_fallbacks_sent: int
    messages_sent: int
    replies_received: int
    contacts_qualified: int
    contacts_opted_out: int
    appointments_booked: int

    # Rates
    answer_rate: float
    fallback_rate: float
    qualification_rate: float
