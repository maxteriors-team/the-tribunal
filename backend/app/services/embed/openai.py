"""OpenAI-backed behavior for public embed chat and voice sessions."""

from collections.abc import Callable
from typing import Any

import httpx
import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent
from app.schemas.embed import ChatRequest, ChatResponse, TokenResponse
from app.services.ai.image_input import build_chat_user_message_with_image
from app.services.ai.openai_credentials import OpenAICredentialError, resolve_openai_credentials
from app.services.ai.openai_realtime_config import (
    RealtimeSessionConfig,
    build_client_secret_request,
    build_realtime_session_config,
    extract_realtime_client_secret_value,
)

logger = structlog.get_logger()

OPENAI_REALTIME_CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
EMBED_CHAT_MODEL = "gpt-5.4-nano"

HttpClientFactory = Callable[[], httpx.AsyncClient]


def build_embed_tools() -> list[dict[str, object]]:
    """Build the browser-visible tools supported by embed sessions."""
    return [
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
    ]


def build_embed_realtime_session(agent: Agent) -> RealtimeSessionConfig:
    """Build the server-bound Realtime session config for an embed agent."""
    return build_realtime_session_config(
        instructions=agent.system_prompt,
        voice=agent.voice_id,
        turn_detection_mode=agent.turn_detection_mode,
        turn_detection_threshold=agent.turn_detection_threshold,
        silence_duration_ms=agent.silence_duration_ms,
        idle_timeout_ms=settings.openai_realtime_idle_timeout_ms,
        language=agent.language,
    )


def build_embed_chat_messages(agent: Agent, body: ChatRequest) -> list[dict[str, Any]]:
    """Build OpenAI Chat Completions messages from embed request state.

    When the request carries an image, the latest user turn is sent as a
    multimodal content array so the vision-capable model can "see" the photo
    and ground its reply in it.
    """
    messages: list[dict[str, Any]] = [{"role": "system", "content": agent.system_prompt}]
    messages.extend(body.conversation_history[-agent.text_max_context_messages :])
    messages.append(build_chat_user_message_with_image(body.message, body.image))
    return messages


def _extract_chat_response_text(payload: dict[str, Any]) -> str:
    """Extract assistant text from an OpenAI Chat Completions response."""
    choices = payload.get("choices", [])
    first_choice = choices[0] if choices else {}
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    return content if isinstance(content, str) else ""


class EmbedOpenAIService:
    """Create OpenAI Realtime sessions and chat responses for public embeds."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self.db = db
        self.http_client_factory = http_client_factory or httpx.AsyncClient
        self.log = logger.bind(component="embed_openai_service")

    async def create_realtime_token(self, agent: Agent) -> TokenResponse:
        """Mint an OpenAI Realtime client secret for an embed voice session."""
        try:
            credential_context = await resolve_openai_credentials(self.db, agent.workspace_id)
        except OpenAICredentialError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Voice service not configured",
            ) from None

        session_config = build_embed_realtime_session(agent)
        client_secret_body = build_client_secret_request(session=session_config)

        async with self.http_client_factory() as client:
            response = await client.post(
                OPENAI_REALTIME_CLIENT_SECRET_URL,
                headers={
                    **credential_context.openai_headers(),
                    "Content-Type": "application/json",
                },
                json=client_secret_body,
                timeout=30.0,
            )

        if response.status_code != 200:
            self.log.error(
                "openai_session_error",
                status=response.status_code,
                credential_source=credential_context.source,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to create voice session",
            )

        session_data = response.json()
        return TokenResponse(
            client_secret={"value": extract_realtime_client_secret_value(session_data) or ""},
            agent={
                "name": agent.name,
                "voice": agent.voice_id,
                "language": agent.language,
                "initial_greeting": agent.initial_greeting,
            },
            model=session_config["model"],
            tools=build_embed_tools(),
        )

    async def send_chat_message(self, agent: Agent, body: ChatRequest) -> ChatResponse:
        """Send an embed chat request to OpenAI and return assistant text."""
        try:
            credential_context = await resolve_openai_credentials(self.db, agent.workspace_id)
        except OpenAICredentialError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chat service not configured",
            ) from None

        messages = build_embed_chat_messages(agent, body)
        async with self.http_client_factory() as client:
            response = await client.post(
                OPENAI_CHAT_COMPLETIONS_URL,
                headers={
                    **credential_context.openai_headers(),
                    "Content-Type": "application/json",
                },
                json={
                    "model": EMBED_CHAT_MODEL,
                    "messages": messages,
                    "temperature": agent.temperature,
                    "max_completion_tokens": agent.max_tokens,
                },
                timeout=60.0,
            )

        if response.status_code != 200:
            self.log.error(
                "openai_chat_error",
                status=response.status_code,
                credential_source=credential_context.source,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to get AI response",
            )

        return ChatResponse(response=_extract_chat_response_text(response.json()), tool_calls=[])
