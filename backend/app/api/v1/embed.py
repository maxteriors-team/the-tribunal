"""Public embed API endpoints for embeddable agent widgets."""

from fastapi import APIRouter, Request

from app.api.deps import DB
from app.core.config import settings
from app.core.utils import get_client_ip
from app.schemas.embed import (
    ChatRequest,
    ChatResponse,
    EmbedActionResponse,
    EmbedConfigResponse,
    EmbedPhoneRequest,
    TokenRequest,
    TokenResponse,
    ToolCallRequest,
    ToolCallResponse,
    TranscriptRequest,
    TranscriptResponse,
)
from app.services.embed.access import verified_parent_origin
from app.services.embed.service import PublicEmbedService

router = APIRouter()


def _parent_origin(request: Request, *, public_id: str) -> str:
    """Resolve the real host page for cross- and same-origin iframe fetches."""
    return verified_parent_origin(request, public_id=public_id)


def _client_ip(request: Request) -> str:
    """Return the validated caller IP for public embed rate limits."""
    return get_client_ip(request, settings.trusted_proxies)


@router.get("/{public_id}/config", response_model=EmbedConfigResponse)
async def get_embed_config(
    public_id: str,
    request: Request,
    db: DB,
) -> EmbedConfigResponse:
    """Get public configuration for the embed widget."""
    return await PublicEmbedService(db).get_config(
        public_id=public_id, origin=_parent_origin(request, public_id=public_id)
    )


@router.post("/{public_id}/token", response_model=TokenResponse)
async def get_ephemeral_token(
    public_id: str,
    request: Request,
    db: DB,
    body: TokenRequest | None = None,
) -> TokenResponse:
    """Get an ephemeral token for OpenAI Realtime WebRTC connection."""
    del body
    return await PublicEmbedService(db).create_realtime_token(
        public_id=public_id,
        origin=_parent_origin(request, public_id=public_id),
        client_ip=_client_ip(request),
    )


@router.post("/{public_id}/chat", response_model=ChatResponse)
async def send_chat_message(
    public_id: str,
    body: ChatRequest,
    request: Request,
    db: DB,
) -> ChatResponse:
    """Send a chat message and get AI response."""
    return await PublicEmbedService(db).send_chat_message(
        public_id=public_id,
        origin=_parent_origin(request, public_id=public_id),
        client_ip=_client_ip(request),
        body=body,
    )


@router.post("/{public_id}/tool-call", response_model=ToolCallResponse)
async def execute_tool_call(
    public_id: str,
    body: ToolCallRequest,
    request: Request,
    db: DB,
) -> ToolCallResponse:
    """Execute a tool call from the AI."""
    return await PublicEmbedService(db).execute_tool_call(
        public_id=public_id,
        origin=_parent_origin(request, public_id=public_id),
        client_ip=_client_ip(request),
        body=body,
    )


@router.post("/{public_id}/transcript", response_model=TranscriptResponse)
async def save_transcript(
    public_id: str,
    body: TranscriptRequest,
    request: Request,
    db: DB,
) -> TranscriptResponse:
    """Save a conversation transcript."""
    return await PublicEmbedService(db).save_transcript(
        public_id=public_id,
        origin=_parent_origin(request, public_id=public_id),
        client_ip=_client_ip(request),
        body=body,
    )


@router.post("/{public_id}/call", response_model=EmbedActionResponse)
async def trigger_embed_call(
    public_id: str,
    body: EmbedPhoneRequest,
    request: Request,
    db: DB,
) -> EmbedActionResponse:
    """Trigger an AI call via the embed widget."""
    return await PublicEmbedService(db).trigger_call(
        public_id=public_id,
        origin=_parent_origin(request, public_id=public_id),
        client_ip=_client_ip(request),
        body=body,
    )


@router.post("/{public_id}/text", response_model=EmbedActionResponse)
async def trigger_embed_text(
    public_id: str,
    body: EmbedPhoneRequest,
    request: Request,
    db: DB,
) -> EmbedActionResponse:
    """Trigger an AI text via the embed widget."""
    return await PublicEmbedService(db).trigger_text(
        public_id=public_id,
        origin=_parent_origin(request, public_id=public_id),
        client_ip=_client_ip(request),
        body=body,
    )
