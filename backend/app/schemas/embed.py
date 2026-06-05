"""Public embed API schemas."""

from pydantic import BaseModel, Field, field_validator

from app.services.ai.image_input import ImageValidationError, validate_image_data_url


class EmbedConfigResponse(BaseModel):
    """Public configuration for embed widget."""

    public_id: str
    name: str
    greeting_message: str | None
    button_text: str
    theme: str
    position: str
    primary_color: str
    language: str
    voice: str
    channel_mode: str


class TokenRequest(BaseModel):
    """Request for ephemeral token."""

    mode: str = "voice"


class TokenResponse(BaseModel):
    """Ephemeral token response for WebRTC connection."""

    client_secret: dict[str, str]
    agent: dict[str, str | None]
    model: str
    tools: list[dict[str, object]]


class ChatRequest(BaseModel):
    """Chat message request."""

    message: str
    conversation_history: list[dict[str, str]] = Field(
        default_factory=list,
        json_schema_extra={"default": []},
    )
    image: str | None = Field(
        default=None,
        description=(
            "Optional base64 image data URL (data:image/<type>;base64,...) for the "
            "AI to reference when answering. JPEG/PNG/WebP/GIF up to 5 MB."
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


class ChatResponse(BaseModel):
    """Chat message response."""

    response: str
    tool_calls: list[dict[str, object]] = Field(
        default_factory=list,
        json_schema_extra={"default": []},
    )


class ToolCallRequest(BaseModel):
    """Tool call execution request."""

    tool_name: str
    arguments: dict[str, object]


class ToolCallResponse(BaseModel):
    """Tool call execution response."""

    success: bool
    message: str
    action: str | None = None
    result: dict[str, object] | None = None


class TranscriptRequest(BaseModel):
    """Transcript save request."""

    session_id: str
    transcript: str
    duration_seconds: int


class TranscriptResponse(BaseModel):
    """Transcript save response."""

    status: str


class EmbedPhoneRequest(BaseModel):
    """Request for embed call/text endpoints."""

    phone_number: str
    caller_name: str | None = None
    notes: str | None = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        """Validate and normalize a US phone number to E.164 format."""
        digits = "".join(character for character in value if character.isdigit())
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        msg = "Phone number must be a valid US number (10 digits)"
        raise ValueError(msg)


class EmbedActionResponse(BaseModel):
    """Generic success response for public embed side-effect actions."""

    success: bool
    message: str
