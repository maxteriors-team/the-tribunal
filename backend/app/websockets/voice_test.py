"""Voice test WebSocket endpoint for browser-based agent testing."""

import asyncio
import base64
import contextlib
import json
import uuid
from typing import Any

try:
    import audioop
except ModuleNotFoundError:
    import audioop_lts as audioop  # type: ignore[no-redef]

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.ai.elevenlabs_voice_agent import ElevenLabsVoiceAgentSession
from app.services.ai.grok import GrokVoiceAgentSession
from app.services.ai.openai_credentials import OpenAICredentialError, resolve_openai_credentials
from app.services.ai.voice_agent import VoiceAgentSession
from app.websockets.connection_limits import (
    HeartbeatMonitor,
    acquire_connection_slot,
    acquire_workspace_slot,
    enforce_duration_cap,
    voice_test_semaphore,
)

router = APIRouter()
logger = structlog.get_logger()

# Type alias for voice sessions
VoiceSessionType = VoiceAgentSession | GrokVoiceAgentSession | ElevenLabsVoiceAgentSession


async def _authenticate_websocket(  # noqa: PLR0911
    websocket: WebSocket,
    workspace_id: str,
    log: Any,
) -> bool:
    """Authenticate WebSocket connection via JWT token in query params.

    Validates the token and checks the user has access to the workspace.
    Must be called BEFORE websocket.accept().

    Args:
        websocket: WebSocket connection (not yet accepted)
        workspace_id: Workspace UUID the user is trying to access
        log: Logger instance

    Returns:
        True if authenticated and authorized, False otherwise
    """
    # Prefer query-param ticket (issued via /auth/ws-ticket); fall back to the
    # httpOnly access cookie if the WS handshake is same-origin.
    token = websocket.query_params.get("token") or websocket.cookies.get("access_token")
    if not token:
        log.warning("ws_auth_failed", reason="no_token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False

    payload = decode_access_token(token)
    if payload is None:
        log.warning("ws_auth_failed", reason="invalid_token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        log.warning("ws_auth_failed", reason="no_subject_in_token")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        log.warning("ws_auth_failed", reason="invalid_user_id")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return False

    async with AsyncSessionLocal() as db:
        # Verify user exists and is active
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None or not user.is_active:
            log.warning("ws_auth_failed", reason="user_not_found_or_inactive", user_id=user_id)
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return False

        # Verify user has access to the workspace
        membership_result = await db.execute(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.workspace_id == workspace_id,
            )
        )
        membership = membership_result.scalar_one_or_none()
        if membership is None:
            log.warning(
                "ws_auth_failed",
                reason="no_workspace_access",
                user_id=user_id,
                workspace_id=workspace_id,
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return False

    log.info("ws_auth_success", user_id=user_id)
    return True


async def _get_agent_by_id(agent_id: str, workspace_id: str, log: Any) -> Any:
    """Look up an agent by ID.

    Args:
        agent_id: Agent UUID
        workspace_id: Workspace UUID
        log: Logger instance

    Returns:
        Agent model or None
    """
    from sqlalchemy import select

    from app.models.agent import Agent

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Agent).where(
                Agent.id == agent_id,
                Agent.workspace_id == workspace_id,
            )
        )
        agent = result.scalar_one_or_none()
        if agent:
            log.info("found_agent", agent_id=str(agent.id), agent_name=agent.name)
        return agent


async def _create_voice_session_for_test(  # noqa: PLR0911
    voice_provider: str,
    agent: Any,
    workspace_id: str,
) -> tuple[VoiceSessionType | None, str | None]:
    """Create appropriate voice session based on provider.

    Args:
        voice_provider: Provider name (openai, grok, elevenlabs)
        agent: Agent model for configuration

    Returns:
        Tuple of (voice_session, error_message)
    """
    if voice_provider == "elevenlabs":
        # ElevenLabs hybrid mode: Grok STT+LLM + ElevenLabs TTS
        if not settings.elevenlabs_api_key:
            return None, "ElevenLabs API key not configured"
        if not settings.xai_api_key:
            return None, "xAI API key required for ElevenLabs mode (used for STT+LLM)"
        return ElevenLabsVoiceAgentSession(
            xai_api_key=settings.xai_api_key,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            agent=agent,
        ), None

    if voice_provider == "grok":
        if not settings.xai_api_key:
            return None, "xAI API key not configured"
        return GrokVoiceAgentSession(settings.xai_api_key, agent), None

    # Default to OpenAI
    async with AsyncSessionLocal() as db:
        try:
            credential_context = await resolve_openai_credentials(db, uuid.UUID(workspace_id))
        except OpenAICredentialError:
            return None, "OpenAI credential not configured"
    return VoiceAgentSession(
        credential_context.bearer_token,
        agent,
        additional_headers={
            key: value
            for key, value in credential_context.openai_headers().items()
            if key != "Authorization"
        },
    ), None


