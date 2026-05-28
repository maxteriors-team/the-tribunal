"""Voice bridge WebSocket endpoint for Telnyx media streaming.

This module handles bidirectional audio streaming between Telnyx (telephony)
and AI voice providers (OpenAI/Grok). Key considerations:

- Telnyx uses μ-law (G.711) at 8kHz sample rate
- OpenAI/Grok Realtime API uses PCM16 at 24kHz
- Audio must be converted and resampled in both directions (3x ratio)
- Supports tool calling for Cal.com booking integration

Architecture Note:
    Audio conversion, tool execution, call context, and session factory
    logic has been extracted to dedicated modules in app/services/audio/
    and app/services/ai/ for better testability and maintainability.
"""

import asyncio
import base64
import contextlib
import time
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import update

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.conversation import Message
from app.services.ai.call_context import lookup_call_context, save_call_transcript
from app.services.ai.elevenlabs_voice_agent import ElevenLabsVoiceAgentSession
from app.services.ai.grok import GrokVoiceAgentSession
from app.services.ai.ivr.gate import GateOutcome, GateResult, IVRGate
from app.services.ai.openai_credentials import is_openai_configured
from app.services.ai.protocols import supports_tools
from app.services.ai.tool_executor import create_tool_callback
from app.services.ai.voice_agent import VoiceAgentSession
from app.services.ai.voice_session_factory import create_workspace_voice_session
from app.services.audio import (
    TELNYX_MIN_CHUNK_BYTES,
    convert_openai_to_telnyx,
    convert_telnyx_to_openai,
)
from app.websockets.connection_limits import (
    HeartbeatMonitor,
    acquire_connection_slot,
    acquire_workspace_slot,
    enforce_duration_cap,
    voice_bridge_semaphore,
)

router = APIRouter()
logger = structlog.get_logger()

_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key", "proxy-authorization"}


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    """Redact sensitive header values to prevent leaking secrets in logs."""
    return {k: "***" if k.lower() in _SENSITIVE_HEADERS else v for k, v in headers.items()}


async def _lookup_call_context_wrapper(
    call_id: str,
    log: Any,
) -> tuple[Any, dict[str, Any] | None, dict[str, Any] | None, str, str | None]:
    """Look up agent, contact, and offer context for a call.

    Wrapper around call_context.lookup_call_context to maintain backward
    compatibility with existing code.

    Returns:
        Tuple of (agent, contact_info, offer_info, timezone, prompt_version_id)
    """
    context = await lookup_call_context(call_id, log)
    return (
        context.agent,
        context.contact_info,
        context.offer_info,
        context.timezone,
        context.prompt_version_id,
    )


VoiceSessionType = VoiceAgentSession | GrokVoiceAgentSession | ElevenLabsVoiceAgentSession


async def _save_call_transcript_wrapper(call_id: str, transcript_json: str, log: Any) -> None:
    """Save transcript - wrapper around call_context.save_call_transcript."""
    await save_call_transcript(call_id, transcript_json, log)


async def _save_call_duration(call_id: str, duration_seconds: int, log: Any) -> None:
    """Save call duration from streaming session to message record."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Message)
            .where(Message.provider_message_id == call_id)
            .values(duration_seconds=duration_seconds)
        )
        await db.commit()
        log.info("streaming_duration_saved", call_id=call_id, duration_seconds=duration_seconds)


async def _stamp_prompt_version_on_message(call_id: str, prompt_version_id: str, log: Any) -> None:
    """Stamp prompt version ID on the message record for attribution."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(Message)
                .where(Message.provider_message_id == call_id)
                .values(prompt_version_id=uuid.UUID(prompt_version_id))
            )
            await db.commit()
            log.info(
                "prompt_version_stamped_on_message",
                call_id=call_id,
                prompt_version_id=prompt_version_id,
                rows_updated=result.rowcount,  # type: ignore[attr-defined]
            )
    except Exception as e:
        log.exception("failed_to_stamp_prompt_version", error=str(e), call_id=call_id)


