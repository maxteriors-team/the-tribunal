"""Conversation and message schemas."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageCreate(BaseModel):
    """Schema for sending a message."""

    body: str
    client_request_id: uuid.UUID | None = None


class MessageResponse(BaseModel):
    """Message response schema."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    direction: str
    channel: str
    body: str
    status: str
    is_ai: bool
    agent_id: uuid.UUID | None
    sender_user_id: int | None = None
    sender_display_name: str | None = None
    source_provider: str | None = None
    external_url: str | None = None
    is_voicemail: bool = False
    booking_outcome: str | None = None
    sent_at: datetime | None
    created_at: datetime

    @field_validator("is_voicemail", mode="before")
    @classmethod
    def default_missing_voicemail_indicator(cls, value: object) -> bool:
        return bool(value)

    model_config = ConfigDict(from_attributes=True)


class ConversationResponse(BaseModel):
    """Conversation response schema."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int | None
    # Display name of the linked contact, resolved by the service layer. ``None``
    # when the thread has no contact yet, so clients fall back to the phone.
    contact_name: str | None = None
    workspace_phone: str
    contact_phone: str
    status: str
    channel: str
    source_provider: str | None = None
    assigned_agent_id: uuid.UUID | None
    ai_enabled: bool
    ai_paused: bool
    unread_count: int
    last_message_preview: str | None
    last_message_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationWithMessages(ConversationResponse):
    """Conversation with messages."""

    messages: list[MessageResponse]


class PaginatedConversations(BaseModel):
    """Paginated conversations response."""

    items: list[ConversationResponse]
    total: int
    page: int
    page_size: int
    pages: int


class PaginatedMessages(BaseModel):
    """One page of a single thread's messages, in reading order."""

    items: list[MessageResponse]
    total: int
    page: int
    page_size: int
    pages: int


class UnreadSummary(BaseModel):
    """Workspace-wide unread rollup backing the header chat badge.

    ``unread_messages`` is the sum of every thread's ``unread_count`` (what the
    badge shows); ``unread_conversations`` is how many threads are waiting.
    """

    unread_conversations: int
    unread_messages: int


class MarkAllReadResponse(BaseModel):
    """Result of clearing every unread thread in a workspace."""

    conversations_marked: int


class AIToggle(BaseModel):
    """AI toggle request."""

    enabled: bool


class AgentAssign(BaseModel):
    """Agent assignment request."""

    agent_id: uuid.UUID | None


class FollowupSettingsUpdate(BaseModel):
    """Schema for updating follow-up settings."""

    enabled: bool | None = None
    delay_hours: int | None = Field(None, ge=1, le=168)  # 1 hour to 1 week
    max_count: int | None = Field(None, ge=1, le=10)


class FollowupSettingsResponse(BaseModel):
    """Follow-up settings and status response."""

    enabled: bool
    delay_hours: int
    max_count: int
    count_sent: int
    next_followup_at: datetime | None
    last_followup_at: datetime | None


class FollowupGenerateRequest(BaseModel):
    """Request for generating a follow-up message."""

    custom_instructions: str | None = None


class FollowupGenerateResponse(BaseModel):
    """Response with generated follow-up message."""

    message: str
    conversation_id: str


class FollowupSendRequest(BaseModel):
    """Request for sending a follow-up message."""

    message: str | None = None  # If not provided, will generate one
    custom_instructions: str | None = None


class FollowupSendResponse(BaseModel):
    """Response after sending a follow-up."""

    success: bool
    message_id: str | None
    message_body: str


class TeachAIRequest(BaseModel):
    """Human-approved correction to one AI-generated SMS reply."""

    source_message_id: uuid.UUID
    ideal_response: str = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("ideal_response")
    @classmethod
    def validate_ideal_response(cls, value: str) -> str:
        """Reject whitespace-only corrections before they reach persistence."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("ideal_response must contain visible text")
        return stripped

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        """Store an omitted note rather than encrypted empty whitespace."""
        if value is None:
            return None
        return value.strip() or None


class TeachAIResponse(BaseModel):
    """Saved correction and its agent target; never returned across tenants."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    agent_id: uuid.UUID
    conversation_id: uuid.UUID | None
    source_message_id: uuid.UUID | None
    ideal_response: str
    note: str | None
    is_active: bool
    agent_name: str
    created_at: datetime
    updated_at: datetime
