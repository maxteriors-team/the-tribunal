"""Public embed API endpoints for embeddable agent widgets.

These endpoints are unauthenticated but require domain validation
and are rate-limited for security.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import hash_phone
from app.core.origin_validation import validate_origin
from app.core.rate_limit_helpers import raise_rate_limited
from app.core.utils import get_client_ip
from app.db.session import get_db
from app.models.agent import Agent
from app.models.demo_request import DemoRequest
from app.services.rate_limiting.embed_limiter import (
    enforce_chat_rate_limits,
    enforce_token_rate_limits,
)
from app.services.telephony.telnyx import TelnyxSMSService
from app.services.telephony.telnyx_voice import TelnyxVoiceService

# Latest OpenAI audio models (for standalone TTS/transcription, not Realtime API):
# - TTS: gpt-4o-mini-tts-2025-12-15 (lower word error rates)
# - Transcription: gpt-4o-mini-transcribe-2025-12-15 (~90% fewer hallucinations)

# Database dependency type alias
DB = Annotated[AsyncSession, Depends(get_db)]

logger = structlog.get_logger()

router = APIRouter()


# Schemas
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

    mode: str = "voice"  # voice or chat


class TokenResponse(BaseModel):
    """Ephemeral token response for WebRTC connection."""

    client_secret: dict[str, str]
    agent: dict[str, str | None]
    model: str
    tools: list[dict[str, object]]


class ChatRequest(BaseModel):
    """Chat message request."""

    message: str
    conversation_history: list[dict[str, str]] = []


class ChatResponse(BaseModel):
    """Chat message response."""

    response: str
    tool_calls: list[dict[str, object]] = []


class ToolCallRequest(BaseModel):
    """Tool call execution request."""

    tool_name: str
    arguments: dict[str, object]


class TranscriptRequest(BaseModel):
    """Transcript save request."""

    session_id: str
    transcript: str
    duration_seconds: int


class EmbedPhoneRequest(BaseModel):
    """Request for embed call/text endpoints."""

    phone_number: str
    caller_name: str | None = None
    notes: str | None = None

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        """Validate and normalize phone number to E.164 format."""
        digits = "".join(c for c in v if c.isdigit())
        if len(digits) == 10:
            return f"+1{digits}"
        elif len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        else:
            raise ValueError("Phone number must be a valid US number (10 digits)")


def _seconds_until_window_clears(
    oldest_created_at: datetime | None,
    window_seconds: int,
    now: datetime,
) -> int:
    """Seconds until the rolling window has room for another request.

    Mirrors the helper in ``demo.py``: once the oldest in-window record ages
    out, the caller is back under cap. Falls back to ``window_seconds`` when
    no rows are visible (paranoia path).
    """
    if oldest_created_at is None:
        return window_seconds
    if oldest_created_at.tzinfo is None:
        oldest_created_at = oldest_created_at.replace(tzinfo=UTC)
    expires_at = oldest_created_at + timedelta(seconds=window_seconds)
    remaining = int((expires_at - now).total_seconds())
    return max(1, remaining)


async def _check_embed_rate_limits(db: AsyncSession, client_ip: str, phone_number: str) -> None:
    """Check rate limits for embed call/text requests."""
    # Bypass rate limits for dev/test phone numbers
    if phone_number in settings.demo_rate_limit_bypass_phones:
        return

    now = datetime.now(UTC)
    hour_ago = now - timedelta(hours=1)
    day_ago = now - timedelta(days=1)
    hour_seconds = 3600
    day_seconds = 86400

    # Check IP rate limit
    ip_count_result = await db.execute(
        select(func.count(), func.min(DemoRequest.created_at)).where(
            DemoRequest.client_ip == client_ip,
            DemoRequest.created_at >= hour_ago,
        )
    )
    ip_row = ip_count_result.one()
    ip_count = ip_row[0] or 0
    ip_oldest = ip_row[1]

    if ip_count >= settings.demo_ip_rate_limit:
        retry_after = _seconds_until_window_clears(ip_oldest, hour_seconds, now)
        raise_rate_limited(
            retry_after,
            detail="Rate limit exceeded. Please try again later.",
        )

    # Check phone rate limit
    phone_count_result = await db.execute(
        select(func.count(), func.min(DemoRequest.created_at)).where(
            DemoRequest.phone_number == phone_number,
            DemoRequest.created_at >= day_ago,
        )
    )
    phone_row = phone_count_result.one()
    phone_count = phone_row[0] or 0
    phone_oldest = phone_row[1]

    if phone_count >= settings.demo_phone_rate_limit:
        retry_after = _seconds_until_window_clears(phone_oldest, day_seconds, now)
        raise_rate_limited(
            retry_after,
            detail=("This phone number has reached its daily limit. " "Please try again tomorrow."),
        )


async def get_agent_by_public_id(db: AsyncSession, public_id: str) -> Agent:
    """Get an agent by public ID with validation."""
    result = await db.execute(
        select(Agent).where(
            Agent.public_id == public_id,
            Agent.embed_enabled.is_(True),
            Agent.is_active.is_(True),
        )
    )
    agent: Agent | None = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found or embedding not enabled",
        )

    return agent


@router.get("/{public_id}/config", response_model=EmbedConfigResponse)
async def get_embed_config(
    public_id: str,
    request: Request,
    db: DB,
) -> EmbedConfigResponse:
    """Get public configuration for the embed widget."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    # Get embed settings with defaults
    embed_settings = agent.embed_settings or {}

    return EmbedConfigResponse(
        public_id=agent.public_id or "",
        name=agent.name,
        greeting_message=agent.initial_greeting,
        button_text=embed_settings.get("button_text", "Talk to AI"),
        theme=embed_settings.get("theme", "auto"),
        position=embed_settings.get("position", "bottom-right"),
        primary_color=embed_settings.get("primary_color", "#6366f1"),
        language=agent.language,
        voice=agent.voice_id,
        channel_mode=agent.channel_mode,
    )