async def _setup_voice_session(
    voice_session: VoiceSessionType,
    agent: Any,
    contact_info: dict[str, Any] | None,
    offer_info: dict[str, Any] | None,
    timezone: str,
    log: Any,
    call_control_id: str | None = None,
    is_outbound: bool = True,
    *,
    skip_ivr_detection: bool = False,
) -> None:
    """Configure voice session with agent settings and context.

    Note: The greeting is NOT sent here. It's triggered when the Telnyx
    stream starts (in _receive_from_telnyx_and_send_to_provider) to ensure
    audio is ready before the AI starts speaking.

    Args:
        skip_ivr_detection: If True, skip AI-based IVR detection (Phase 1 gate handled it)
    """
    # Set up tool callback for any provider session that supports tool calls.
    if supports_tools(voice_session):
        log.info(
            "setting_up_tool_callback",
            session_type=type(voice_session).__name__,
            agent_name=agent.name if agent else None,
            calcom_event_type_id=agent.calcom_event_type_id if agent else None,
        )

        # Use the extracted tool executor to create callback
        callback = create_tool_callback(
            agent=agent,
            contact_info=contact_info,
            timezone=timezone,
            call_control_id=call_control_id,
            log=log,
        )

        voice_session.set_tool_callback(callback)
        log.info("tool_callback_configured", session_type=type(voice_session).__name__)

        # Enable IVR detection for outbound Grok calls ONLY if agent has it enabled
        # Skip if Phase 1 gate already handled IVR navigation
        if (
            is_outbound
            and isinstance(voice_session, GrokVoiceAgentSession)
            and not skip_ivr_detection
        ):
            # Check if agent has IVR navigation enabled
            ivr_enabled = agent and getattr(agent, "enable_ivr_navigation", False)

            if ivr_enabled:
                # Determine navigation goal from agent config or offer info
                navigation_goal: str | None = None
                if agent.ivr_navigation_goal:
                    navigation_goal = agent.ivr_navigation_goal
                elif offer_info and offer_info.get("name"):
                    navigation_goal = f"Reach someone to discuss {offer_info['name']}"
                else:
                    navigation_goal = "Reach a human representative"

                # Get loop threshold from agent config or use default
                loop_threshold = agent.ivr_loop_threshold if agent.ivr_loop_threshold else 2

                # Get IVR timing configuration from agent
                ivr_config = {
                    "silence_duration_ms": getattr(agent, "ivr_silence_duration_ms", 3000),
                    "post_dtmf_cooldown_ms": getattr(agent, "ivr_post_dtmf_cooldown_ms", 3000),
                    "menu_buffer_silence_ms": getattr(agent, "ivr_menu_buffer_silence_ms", 2000),
                }

                voice_session.enable_ivr_detection(
                    navigation_goal=navigation_goal,
                    loop_threshold=loop_threshold,
                    ivr_config=ivr_config,
                )
                log.info(
                    "ivr_detection_enabled_for_outbound",
                    navigation_goal=navigation_goal,
                    loop_threshold=loop_threshold,
                    ivr_config=ivr_config,
                )
            else:
                log.info(
                    "ivr_detection_skipped_agent_disabled",
                    agent_name=agent.name if agent else None,
                    enable_ivr_navigation=False,
                )
        elif skip_ivr_detection:
            log.info("ivr_detection_skipped_phase1_gate_handled")
    else:
        log.info(
            "tool_callback_not_configured",
            session_type=type(voice_session).__name__,
            reason="Session type does not support tools",
        )

    if agent:
        await voice_session.configure_session(
            voice=agent.voice_id,
            system_prompt=agent.system_prompt,
            temperature=agent.temperature,
            turn_detection_mode=agent.turn_detection_mode,
            turn_detection_threshold=agent.turn_detection_threshold,
            silence_duration_ms=agent.silence_duration_ms,
        )
        log.info("session_configured_with_agent_settings", agent_name=agent.name)

    if contact_info or offer_info:
        await voice_session.inject_context(
            contact_info=contact_info,
            offer_info=offer_info,
            is_outbound=is_outbound,
        )
        log.info(
            "context_injected",
            has_contact=bool(contact_info),
            has_offer=bool(offer_info),
            is_outbound=is_outbound,
        )

    if agent and agent.initial_greeting:
        log.info("initial_greeting_prepared", greeting_length=len(agent.initial_greeting))


