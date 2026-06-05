"""CRM assistant schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.ai.image_input import ImageValidationError, validate_image_data_url

AssistantRole = Literal["user", "assistant", "tool"]


class AssistantChatRequest(BaseModel):
    """Request to send a message to the CRM assistant."""

    message: str
    conversation_id: uuid.UUID | None = None
    image: str | None = Field(
        default=None,
        description=(
            "Optional base64 image data URL (data:image/<type>;base64,...) for the "
            "assistant to reference. JPEG/PNG/WebP/GIF up to 5 MB."
        ),
    )

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str | None) -> str | None:
        """Reject unsupported or oversized images before forwarding to OpenAI."""
        if value is None:
            return None
        try:
            return validate_image_data_url(value)
        except ImageValidationError as exc:
            raise ValueError(str(exc)) from exc


class ActionSummary(BaseModel):
    """Summary of a tool action taken by the assistant."""

    tool_name: str
    success: bool
    summary: str


class AssistantChatResponse(BaseModel):
    """Response from the CRM assistant."""

    response: str
    actions_taken: list[ActionSummary] = []
    conversation_id: str | None = None


class AssistantMessageResponse(BaseModel):
    """A single message in an assistant conversation."""

    id: str
    role: AssistantRole
    content: str
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssistantConversationResponse(BaseModel):
    """Full assistant conversation with messages."""

    id: str
    messages: list[AssistantMessageResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AssistantConversationMetaResponse(BaseModel):
    """Assistant conversation list item."""

    id: str
    title: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class AssistantStreamDeltaEvent(BaseModel):
    """Streaming assistant text delta."""

    type: Literal["delta"]
    text: str


class AssistantStreamReasoningEvent(BaseModel):
    """Streaming assistant reasoning delta."""

    type: Literal["reasoning"]
    text: str


class AssistantStreamToolStartEvent(BaseModel):
    """Assistant tool execution started."""

    type: Literal["tool_start"]
    name: str


class AssistantStreamToolEndEvent(BaseModel):
    """Assistant tool execution completed."""

    type: Literal["tool_end"]
    name: str
    success: bool | None = None


class AssistantStreamRetryEvent(BaseModel):
    """Assistant stream retry notice."""

    type: Literal["retry"]
    reason: str
    attempt: int


class AssistantStreamErrorEvent(BaseModel):
    """Assistant stream error notice."""

    type: Literal["error"]
    message: str


class AssistantStreamDoneEvent(BaseModel):
    """Assistant stream completion event."""

    type: Literal["done"]
    conversation_id: str
    message_id: str | None = None
    actions_taken: list[ActionSummary] = []


AssistantStreamEvent = (
    AssistantStreamDeltaEvent
    | AssistantStreamReasoningEvent
    | AssistantStreamToolStartEvent
    | AssistantStreamToolEndEvent
    | AssistantStreamRetryEvent
    | AssistantStreamErrorEvent
    | AssistantStreamDoneEvent
)