async def _handle_start_message(
    websocket: WebSocket,
    voice_session: VoiceSessionType,
    agent: Any,
    voice_provider: str,
    log: Any,
) -> asyncio.Task[None] | None:
    """Handle the start message from client.

    Returns:
        Task for receiving audio, or None if connection failed
    """
    if not await voice_session.connect():
        log.error("failed_to_connect_to_voice_provider")
        await websocket.send_json(
            {
                "type": "error",
                "message": f"Failed to connect to {voice_provider}",
            }
        )
        return None

    log.info("voice_session_connected")

    # Configure session with agent settings
    await voice_session.configure_session(
        voice=agent.voice_id,
        system_prompt=agent.system_prompt,
        temperature=agent.temperature,
    )

    await websocket.send_json(
        {
            "type": "connected",
            "audio_format": {"encoding": "pcm16", "sampleRate": 24000, "channels": 1},
        }
    )

    # Start receiving audio from provider
    receive_task = asyncio.create_task(
        _receive_from_provider(websocket, voice_session, voice_provider, log)
    )

    # Trigger initial greeting if configured
    if agent.initial_greeting:
        await voice_session.trigger_initial_response(agent.initial_greeting)

    return receive_task


def _normalize_client_audio_for_provider(
    audio_pcm16_16k: bytes,
    voice_provider: str,
) -> bytes:
    """Convert client PCM16 16kHz audio to the provider's expected format.

    - OpenAI expects g711_ulaw at 8kHz
    - Grok expects PCM16 at 24kHz
    - ElevenLabs hybrid uses Grok STT, so also PCM16 24kHz

    Args:
        audio_pcm16_16k: PCM16 audio at 16kHz from the mobile client
        voice_provider: Provider name (openai, grok, elevenlabs)

    Returns:
        Audio bytes in the provider's expected format
    """
    if voice_provider in ("grok", "elevenlabs"):
        # Resample PCM16 16kHz → 24kHz
        pcm_24k, _ = audioop.ratecv(audio_pcm16_16k, 2, 1, 16000, 24000, None)
        return pcm_24k

    # OpenAI: PCM16 16kHz → resample to 8kHz → encode as mu-law
    pcm_8k, _ = audioop.ratecv(audio_pcm16_16k, 2, 1, 16000, 8000, None)
    return audioop.lin2ulaw(pcm_8k, 2)


async def _handle_audio_message(
    voice_session: VoiceSessionType,
    message: dict[str, Any],
    voice_provider: str,
) -> None:
    """Handle audio message from client.

    Converts client PCM16 16kHz audio to the provider's expected format
    before forwarding.
    """
    audio_b64 = message.get("data", "")
    if audio_b64:
        audio_pcm = base64.b64decode(audio_b64)
        converted = _normalize_client_audio_for_provider(audio_pcm, voice_provider)
        await voice_session.send_audio_chunk(converted)


async def _process_messages(
    websocket: WebSocket,
    voice_session: VoiceSessionType,
    agent: Any,
    voice_provider: str,
    log: Any,
    heartbeat: HeartbeatMonitor | None = None,
) -> None:
    """Process incoming messages from the client.

    Args:
        websocket: WebSocket connection
        voice_session: Voice provider session
        agent: Agent model
        voice_provider: Provider name
        log: Logger instance
        heartbeat: Optional heartbeat monitor; ``mark_activity`` is called on
            every inbound frame and ``pong`` messages are consumed silently.
    """
    session_active = False
    receive_task: asyncio.Task[None] | None = None

    try:
        while True:
            raw_data = await websocket.receive_text()
            if heartbeat is not None:
                heartbeat.mark_activity()
            message = json.loads(raw_data)
            msg_type = message.get("type", "")

            if msg_type == "pong":
                # Heartbeat reply — ``mark_activity`` above already reset the
                # idle clock; nothing else to do.
                continue

            if msg_type == "start" and not session_active:
                receive_task = await _handle_start_message(
                    websocket, voice_session, agent, voice_provider, log
                )
                if receive_task:
                    session_active = True

            elif msg_type == "audio" and session_active:
                await _handle_audio_message(voice_session, message, voice_provider)

            elif msg_type == "stop":
                log.info("stop_requested")
                break

    except WebSocketDisconnect:
        log.info("websocket_disconnected")
    except json.JSONDecodeError as e:
        log.warning("invalid_json", error=str(e))
    finally:
        if receive_task:
            receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await receive_task


