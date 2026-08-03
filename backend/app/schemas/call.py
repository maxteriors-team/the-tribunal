"""Call schemas for voice call API endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    """Request to initiate a call.

    ``mode`` decides who actually talks to the contact:

    - ``"ai"`` (default): a voice agent handles the call. ``agent_id`` selects
      it; when omitted the conversation's assigned agent or the workspace
      default voice agent is used. A call with no resolvable agent is rejected
      rather than dialing the contact into silence.
    - ``"user"``: the operator's own phone rings first, then the contact is
      dialed and the two legs are bridged. ``agent_id`` is ignored.
      ``user_phone_number`` picks which allowlisted number to ring.
    """

    to_number: str
    from_phone_number: str
    contact_phone: str | None = None
    agent_id: uuid.UUID | None = Field(
        default=None,
        description="Voice agent for mode='ai'. Ignored when mode='user'.",
    )
    mode: Literal["ai", "user"] = "ai"
    user_phone_number: str | None = Field(
        default=None,
        description=(
            "Number to ring for mode='user'. Must be the caller's profile phone, "
            "the workspace transfer destination, or a workspace phone number. "
            "Defaults to the first of those that is configured."
        ),
    )


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


class LiveCallResponse(BaseModel):
    """A live (in-progress) call available for operator supervision."""

    call_id: str
    workspace_id: str
    direction: str
    agent_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    started_at: str
    duration_seconds: int
    supervisor_count: int
    barged: bool


class LiveCallsResponse(BaseModel):
    """Roster of live calls in a workspace."""

    items: list[LiveCallResponse]


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