@router.websocket("/voice/stream/{call_id}")
async def voice_stream_bridge(  # noqa: PLR0912, PLR0915
    websocket: WebSocket,
    call_id: str,
    is_outbound: bool = Query(default=False),
) -> None:
    """Bridge between Telnyx media stream and voice AI provider.

    This WebSocket endpoint receives audio from Telnyx (μ-law 8kHz) and
    relays it to OpenAI/Grok (PCM16 24kHz), and vice versa.

    Supports multiple providers:
    - OpenAI Realtime API (default)
    - Grok (xAI) Realtime API

    Args:
        websocket: WebSocket connection from Telnyx
        call_id: Telnyx call control ID
        is_outbound: If True, this is an outbound call and the AI uses an outbound opener
    """
    connection_start = time.time()
    log = logger.bind(endpoint="voice_stream_bridge", call_id=call_id, is_outbound=is_outbound)
    log.info(
        "========== VOICE BRIDGE START ==========",
        call_id=call_id,
        is_outbound=is_outbound,
    )
    log.info(
        "voice_bridge_connection_received",
        client_host=websocket.client.host if websocket.client else "unknown",
        client_port=websocket.client.port if websocket.client else "unknown",
        headers=_safe_headers(dict(websocket.headers)) if hasattr(websocket, "headers") else {},
    )

    # Global backpressure: cap total concurrent voice bridges across the
    # process. Telnyx will retry on WS_1013 (try again later).
    async with acquire_connection_slot(
        websocket, voice_bridge_semaphore(), log, endpoint="voice_bridge"
    ) as slot_ok:
        if not slot_ok:
            return

        await websocket.accept()
        log.info("websocket_accepted", state="connection_established")

        # Get agent and conversation context from database first to determine
        # provider — we also need workspace_id for the per-tenant cap below.
        log.info("looking_up_call_context", call_id=call_id)
        full_context = await lookup_call_context(call_id, log)
        agent = full_context.agent
        contact_info = full_context.contact_info
        offer_info = full_context.offer_info
        timezone = full_context.timezone
        prompt_version_id = full_context.prompt_version_id
        workspace_id = full_context.workspace_id

        # Per-tenant cap (Redis-backed). Fails open on Redis outage so a cache
        # blip can't drop live calls. Heartbeat watchdog + duration backstop
        # run inside this scope so they're armed for the entire phase block.
        async with acquire_workspace_slot(websocket, workspace_id, log) as (ws_ok, _session_id):
            if not ws_ok:
                return

            heartbeat = HeartbeatMonitor(websocket, log, send_ping=False)
            heartbeat.start()
            duration_task = asyncio.create_task(
                enforce_duration_cap(
                    websocket,
                    log,
                    max_seconds=settings.voice_max_call_duration_seconds,
                ),
                name="voice-bridge-duration-cap",
            )
            # Stash heartbeat on the websocket scope so the deeply-nested
            # Telnyx receive loop can call ``mark_activity()`` on each frame
            # without threading an extra parameter through every helper.
            websocket.scope["voice_heartbeat"] = heartbeat

            try:
                await _voice_stream_bridge_body(
                    websocket=websocket,
                    call_id=call_id,
                    is_outbound=is_outbound,
                    connection_start=connection_start,
                    log=log,
                    agent=agent,
                    contact_info=contact_info,
                    offer_info=offer_info,
                    timezone=timezone,
                    prompt_version_id=prompt_version_id,
                    workspace_id=workspace_id,
                )
            finally:
                await heartbeat.stop()
                duration_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await duration_task