@router.websocket("/voice/test/{workspace_id}/{agent_id}")
async def voice_test_endpoint(
    websocket: WebSocket,
    workspace_id: str,
    agent_id: str,
) -> None:
    """WebSocket endpoint for browser-based voice agent testing.

    Authentication:
    - Requires a JWT token as a query parameter: ?token=<jwt>
    - The token is validated and the user must have access to the workspace
    - Connection is closed with 1008 (Policy Violation) if auth fails

    Protocol:
    - Client sends JSON messages with type field
    - Server sends JSON messages with type field

    Client -> Server:
        {"type": "start"} - Start the voice session
        {"type": "audio", "data": "<base64-pcm16>"} - Send audio chunk
        {"type": "stop"} - Stop the session

    Server -> Client:
        {"type": "connected"} - Session connected to voice provider
        {"type": "audio", "data": "<base64-pcm16>"} - Audio response
        {"type": "transcript", "role": "user"|"assistant", "text": "..."} - Transcript
        {"type": "error", "message": "..."} - Error message
        {"type": "stopped"} - Session stopped

    Args:
        websocket: WebSocket connection from browser
        workspace_id: Workspace UUID
        agent_id: Agent UUID to test
    """
    log = logger.bind(
        endpoint="voice_test",
        workspace_id=workspace_id,
        agent_id=agent_id,
    )
    log.info("voice_test_connection_received")

    # Backpressure: cap total concurrent test sessions across the process.
    async with acquire_connection_slot(
        websocket, voice_test_semaphore(), log, endpoint="voice_test"
    ) as slot_ok:
        if not slot_ok:
            return

        # Authenticate via JWT token in query params before accepting
        if not await _authenticate_websocket(websocket, workspace_id, log):
            return

        # Per-tenant cap (Redis-backed, shared across replicas).
        async with acquire_workspace_slot(websocket, workspace_id, log) as (
            ws_ok,
            _session_id,
        ):
            if not ws_ok:
                return

            await websocket.accept()

            # Look up the agent
            agent = await _get_agent_by_id(agent_id, workspace_id, log)
            if not agent:
                await websocket.send_json({"type": "error", "message": "Agent not found"})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            # Determine voice provider
            voice_provider = agent.voice_provider.lower() if agent.voice_provider else "openai"
            log.info("using_voice_provider", provider=voice_provider)

            # Create voice session
            voice_session, error = await _create_voice_session_for_test(
                voice_provider,
                agent,
                workspace_id,
            )
            if voice_session is None:
                log.error("api_key_not_configured", provider=voice_provider)
                await websocket.send_json({"type": "error", "message": error})
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            # Heartbeat + absolute duration backstop.
            heartbeat = HeartbeatMonitor(websocket, log)
            heartbeat.start()
            duration_task = asyncio.create_task(
                enforce_duration_cap(
                    websocket,
                    log,
                    max_seconds=settings.voice_max_call_duration_seconds,
                ),
                name="voice-test-duration-cap",
            )

            try:
                await _process_messages(
                    websocket, voice_session, agent, voice_provider, log, heartbeat
                )
            except Exception as e:
                log.exception("voice_test_error", error=str(e))
                with contextlib.suppress(Exception):
                    await websocket.send_json({"type": "error", "message": str(e)})
            finally:
                await heartbeat.stop()
                duration_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await duration_task
                await voice_session.disconnect()
                with contextlib.suppress(Exception):
                    await websocket.send_json({"type": "stopped"})
                    await websocket.close()
                log.info("voice_test_session_ended")


def _normalize_audio_to_pcm16_24k(audio_data: bytes, voice_provider: str) -> bytes:
    """Normalize audio from any provider to PCM16 at 24kHz.

    - Grok already outputs PCM16/24kHz — passed through unchanged.
    - OpenAI outputs g711_ulaw at 8kHz — decode ulaw→PCM16, upsample 8k→24k.
    - ElevenLabs outputs ulaw at 8kHz — decode ulaw→PCM16, upsample 8k→24k.

    Args:
        audio_data: Raw audio bytes from the provider
        voice_provider: Provider name (openai, grok, elevenlabs)

    Returns:
        PCM16 audio at 24kHz
    """
    if voice_provider == "grok":
        # Already PCM16/24kHz
        return audio_data

    # OpenAI and ElevenLabs: ulaw 8kHz → PCM16 24kHz
    # Step 1: Decode ulaw to linear PCM16 (2 bytes per sample)
    pcm_8k = audioop.ulaw2lin(audio_data, 2)

    # Step 2: Upsample from 8kHz to 24kHz (3x)
    pcm_24k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 24000, None)

    return pcm_24k


async def _receive_from_provider(
    websocket: WebSocket,
    voice_session: VoiceSessionType,
    voice_provider: str,
    log: Any,
) -> None:
    """Receive audio from voice provider and send to browser.

    All audio is normalized to PCM16/24kHz before sending to the client.

    Args:
        websocket: Browser WebSocket connection
        voice_session: Voice provider session
        voice_provider: Provider name for format detection
        log: Logger instance
    """
    try:
        async for audio_data in voice_session.receive_audio_stream():
            normalized = _normalize_audio_to_pcm16_24k(audio_data, voice_provider)
            audio_b64 = base64.b64encode(normalized).decode("utf-8")
            await websocket.send_json(
                {
                    "type": "audio",
                    "data": audio_b64,
                }
            )
    except asyncio.CancelledError:
        log.info("receive_task_cancelled")
    except Exception as e:
        log.exception("receive_from_provider_error", error=str(e))
