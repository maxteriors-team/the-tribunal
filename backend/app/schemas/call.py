"""Call schemas for voice call API endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CapturedMessageResponse(BaseModel):
    """A structured "take a message" capture from a voice call."""

    id: uuid.UUID
    caller_name: str | None = None
    callback_number: str | None = None
    reason: str | None = None
    urgency: str
    preferred_callback_time: str | None = None
    message_body: str | None = None
    status: str
    created_at: datetime


class CallCreate(BaseModel):
    """Request to initiate a call."""

    to_number: str
    from_phone_number: str
    contact_phone: str | None = None
    agent_id: uuid.UUID | None = None


class CallResponse(BaseModel):
    """Voice call response."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    direction: str  # inbound/outbound
    channel: str
    status: str  # queued/ringing/answered/completed/failed
    duration_seconds: int | None
    recording_url: str | None
    transcript: str | None  # JSON array of transcript entries
    created_at: datetime
    # Phone numbers from conversation
    from_number: str | None = None
    to_number: str | None = None
    # Contact info
    contact_name: str | None = None
    contact_id: int | None = None
    contact_avatar_url: str | None = None
    # Agent info
    agent_id: uuid.UUID | None = None
    agent_name: str | None = None
    is_ai: bool = False
    booking_outcome: str | None = None
    # Structured messages captured during the call via the take_message tool
    captured_messages: list[CapturedMessageResponse] = []


class PaginatedCalls(BaseModel):
    """Paginated calls response."""

    items: list[CallResponse]
    total: int
    page: int
    page_size: int
    pages: int
    # Aggregate stats across all matching calls (not just current page)
    completed_count: int = 0
    total_duration_seconds: int = 0