@router.post("/{public_id}/token", response_model=TokenResponse)
async def get_ephemeral_token(
    public_id: str,
    request: Request,
    db: DB,
    body: TokenRequest | None = None,
) -> TokenResponse:
    """Get an ephemeral token for OpenAI Realtime WebRTC connection."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    # Rate limit before doing any expensive work (OpenAI client_secrets mint)
    client_ip = get_client_ip(request, settings.trusted_proxies)
    await enforce_token_rate_limits(client_ip=client_ip, public_id=public_id)

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice service not configured",
        )

    # Map voice to OpenAI Realtime-compatible voices
    openai_realtime_voices = {
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    }
    voice = agent.voice_id if agent.voice_id in openai_realtime_voices else "ash"

    # Create ephemeral client secret from OpenAI (GA Realtime API)
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/realtime/client_secrets",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-realtime-preview",
                "voice": voice,
            },
            timeout=30.0,
        )

        if response.status_code != 200:
            logger.error(
                "openai_session_error",
                status=response.status_code,
                body=response.text,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to create voice session",
            )

        session_data = response.json()

    # Build tools list from agent's enabled tools
    tools: list[dict[str, object]] = []

    # Add end_call tool by default for embed sessions
    tools.append(
        {
            "type": "function",
            "name": "end_call",
            "description": (
                "End the current call. Use this when the user says goodbye, "
                "thanks you and indicates they're done, or explicitly asks to end the call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "The reason for ending the call",
                    }
                },
                "required": ["reason"],
            },
        }
    )

    return TokenResponse(
        client_secret={"value": session_data.get("client_secret", {}).get("value", "")},
        agent={
            "name": agent.name,
            "voice": agent.voice_id,
            "instructions": agent.system_prompt,
            "language": agent.language,
            "initial_greeting": agent.initial_greeting,
        },
        model="gpt-realtime",
        tools=tools,
    )


@router.post("/{public_id}/chat", response_model=ChatResponse)
async def send_chat_message(
    public_id: str,
    body: ChatRequest,
    request: Request,
    db: DB,
) -> ChatResponse:
    """Send a chat message and get AI response."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)
    await enforce_chat_rate_limits(client_ip=client_ip, public_id=public_id)

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chat service not configured",
        )

    # Build messages for OpenAI
    messages: list[dict[str, str]] = [{"role": "system", "content": agent.system_prompt}]

    # Add conversation history
    for msg in body.conversation_history[-agent.text_max_context_messages :]:
        messages.append(msg)

    # Add current message
    messages.append({"role": "user", "content": body.message})

    # Call OpenAI Chat API
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-5.4-nano",
                "messages": messages,
                "temperature": agent.temperature,
                "max_completion_tokens": agent.max_tokens,
            },
            timeout=60.0,
        )

        if response.status_code != 200:
            logger.error(
                "openai_chat_error",
                status=response.status_code,
                body=response.text,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to get AI response",
            )

        data = response.json()

    # Extract response
    choices = data.get("choices", [])
    first_choice = choices[0] if choices else {}
    ai_response = first_choice.get("message", {}).get("content", "")

    return ChatResponse(response=ai_response, tool_calls=[])