async def _voice_stream_bridge_body(  # noqa: PLR0912, PLR0915
    *,
    websocket: WebSocket,
    call_id: str,
    is_outbound: bool,
    connection_start: float,
    log: Any,
    agent: Any,
    contact_info: dict[str, Any] | None,
    offer_info: dict[str, Any] | None,
    timezone: str,
    prompt_version_id: str | None,
    workspace_id: str | None,
) -> None:
    """Core bridge handler running inside the capacity-guard scope.

    Split out so the ``async with`` block over the global semaphore and the
    per-workspace Redis cap stay at the top of the endpoint and pyright/ruff
    don't trip on an even-longer function body.
    """

    # Stamp prompt version on message for attribution
    if prompt_version_id:
        await _stamp_prompt_version_on_message(call_id, prompt_version_id, log)

    greeting_preview = None
    if agent and agent.initial_greeting:
        greeting_preview = agent.initial_greeting[:50]
    log.info(
        "call_context_lookup_result",
        agent_found=agent is not None,
        agent_id=str(agent.id) if agent else None,
        agent_name=agent.name if agent else None,
        agent_voice_provider=agent.voice_provider if agent else None,
        agent_voice_id=agent.voice_id if agent else None,
        agent_initial_greeting=greeting_preview,
        contact_found=contact_info is not None,
        contact_name=contact_info.get("name") if contact_info else None,
        offer_found=offer_info is not None,
        timezone=timezone,
        prompt_version_id=prompt_version_id,
    )

    if not agent:
        log.warning(
            "no_agent_found_for_call",
            call_id=call_id,
            hint="Check message has agent_id and conversation has assigned_agent_id",
        )

    # ── Phase 1: IVR Gate ──────────────────────────────────────────────
    # For outbound calls with IVR navigation enabled, run the cheap
    # Phase 1 gate (Whisper transcription + regex classification) before
    # connecting the expensive AI provider.
    ivr_gate_active = (
        is_outbound and agent is not None and getattr(agent, "enable_ivr_navigation", False)
    )

    gate_result: GateResult | None = None
    if ivr_gate_active:
        navigation_goal = "Reach a human representative"
        if agent.ivr_navigation_goal:
            navigation_goal = agent.ivr_navigation_goal
        elif offer_info and offer_info.get("name"):
            navigation_goal = f"Reach someone to discuss {offer_info['name']}"

        gate = IVRGate(
            call_control_id=call_id,
            navigation_goal=navigation_goal,
            agent_config={
                "loop_threshold": agent.ivr_loop_threshold or 2,
                "post_dtmf_cooldown_ms": getattr(agent, "ivr_post_dtmf_cooldown_ms", 3000),
                "silence_duration_ms": getattr(agent, "ivr_silence_duration_ms", 3000),
            },
            log=log,
        )
        gate_result = await gate.run(websocket)
        log.info(
            "ivr_gate_result",
            outcome=gate_result.outcome.value,
            duration=round(gate_result.duration_seconds, 1),
            dtmf_attempts=gate_result.dtmf_attempts,
            transcripts=len(gate_result.transcript_history),
        )

        if gate_result.outcome == GateOutcome.VOICEMAIL_DETECTED:
            # Hangup - webhook handler will trigger SMS fallback
            log.info("ivr_gate_voicemail_hangup", call_id=call_id)
            from app.services.telephony.telnyx_voice import TelnyxVoiceService

            svc = TelnyxVoiceService(settings.telnyx_api_key)
            await svc.hangup_call(call_id)
            elapsed = time.time() - connection_start
            with contextlib.suppress(Exception):
                await _save_call_duration(call_id, round(elapsed), log)
            with contextlib.suppress(Exception):
                await websocket.close()
            return

        if gate_result.outcome == GateOutcome.CALL_DROPPED:
            log.info("ivr_gate_call_dropped", call_id=call_id)
            elapsed = time.time() - connection_start
            with contextlib.suppress(Exception):
                await _save_call_duration(call_id, round(elapsed), log)
            with contextlib.suppress(Exception):
                await websocket.close()
            return

        # HUMAN_DETECTED, TIMEOUT, FALLBACK_AI, ERROR → proceed to Phase 2

        # Inject IVR navigation context for Phase 2 AI
        if gate_result.transcript_history:
            contact_info = dict(contact_info) if contact_info else {}
            contact_info["ivr_navigation_context"] = (
                "[IVR Navigation Complete] You navigated through an automated phone system. "
                f"What you heard: {' | '.join(gate_result.transcript_history)}"
            )

    # ── Phase 2: AI Provider ───────────────────────────────────────────
    # Determine which voice provider to use
    voice_provider = "openai"  # default
    if agent and agent.voice_provider:
        voice_provider = agent.voice_provider.lower()

    log.info(
        "voice_provider_selected",
        provider=voice_provider,
        agent_name=agent.name if agent else None,
        agent_id=str(agent.id) if agent else None,
        has_contact=contact_info is not None,
        has_offer=offer_info is not None,
        openai_credential_configured=is_openai_configured(),
        xai_key_configured=bool(settings.xai_api_key),
        elevenlabs_key_configured=bool(settings.elevenlabs_api_key),
    )

    # Create appropriate voice session based on provider
    log.info("creating_voice_session", provider=voice_provider)
    if workspace_id is None:
        log.error(
            "voice_session_creation_failed",
            provider=voice_provider,
            error="Workspace not found",
        )
        await websocket.send_json({"error": "Workspace not found"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    async with AsyncSessionLocal() as db:
        voice_session, error = await create_workspace_voice_session(
            db,
            uuid.UUID(workspace_id),
            voice_provider,
            agent,
            timezone,
        )
    if voice_session is None:
        log.error(
            "voice_session_creation_failed",
            provider=voice_provider,
            error=error,
            hint="Check API keys in environment variables",
        )
        await websocket.send_json({"error": error})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    log.info(
        "voice_session_created",
        provider=voice_provider,
        session_type=type(voice_session).__name__,
    )

    relay_task: asyncio.Task[None] | None = None

    try:
        # Connect to voice provider
        log.info(
            "connecting_to_voice_provider",
            provider=voice_provider,
            session_type=type(voice_session).__name__,
        )
        connect_start = time.time()

        connected = await voice_session.connect()
        connect_elapsed = time.time() - connect_start

        if not connected:
            log.error(
                "failed_to_connect_to_voice_provider",
                provider=voice_provider,
                elapsed_secs=round(connect_elapsed, 2),
                hint="Check API key validity and network connectivity",
            )
            await websocket.send_json(
                {"error": f"Failed to connect to {voice_provider} Realtime API"}
            )
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return

        def _ws_status() -> str:
            """Check WebSocket connection status."""
            if hasattr(voice_session, "is_connected"):
                return str(voice_session.is_connected())
            return "unknown"

        log.info(
            "connected_to_voice_provider",
            provider=voice_provider,
            connect_time_secs=round(connect_elapsed, 2),
            ws_connected=_ws_status(),
        )

        # Configure session with agent settings and inject context
        log.info(
            "configuring_voice_session",
            has_agent=agent is not None,
            has_contact=contact_info is not None,
            has_offer=offer_info is not None,
        )
        await _setup_voice_session(
            voice_session,
            agent,
            contact_info,
            offer_info,
            timezone,
            log,
            call_control_id=call_id,
            is_outbound=is_outbound,
            skip_ivr_detection=bool(gate_result),
        )
        log.info(
            "voice_session_configured",
            ws_still_connected=_ws_status(),
        )

        # Start bidirectional audio relay
        log.info(
            "starting_relay_task",
            telnyx_ws_open=True,
            provider_ws_open=_ws_status(),
            is_outbound=is_outbound,
        )
        relay_task = asyncio.create_task(
            _relay_audio(
                websocket,
                voice_session,
                log,
                is_outbound=is_outbound,
                stream_already_started=bool(gate_result),
            )
        )

        # Wait for relay to complete (it will run until disconnect)
        log.info("waiting_for_relay_completion")
        await relay_task
        log.info("relay_task_completed")

    except WebSocketDisconnect:
        elapsed = time.time() - connection_start
        log.info(
            "telnyx_websocket_disconnected",
            total_connection_secs=round(elapsed, 1),
        )
    except asyncio.CancelledError:
        log.info("voice_bridge_cancelled")
    except Exception as e:
        elapsed = time.time() - connection_start
        log.exception(
            "voice_bridge_error",
            error=str(e),
            total_connection_secs=round(elapsed, 1),
        )
    finally:
        # Clean up relay task
        if relay_task and not relay_task.done():
            relay_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await relay_task

        elapsed = time.time() - connection_start

        # Save transcript and duration before disconnecting
        if call_id:
            if hasattr(voice_session, "get_transcript_json"):
                try:
                    transcript_json = voice_session.get_transcript_json()
                    if transcript_json:
                        await _save_call_transcript_wrapper(call_id, transcript_json, log)
                except Exception as e:
                    log.exception("failed_to_save_transcript", error=str(e))

            # Save streaming duration so hangup handler has accurate duration
            try:
                await _save_call_duration(call_id, round(elapsed), log)
            except Exception as e:
                log.exception("failed_to_save_duration", error=str(e))

        log.info("disconnecting_from_voice_provider")
        await voice_session.disconnect()

        with contextlib.suppress(Exception):
            await websocket.close()

        log.info(
            "voice_bridge_session_ended",
            total_duration_secs=round(elapsed, 1),
        )


async def _relay_audio(
    websocket: WebSocket,
    voice_session: VoiceSessionType,
    log: Any,
    *,
    is_outbound: bool = False,
    stream_already_started: bool = False,
) -> None:
    """Relay audio bidirectionally between Telnyx and voice provider.

    This function manages two concurrent tasks:
    1. Receiving audio from Telnyx and sending to OpenAI/Grok
    2. Receiving audio from OpenAI/Grok and sending to Telnyx

    A synchronization event ensures audio is only sent to Telnyx after
    the greeting has been triggered and the stream is ready.

    Args:
        websocket: Telnyx WebSocket connection
        voice_session: Voice provider session (OpenAI or Grok)
        log: Logger instance
        is_outbound: If True, this is an outbound call and the AI uses an outbound opener
        stream_already_started: If True, Phase 1 gate already consumed the start event
    """
    # Event to synchronize greeting trigger with audio sending
    greeting_triggered = asyncio.Event()

    # Event to signal interruption (barge-in) - clear audio buffer when user speaks
    interruption_event = asyncio.Event()

    # Pass interruption event to voice session for barge-in handling
    if hasattr(voice_session, "set_interruption_event"):
        voice_session.set_interruption_event(interruption_event)
        log.info("interruption_event_configured_for_voice_session")

    # Shared dict to pass stream_id from Telnyx start event to outbound sender
    stream_id_holder: dict[str, str] = {}

    def _get_ws_status() -> str:
        if hasattr(voice_session, "is_connected"):
            return str(voice_session.is_connected())
        return "unknown"

    log.info(
        "========== AUDIO RELAY START ==========",
        voice_session_type=type(voice_session).__name__,
        voice_session_connected=_get_ws_status(),
    )

    # Create tasks for bidirectional streaming
    send_task = asyncio.create_task(
        _receive_from_telnyx_and_send_to_provider(
            websocket,
            voice_session,
            log,
            greeting_triggered,
            stream_id_holder,
            is_outbound=is_outbound,
            stream_already_started=stream_already_started,
        )
    )
    recv_task = asyncio.create_task(
        _receive_from_provider_and_send_to_telnyx(
            websocket, voice_session, log, greeting_triggered, stream_id_holder, interruption_event
        )
    )

    try:
        # Wait for either task to complete or fail
        done, pending = await asyncio.wait(
            [send_task, recv_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Log which task completed
        for task in done:
            if task == send_task:
                log.info("telnyx_receive_task_completed")
            else:
                log.info("provider_receive_task_completed")

        # Cancel remaining tasks gracefully
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # Check for exceptions in completed tasks
        for task in done:
            exc = task.exception()
            if exc:
                log.error(
                    "relay_task_failed",
                    task="telnyx_receive" if task == send_task else "provider_receive",
                    error=str(exc),
                )

    except asyncio.CancelledError:
        log.info("relay_cancelled")
        # Cancel both tasks
        send_task.cancel()
        recv_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(send_task, recv_task)
    except Exception as e:
        log.exception("relay_error", error=str(e))


async def _receive_from_telnyx_and_send_to_provider(  # noqa: PLR0912, PLR0915
    websocket: WebSocket,
    voice_session: VoiceSessionType,
    log: Any,
    greeting_triggered: asyncio.Event,
    stream_id_holder: dict[str, str],
    *,
    is_outbound: bool = False,
    stream_already_started: bool = False,
) -> None:
    """Receive audio from Telnyx and send to voice provider.

    Telnyx sends JSON messages with the following format:
    - {"event": "start", "stream_id": "...", "start": {"call_control_id": "..."}}
    - {"event": "media", "media": {"payload": "<base64-audio>"}}
    - {"event": "stop"}

    Args:
        websocket: Telnyx WebSocket connection
        voice_session: Voice provider session (OpenAI or Grok)
        log: Logger instance
        greeting_triggered: Event to signal when greeting has been triggered
        stream_id_holder: Dict to store stream_id for use in outbound messages
        is_outbound: If True, this is an outbound call and the AI uses an outbound opener
        stream_already_started: If True, Phase 1 gate already consumed the start event
    """
    import json

    stream_started = stream_already_started
    audio_chunks_received = 0
    total_audio_bytes = 0
    start_time = time.time()

    # If Phase 1 gate already consumed the start event, trigger greeting immediately
    if stream_already_started:
        log.info("stream_already_started_from_phase1_gate", triggering_greeting=True)
        await asyncio.sleep(0.3)
        try:
            await voice_session.trigger_initial_response(is_outbound=is_outbound)
            greeting_triggered.set()
            log.info("greeting_triggered_after_phase1_gate")
        except Exception as e:
            log.exception("trigger_initial_response_failed_phase2", error=str(e))
            raise

    # Heartbeat watchdog (idle-timeout only — no pings on this socket): stashed
    # on the websocket scope by ``voice_stream_bridge`` so each Telnyx frame
    # resets the inactivity clock.
    heartbeat = websocket.scope.get("voice_heartbeat")

    try:
        while True:
            # Receive JSON message from Telnyx
            raw_data = await websocket.receive_text()
            if heartbeat is not None:
                heartbeat.mark_activity()

            try:
                data = json.loads(raw_data)
                event = data.get("event", "")

                if event == "start":
                    # Stream has started - Telnyx is ready to send/receive audio
                    stream_id = data.get("stream_id", "")
                    start_info = data.get("start", {})
                    call_control_id = start_info.get("call_control_id", "")
                    media_format = start_info.get("media_format", {})
                    stream_started = True

                    # Store stream_id for use in outbound messages
                    stream_id_holder["stream_id"] = stream_id

                    log.info(
                        "========== TELNYX STREAM STARTED ==========",
                        stream_id=stream_id,
                        call_control_id=call_control_id,
                        encoding=media_format.get("encoding", "unknown"),
                        sample_rate=media_format.get("sample_rate", "unknown"),
                        channels=media_format.get("channels", "unknown"),
                        full_start_info=start_info,
                        stream_id_stored=True,
                    )

                    # Trigger the initial assistant response once Telnyx is ready.
                    # Outbound calls use the provider's outbound opener prompt.
                    ws_status = "unknown"
                    if hasattr(voice_session, "is_connected"):
                        ws_status = str(voice_session.is_connected())
                    log.info(
                        "triggering_initial_greeting",
                        voice_session_connected=ws_status,
                        stream_id=stream_id,
                        is_outbound=is_outbound,
                    )

                    # Wait for Telnyx to be fully ready to play audio
                    # This prevents the first few hundred ms of audio from being cut off
                    await asyncio.sleep(0.3)

                    try:
                        await voice_session.trigger_initial_response(is_outbound=is_outbound)
                        greeting_triggered.set()
                        log.info(
                            "initial_greeting_triggered_successfully",
                            greeting_event_set=True,
                            stream_id=stream_id,
                            is_outbound=is_outbound,
                        )
                    except Exception as e:
                        log.exception(
                            "trigger_initial_response_failed",
                            error=str(e),
                            error_type=type(e).__name__,
                        )
                        raise

                elif event == "media" and stream_started:
                    # Audio data received from caller
                    media = data.get("media", {})
                    payload = media.get("payload", "")
                    timestamp = media.get("timestamp", "")
                    chunk_num = media.get("chunk", "")

                    if payload:
                        # Decode base64 μ-law audio (8kHz)
                        audio_mulaw = base64.b64decode(payload)
                        audio_chunks_received += 1
                        total_audio_bytes += len(audio_mulaw)

                        # Check if OpenAI with g711_ulaw - send directly, no conversion
                        is_openai_ulaw = isinstance(voice_session, VoiceAgentSession)
                        if is_openai_ulaw:
                            # OpenAI expects g711_ulaw - send directly
                            await voice_session.send_audio_chunk(audio_mulaw)
                        else:
                            # Grok expects PCM16 24kHz - convert
                            audio_pcm = convert_telnyx_to_openai(audio_mulaw, log)
                            await voice_session.send_audio_chunk(audio_pcm)

                        # Log periodically (every 50 chunks = ~1 second of audio)
                        if audio_chunks_received % 50 == 0:
                            elapsed = time.time() - start_time
                            log.debug(
                                "audio_relay_stats",
                                direction="telnyx_to_provider",
                                chunks=audio_chunks_received,
                                total_bytes=total_audio_bytes,
                                elapsed_secs=round(elapsed, 1),
                                timestamp=timestamp,
                                chunk=chunk_num,
                                no_conversion=is_openai_ulaw,
                            )

                elif event == "stop":
                    elapsed = time.time() - start_time
                    log.info(
                        "telnyx_stream_stopped",
                        total_chunks=audio_chunks_received,
                        total_bytes=total_audio_bytes,
                        duration_secs=round(elapsed, 1),
                    )
                    break

                elif event == "error":
                    error_msg = data.get("error", {}).get("message", "unknown")
                    log.error("telnyx_stream_error", error=error_msg)
                    break

                else:
                    log.debug("telnyx_unknown_event", telnyx_event=event)

            except json.JSONDecodeError as e:
                log.warning(
                    "telnyx_invalid_json",
                    error=str(e),
                    raw_data_preview=raw_data[:100] if raw_data else "empty",
                )
            except Exception as e:
                log.exception(
                    "telnyx_audio_processing_error",
                    error=str(e),
                    event=data.get("event", "unknown") if "data" in dir() else "unknown",
                )

    except WebSocketDisconnect:
        elapsed = time.time() - start_time
        log.info(
            "telnyx_websocket_disconnected",
            total_chunks=audio_chunks_received,
            duration_secs=round(elapsed, 1),
        )
    except asyncio.CancelledError:
        log.info("telnyx_receive_cancelled")
        raise
    except Exception as e:
        log.exception("receive_from_telnyx_error", error=str(e))


async def _receive_from_provider_and_send_to_telnyx(  # noqa: PLR0912, PLR0915
    websocket: WebSocket,
    voice_session: VoiceSessionType,
    log: Any,
    greeting_triggered: asyncio.Event,
    stream_id_holder: dict[str, str],
    interruption_event: asyncio.Event | None = None,
) -> None:
    """Receive audio from voice provider and send to Telnyx.

    Sends audio in Telnyx's expected JSON format:
    {"event": "media", "stream_id": "...", "media": {"payload": "<base64-audio>"}}

    IMPORTANT: Telnyx requires audio chunks to be 20ms-30s in duration.
    At 8kHz μ-law, 20ms = 160 bytes. We buffer audio until we have enough.

    NOTE: ElevenLabs outputs ulaw_8000 directly - no conversion needed!
    OpenAI/Grok output PCM16 24kHz which must be converted.

    Args:
        websocket: Telnyx WebSocket connection
        voice_session: Voice provider session (OpenAI, Grok, or ElevenLabs)
        log: Logger instance
        greeting_triggered: Event to wait for before sending audio
        stream_id_holder: Dict containing stream_id from Telnyx start event
        interruption_event: Event signaling user interruption (barge-in)
    """
    import json

    audio_chunks_sent = 0
    total_audio_bytes = 0
    start_time = time.time()
    first_audio_time: float | None = None

    # Buffer for accumulating audio until we have enough for Telnyx
    # Telnyx requires minimum 20ms chunks (160 bytes at 8kHz μ-law)
    audio_buffer = bytearray()

    async def send_audio_to_telnyx(audio_data: bytes) -> None:
        """Send audio chunk to Telnyx via WebSocket."""
        nonlocal audio_chunks_sent, total_audio_bytes

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        # Telnyx format: NO stream_id needed (unlike Twilio)
        message = json.dumps(
            {
                "event": "media",
                "media": {"payload": audio_b64},
            }
        )
        await websocket.send_text(message)

        audio_chunks_sent += 1
        total_audio_bytes += len(audio_data)

        # Log first few chunks for debugging
        if audio_chunks_sent <= 3:
            log.info(
                "sent_audio_to_telnyx",
                chunk_num=audio_chunks_sent,
                bytes_sent=len(audio_data),
                payload_length=len(audio_b64),
                first_bytes_hex=audio_data[:10].hex() if audio_data else "empty",
            )

    def _check_ws_connected() -> str:
        if hasattr(voice_session, "is_connected"):
            return str(voice_session.is_connected())
        return "unknown"

    try:
        # Wait for greeting to be triggered before sending audio
        # This ensures the stream is ready
        log.info(
            "waiting_for_greeting_trigger",
            timeout_secs=10.0,
            voice_session_connected=_check_ws_connected(),
        )
        await asyncio.wait_for(greeting_triggered.wait(), timeout=10.0)
        log.info(
            "greeting_triggered_starting_audio_relay",
            voice_session_type=type(voice_session).__name__,
        )

        # Check if ElevenLabs - it outputs ulaw_8000 directly (no conversion needed)
        is_elevenlabs = isinstance(voice_session, ElevenLabsVoiceAgentSession)

        log.info(
            "starting_audio_stream_receive",
            is_elevenlabs=is_elevenlabs,
            voice_session_connected=_check_ws_connected(),
        )

        # Check if this is OpenAI with g711_ulaw output (no conversion needed)
        is_openai_ulaw = isinstance(voice_session, VoiceAgentSession)

        async for audio_chunk in voice_session.receive_audio_stream():
            if first_audio_time is None:
                first_audio_time = time.time()
                latency = first_audio_time - start_time
                log.info(
                    "========== FIRST AUDIO FROM AI PROVIDER ==========",
                    latency_secs=round(latency, 2),
                    audio_bytes=len(audio_chunk),
                    is_elevenlabs=is_elevenlabs,
                    is_openai_ulaw=is_openai_ulaw,
                    chunk_preview_hex=audio_chunk[:20].hex() if audio_chunk else "empty",
                )

            try:
                if is_elevenlabs or is_openai_ulaw:
                    # ElevenLabs and OpenAI (g711_ulaw) output μ-law directly - no conversion!
                    audio_mulaw = audio_chunk
                else:
                    # Grok outputs PCM16 24kHz - convert to μ-law 8kHz for Telnyx
                    audio_mulaw = convert_openai_to_telnyx(audio_chunk, log)

                # Check for interruption - clear buffer and skip sending
                if interruption_event and interruption_event.is_set():
                    audio_buffer.clear()
                    interruption_event.clear()
                    log.info("audio_buffer_cleared_on_interruption")
                    continue

                # Add to buffer
                audio_buffer.extend(audio_mulaw)

                # Send chunks when we have at least the minimum size
                # Send in 160-byte chunks (20ms) for optimal latency
                while len(audio_buffer) >= TELNYX_MIN_CHUNK_BYTES:
                    chunk = bytes(audio_buffer[:TELNYX_MIN_CHUNK_BYTES])
                    del audio_buffer[:TELNYX_MIN_CHUNK_BYTES]
                    await send_audio_to_telnyx(chunk)

                # Log periodically
                if audio_chunks_sent % 50 == 0 and audio_chunks_sent > 0:
                    elapsed = time.time() - start_time
                    log.debug(
                        "audio_relay_stats",
                        direction="provider_to_telnyx",
                        chunks=audio_chunks_sent,
                        total_bytes=total_audio_bytes,
                        buffer_size=len(audio_buffer),
                        elapsed_secs=round(elapsed, 1),
                    )

            except Exception as e:
                log.exception(
                    "provider_audio_conversion_error",
                    error=str(e),
                    audio_bytes=len(audio_chunk),
                )

        # Flush any remaining audio in the buffer
        if audio_buffer:
            log.debug("flushing_audio_buffer", remaining_bytes=len(audio_buffer))
            await send_audio_to_telnyx(bytes(audio_buffer))

    except TimeoutError:
        log.error("greeting_trigger_timeout", timeout_secs=10)
    except WebSocketDisconnect:
        elapsed = time.time() - start_time
        log.info(
            "telnyx_websocket_disconnected_while_sending",
            total_chunks=audio_chunks_sent,
            duration_secs=round(elapsed, 1),
        )
    except asyncio.CancelledError:
        log.info("provider_receive_cancelled")
        raise
    except Exception as e:
        log.exception(
            "receive_from_provider_error",
            error=str(e),
            chunks_sent=audio_chunks_sent,
        )
