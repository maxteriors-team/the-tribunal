"""Agent schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing_extensions import TypeIs

from app.constants.text_response_timing import (
    TEXT_RESPONSE_DEFAULT_DELAY_MS,
    TEXT_RESPONSE_MAX_DELAY_MS,
    TEXT_RESPONSE_MIN_DELAY_MS,
)
from app.services.ai.text_response_timing import clamp_text_response_delay_ms


def _is_int_convertible(value: object) -> TypeIs[str | bytes | bytearray | int | float]:
    """Return whether ``value`` can reasonably be coerced with ``int``."""
    return isinstance(value, str | bytes | bytearray | int | float)


def _clamp_text_response_delay_value(value: object) -> object:
    """Clamp legacy text response delay values while preserving invalid inputs."""
    if value is None or not _is_int_convertible(value):
        return value
    try:
        return clamp_text_response_delay_ms(int(value))
    except ValueError:
        return value


_VALID_TRANSFER_MODES = {"warm", "cold"}

_VALID_ASSIGNMENT_STRATEGIES = {"single", "round_robin", "skill_based"}


def _normalize_assignment_strategy(value: object) -> object:
    """Coerce the assignment strategy, defaulting unknowns to 'single'."""
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    return normalized if normalized in _VALID_ASSIGNMENT_STRATEGIES else "single"


def _normalize_transfer_mode(value: object) -> object:
    """Coerce the transfer mode to 'warm'/'cold', defaulting unknowns to 'warm'."""
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    return normalized if normalized in _VALID_TRANSFER_MODES else "warm"


class AgentCreate(BaseModel):
    """Schema for creating an agent."""

    name: str
    description: str | None = None
    channel_mode: str = "both"  # voice, text, both
    voice_provider: str = "openai"  # openai, elevenlabs
    voice_id: str = "alloy"
    language: str = "en-US"
    system_prompt: str
    temperature: float = 0.7
    text_response_delay_ms: int = Field(
        default=TEXT_RESPONSE_DEFAULT_DELAY_MS,
        ge=TEXT_RESPONSE_MIN_DELAY_MS,
        le=TEXT_RESPONSE_MAX_DELAY_MS,
    )
    text_max_context_messages: int = 20
    calcom_event_type_id: int | None = None
    assignment_strategy: str = "single"
    enabled_tools: list[str] = []
    tool_settings: dict[str, list[str]] = {}
    # IVR navigation settings
    enable_ivr_navigation: bool = False
    ivr_navigation_goal: str | None = None
    ivr_loop_threshold: int = 2
    # IVR timing configuration (milliseconds)
    ivr_silence_duration_ms: int = 3000
    ivr_post_dtmf_cooldown_ms: int = 3000
    ivr_menu_buffer_silence_ms: int = 2000
    # Call recording
    enable_recording: bool = True
    # Live human transfer / handoff
    transfer_destination_number: str | None = None
    transfer_mode: str = "warm"
    transfer_briefing_template: str | None = None
    # Appointment reminder settings
    reminder_enabled: bool = True
    reminder_minutes_before: int = 30
    reminder_offsets: list[int] = [1440, 120, 30]
    reminder_template: str | None = None
    # Experiment auto-evaluation
    auto_evaluate: bool = False
    # Greeting
    initial_greeting: str | None = None
    # No-show SMS template
    noshow_template: str | None = None
    # Post-meeting SMS
    post_meeting_sms_enabled: bool = False
    post_meeting_template: str | None = None
    # Value-reinforcement follow-up
    value_reinforcement_enabled: bool = False
    value_reinforcement_offset_minutes: int = 120
    value_reinforcement_template: str | None = None
    # Never-booked re-engagement
    never_booked_reengagement_enabled: bool = False
    never_booked_delay_days: int = 7
    never_booked_template: str | None = None
    never_booked_max_attempts: int = 2
    # No-show multi-day re-engagement
    noshow_reengagement_enabled: bool = True
    noshow_day3_template: str | None = None
    noshow_day7_template: str | None = None

    @field_validator("text_response_delay_ms", mode="before")
    @classmethod
    def clamp_text_response_delay(cls, value: object) -> object:
        """Accept legacy fast delays and clamp them to the supported range."""
        return _clamp_text_response_delay_value(value)

    @field_validator("transfer_mode", mode="before")
    @classmethod
    def validate_transfer_mode(cls, value: object) -> object:
        """Normalize the transfer mode to one of the supported values."""
        return _normalize_transfer_mode(value)

    @field_validator("assignment_strategy", mode="before")
    @classmethod
    def validate_assignment_strategy(cls, value: object) -> object:
        """Normalize the booking assignment strategy to a supported value."""
        return _normalize_assignment_strategy(value)


class AgentUpdate(BaseModel):
    """Schema for updating an agent."""

    name: str | None = None
    description: str | None = None
    channel_mode: str | None = None
    voice_provider: str | None = None
    voice_id: str | None = None
    language: str | None = None
    system_prompt: str | None = None
    temperature: float | None = None
    text_response_delay_ms: int | None = Field(
        default=None,
        ge=TEXT_RESPONSE_MIN_DELAY_MS,
        le=TEXT_RESPONSE_MAX_DELAY_MS,
    )
    text_max_context_messages: int | None = None
    calcom_event_type_id: int | None = None
    assignment_strategy: str | None = None
    is_active: bool | None = None
    enabled_tools: list[str] | None = None
    tool_settings: dict[str, list[str]] | None = None
    # IVR navigation settings
    enable_ivr_navigation: bool | None = None
    ivr_navigation_goal: str | None = None
    ivr_loop_threshold: int | None = None
    # IVR timing configuration (milliseconds)
    ivr_silence_duration_ms: int | None = None
    ivr_post_dtmf_cooldown_ms: int | None = None
    ivr_menu_buffer_silence_ms: int | None = None
    # Call recording
    enable_recording: bool | None = None
    # Live human transfer / handoff
    transfer_destination_number: str | None = None
    transfer_mode: str | None = None
    transfer_briefing_template: str | None = None
    # Appointment reminder settings
    reminder_enabled: bool | None = None
    reminder_minutes_before: int | None = None
    reminder_offsets: list[int] | None = None
    reminder_template: str | None = None
    # Experiment auto-evaluation
    auto_evaluate: bool | None = None
    # Greeting
    initial_greeting: str | None = None
    # No-show SMS template
    noshow_template: str | None = None
    # Post-meeting SMS
    post_meeting_sms_enabled: bool | None = None
    post_meeting_template: str | None = None
    # Value-reinforcement follow-up
    value_reinforcement_enabled: bool | None = None
    value_reinforcement_offset_minutes: int | None = None
    value_reinforcement_template: str | None = None
    # Never-booked re-engagement
    never_booked_reengagement_enabled: bool | None = None
    never_booked_delay_days: int | None = None
    never_booked_template: str | None = None
    never_booked_max_attempts: int | None = None
    # No-show multi-day re-engagement
    noshow_reengagement_enabled: bool | None = None
    noshow_day3_template: str | None = None
    noshow_day7_template: str | None = None

    @field_validator("text_response_delay_ms", mode="before")
    @classmethod
    def clamp_text_response_delay(cls, value: object) -> object:
        """Accept legacy fast delays and clamp them to the supported range."""
        return _clamp_text_response_delay_value(value)

    @field_validator("transfer_mode", mode="before")
    @classmethod
    def validate_transfer_mode(cls, value: object) -> object:
        """Normalize the transfer mode, leaving None untouched for partial updates."""
        if value is None:
            return None
        return _normalize_transfer_mode(value)

    @field_validator("assignment_strategy", mode="before")
    @classmethod
    def validate_assignment_strategy(cls, value: object) -> object:
        """Normalize the assignment strategy, leaving None untouched for partial updates."""
        if value is None:
            return None
        return _normalize_assignment_strategy(value)


class AgentResponse(BaseModel):
    """Agent response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    channel_mode: str
    voice_provider: str
    voice_id: str
    language: str
    system_prompt: str
    temperature: float
    text_response_delay_ms: int
    text_max_context_messages: int
    calcom_event_type_id: int | None
    assignment_strategy: str = "single"
    enabled_tools: list[str]
    tool_settings: dict[str, list[str]]
    is_active: bool
    # IVR navigation settings
    enable_ivr_navigation: bool
    ivr_navigation_goal: str | None
    ivr_loop_threshold: int
    # IVR timing configuration (milliseconds)
    ivr_silence_duration_ms: int
    ivr_post_dtmf_cooldown_ms: int
    ivr_menu_buffer_silence_ms: int
    # Call recording
    enable_recording: bool
    # Live human transfer / handoff
    transfer_destination_number: str | None = None
    transfer_mode: str = "warm"
    transfer_briefing_template: str | None = None
    # Appointment reminder settings
    reminder_enabled: bool
    reminder_minutes_before: int
    reminder_offsets: list[int]
    reminder_template: str | None
    # Experiment auto-evaluation
    auto_evaluate: bool
    # Greeting
    initial_greeting: str | None
    # No-show SMS template
    noshow_template: str | None = None
    # Post-meeting SMS
    post_meeting_sms_enabled: bool = False
    post_meeting_template: str | None = None
    # Value-reinforcement follow-up
    value_reinforcement_enabled: bool = False
    value_reinforcement_offset_minutes: int = 120
    value_reinforcement_template: str | None = None
    # Never-booked re-engagement
    never_booked_reengagement_enabled: bool = False
    never_booked_delay_days: int = 7
    never_booked_template: str | None = None
    never_booked_max_attempts: int = 2
    # No-show multi-day re-engagement
    noshow_reengagement_enabled: bool = True
    noshow_day3_template: str | None = None
    noshow_day7_template: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_validator("text_response_delay_ms", mode="before")
    @classmethod
    def clamp_text_response_delay(cls, value: object) -> object:
        """Return legacy fast delays as the effective supported minimum."""
        return _clamp_text_response_delay_value(value)

    model_config = ConfigDict(from_attributes=True)


class PaginatedAgents(BaseModel):
    """Paginated agents response."""

    items: list[AgentResponse]
    total: int
    page: int
    page_size: int
    pages: int


# Embed settings schemas
class EmbedSettings(BaseModel):
    """Embed widget settings."""

    button_text: str = "Talk to AI"
    theme: str = "auto"  # auto, light, dark
    position: str = "bottom-right"  # bottom-right, bottom-left, top-right, top-left
    primary_color: str = "#6366f1"
    mode: str = "voice"  # voice, chat, both
    display: str = "floating"  # floating, inline, fullpage


class EmbedSettingsResponse(BaseModel):
    """Response for embed settings."""

    public_id: str | None
    embed_enabled: bool
    allowed_domains: list[str]
    embed_settings: EmbedSettings
    embed_code: str | None


class EmbedSettingsUpdate(BaseModel):
    """Request to update embed settings."""

    embed_enabled: bool | None = None
    allowed_domains: list[str] | None = None
    embed_settings: dict[str, Any] | None = None