@router.post("/{public_id}/tool-call")
async def execute_tool_call(
    public_id: str,
    body: ToolCallRequest,
    request: Request,
    db: DB,
) -> dict[str, object]:
    """Execute a tool call from the AI."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)
    await enforce_chat_rate_limits(client_ip=client_ip, public_id=public_id)

    # Handle built-in tools
    if body.tool_name == "end_call":
        return {
            "success": True,
            "action": "end_call",
            "message": "Call ended successfully",
        }

    # For other tools, return a generic response
    # In a full implementation, this would dispatch to the appropriate tool handler
    return {
        "success": True,
        "message": f"Tool {body.tool_name} executed",
        "result": body.arguments,
    }


@router.post("/{public_id}/transcript")
async def save_transcript(
    public_id: str,
    body: TranscriptRequest,
    request: Request,
    db: DB,
) -> dict[str, str]:
    """Save a conversation transcript."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)
    await enforce_chat_rate_limits(client_ip=client_ip, public_id=public_id)

    # Log transcript for analytics (in a full implementation, save to database)
    logger.info(
        "embed_transcript_saved",
        public_id=public_id,
        session_id=body.session_id,
        duration_seconds=body.duration_seconds,
        transcript_length=len(body.transcript),
    )

    return {"status": "saved"}


@router.post("/{public_id}/call")
async def trigger_embed_call(
    public_id: str,
    body: EmbedPhoneRequest,
    request: Request,
    db: DB,
) -> dict[str, bool | str]:
    """Trigger an AI call via the embed widget."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice service not available",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_embed_rate_limits(db, client_ip, body.phone_number)

    # Create or update contact with form data
    if body.caller_name or body.notes:
        from app.models.contact import Contact

        contact_result = await db.execute(
            select(Contact).where(
                Contact.workspace_id == agent.workspace_id,
                Contact.phone_hash == hash_phone(body.phone_number),
            )
        )
        contact = contact_result.scalar_one_or_none()

        if contact:
            if body.caller_name:
                parts = body.caller_name.strip().split(" ", 1)
                contact.first_name = parts[0]
                if len(parts) > 1:
                    contact.last_name = parts[1]
            if body.notes:
                contact.notes = body.notes
        else:
            first_name = "Demo Visitor"
            last_name = None
            if body.caller_name:
                parts = body.caller_name.strip().split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else None

            contact = Contact(
                workspace_id=agent.workspace_id,
                first_name=first_name,
                last_name=last_name,
                phone_number=body.phone_number,
                phone_hash=hash_phone(body.phone_number),
                notes=body.notes,
                source="embed_demo",
            )
            db.add(contact)

        await db.flush()

    # Record the request
    demo_record = DemoRequest(
        phone_number=body.phone_number,
        request_type="embed_call",
        client_ip=client_ip,
    )
    db.add(demo_record)
    await db.flush()

    # Initiate the call
    voice_service = TelnyxVoiceService(settings.telnyx_api_key)
    try:
        api_base = settings.api_base_url or "https://example.com"
        webhook_url = f"{api_base}/webhooks/telnyx/voice"
        connection_id = settings.telnyx_connection_id if settings.telnyx_connection_id else None

        await voice_service.initiate_call(
            to_number=body.phone_number,
            from_number=settings.demo_from_phone_number,
            connection_id=connection_id,
            webhook_url=webhook_url,
            db=db,
            workspace_id=agent.workspace_id,
            contact_phone=body.phone_number,
            agent_id=agent.id,
        )

        demo_record.status = "initiated"
        await db.commit()

        return {
            "success": True,
            "message": "Call initiated! You should receive a call within 10 seconds.",
        }
    except Exception as e:
        demo_record.status = "failed"
        demo_record.error_message = str(e)[:500]
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate call. Please try again.",
        ) from e
    finally:
        await voice_service.close()


@router.post("/{public_id}/text")
async def trigger_embed_text(
    public_id: str,
    body: EmbedPhoneRequest,
    request: Request,
    db: DB,
) -> dict[str, bool | str]:
    """Trigger an AI text via the embed widget."""
    agent = await get_agent_by_public_id(db, public_id)

    # Validate origin
    if not validate_origin(request, agent.allowed_domains):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed",
        )

    if not settings.telnyx_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMS service not available",
        )

    client_ip = get_client_ip(request, settings.trusted_proxies)
    await _check_embed_rate_limits(db, client_ip, body.phone_number)

    # Record the request
    demo_record = DemoRequest(
        phone_number=body.phone_number,
        request_type="embed_text",
        client_ip=client_ip,
    )
    db.add(demo_record)
    await db.flush()

    # Send initial text using agent's greeting (not hardcoded)
    default_greeting = f"Hi! Thanks for reaching out to {agent.name}. How can I help you today?"
    greeting = agent.initial_greeting or default_greeting
    sms_service = TelnyxSMSService(settings.telnyx_api_key)
    try:
        await sms_service.send_message(
            to_number=body.phone_number,
            from_number=settings.demo_from_phone_number,
            body=greeting,
            db=db,
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
        )

        demo_record.status = "initiated"
        await db.commit()

        return {
            "success": True,
            "message": "Text sent! Check your phone for a message.",
        }
    except Exception as e:
        demo_record.status = "failed"
        demo_record.error_message = str(e)[:500]
        await db.commit()

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send text. Please try again.",
        ) from e
    finally:
        await sms_service.close()
