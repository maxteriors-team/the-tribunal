"""Tests for app/websockets/voice_bridge.py.

The voice bridge is the entry point that wires together Telnyx media-stream
WebSockets and the upstream voice provider (OpenAI Realtime, Grok, or
ElevenLabs). The endpoint itself is heavily coupled to the database, the
connection-limit primitives, and async background tasks, so we exercise the
pieces independently:

- Pure helpers (`_safe_headers`, transcript/duration/prompt-version writers).
- `_setup_voice_session` configures the session and wires the tool callback
  for sessions that support tools.
- Codec round-trip across `convert_telnyx_to_openai` /
  `convert_openai_to_telnyx` (the bridge's hot path).
- `_relay_audio` and its two child tasks against in-memory fakes.
- `_voice_stream_bridge_body` for happy-path, OpenAI/session creation failure,
  ElevenLabs connect failure, normal disconnect, and abnormal disconnect.

Each test mocks the upstream provider clients — no real network. Database
writes are intercepted by patching `AsyncSessionLocal` at the call site.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocketDisconnect, status

from app.services.ai.elevenlabs_voice_agent import ElevenLabsVoiceAgentSession
from app.services.ai.grok import GrokVoiceAgentSession
from app.services.ai.voice_agent import VoiceAgentSession
from app.services.audio import (
    TELNYX_MIN_CHUNK_BYTES,
    convert_openai_to_telnyx,
    convert_telnyx_to_openai,
)
from app.websockets import voice_bridge as vb

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAudioIterator:
    """An async iterator over a list of audio chunks for relay tests."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._iter()

    async def _iter(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            await asyncio.sleep(0)
            yield chunk


def _make_voice_session(
    session_cls: type[Any] = VoiceAgentSession,
    *,
    audio_chunks: list[bytes] | None = None,
    transcript_json: str | None = None,
    connect_result: bool = True,
) -> MagicMock:
    """Build a MagicMock that ``isinstance`` matches the requested class."""

    session = MagicMock(spec=session_cls)
    # Make isinstance() checks pass — spec already covers this, but we need
    # __class__ to match for the bridge's runtime type dispatch.
    session.__class__ = session_cls
    session.connect = AsyncMock(return_value=connect_result)
    session.disconnect = AsyncMock()
    session.configure_session = AsyncMock()
    session.inject_context = AsyncMock()
    session.send_audio_chunk = AsyncMock()
    session.trigger_initial_response = AsyncMock()
    session.set_tool_callback = MagicMock()
    session.set_interruption_event = MagicMock()
    session.enable_ivr_detection = MagicMock()
    session.is_connected = MagicMock(return_value=True)
    session.get_transcript_json = MagicMock(return_value=transcript_json)
    session.receive_audio_stream = MagicMock(return_value=_FakeAudioIterator(audio_chunks or []))
    return session


def _make_agent(
    *,
    voice_provider: str = "openai",
    enable_ivr: bool = False,
    initial_greeting: str | None = "Hi there!",
) -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.uuid4()
    agent.name = "Test Agent"
    agent.voice_provider = voice_provider
    agent.voice_id = "alloy"
    agent.system_prompt = "You are helpful."
    agent.temperature = 0.7
    agent.turn_detection_mode = "server_vad"
    agent.turn_detection_threshold = 0.5
    agent.silence_duration_ms = 700
    agent.initial_greeting = initial_greeting
    agent.calcom_event_type_id = None
    agent.enable_ivr_navigation = enable_ivr
    agent.ivr_navigation_goal = None
    agent.ivr_loop_threshold = 2
    agent.ivr_post_dtmf_cooldown_ms = 3000
    agent.ivr_silence_duration_ms = 3000
    agent.ivr_menu_buffer_silence_ms = 2000
    return agent


def _make_websocket() -> MagicMock:
    """Build a WebSocket double sufficient for the relay handlers."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    ws.send_text = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.scope = {}
    ws.client = MagicMock()
    ws.client.host = "127.0.0.1"
    ws.client.port = 12345
    ws.headers = {}
    return ws


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestSafeHeaders:
    def test_redacts_sensitive_keys_case_insensitively(self) -> None:
        headers = {
            "Authorization": "Bearer secret",
            "Cookie": "session=abc",
            "X-API-Key": "key",
            "Proxy-Authorization": "Basic xyz",
            "Content-Type": "application/json",
        }
        safe = vb._safe_headers(headers)
        assert safe["Authorization"] == "***"
        assert safe["Cookie"] == "***"
        assert safe["X-API-Key"] == "***"
        assert safe["Proxy-Authorization"] == "***"
        assert safe["Content-Type"] == "application/json"

    def test_passes_through_when_no_sensitive(self) -> None:
        assert vb._safe_headers({"X-Other": "v"}) == {"X-Other": "v"}


# ---------------------------------------------------------------------------
# Codec round-trip — the bridge's audio hot path
# ---------------------------------------------------------------------------


class TestCodecRoundTrip:
    """Pin the PCM<->µ-law conversions actually wired into the bridge."""

    def test_telnyx_to_openai_returns_three_times_bytes(self) -> None:
        # 160 bytes of µ-law @ 8kHz = 20ms = 160 samples after decode = 480
        # samples after upsampling = 960 bytes of PCM16 @ 24kHz.
        mulaw = b"\x7f" * 160
        pcm = convert_telnyx_to_openai(mulaw)
        assert len(pcm) == 960

    def test_openai_to_telnyx_returns_one_third_bytes(self) -> None:
        # 960 bytes of PCM16 @ 24kHz = 480 samples = 160 samples @ 8kHz
        # after downsampling = 160 bytes of µ-law.
        pcm = b"\x00\x00" * 480
        mulaw = convert_openai_to_telnyx(pcm)
        assert len(mulaw) == 160

    def test_round_trip_preserves_length(self) -> None:
        mulaw_in = bytes(range(160))
        pcm = convert_telnyx_to_openai(mulaw_in)
        mulaw_out = convert_openai_to_telnyx(pcm)
        assert len(mulaw_out) == len(mulaw_in)

    def test_empty_input_safe(self) -> None:
        assert convert_telnyx_to_openai(b"") == b""
        assert convert_openai_to_telnyx(b"") == b""


# ---------------------------------------------------------------------------
# Database wrappers
# ---------------------------------------------------------------------------


def _patch_async_session(execute_returns: Any = None) -> Any:
    """Patch AsyncSessionLocal used inside voice_bridge."""

    db = AsyncMock()
    db.execute = AsyncMock(return_value=execute_returns or MagicMock(rowcount=1))
    db.commit = AsyncMock()
    db.__aenter__ = AsyncMock(return_value=db)
    db.__aexit__ = AsyncMock(return_value=False)

    session_local = MagicMock(return_value=db)
    return patch.object(vb, "AsyncSessionLocal", session_local), db


class TestDatabaseWrappers:
    async def test_save_call_duration_executes_update_and_commits(self) -> None:
        ctx, db = _patch_async_session()
        log = MagicMock()
        with ctx:
            await vb._save_call_duration("call-1", 42, log)
        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()
        log.info.assert_called()

    async def test_stamp_prompt_version_uses_uuid(self) -> None:
        ctx, db = _patch_async_session(MagicMock(rowcount=1))
        log = MagicMock()
        version_id = str(uuid.uuid4())
        with ctx:
            await vb._stamp_prompt_version_on_message("call-1", version_id, log)
        db.execute.assert_awaited_once()
        db.commit.assert_awaited_once()

    async def test_stamp_prompt_version_swallows_exception(self) -> None:
        # Bad UUID — function should log but not raise (call must continue).
        log = MagicMock()
        await vb._stamp_prompt_version_on_message("call-1", "not-a-uuid", log)
        log.exception.assert_called_once()

    async def test_save_call_transcript_wrapper_delegates(self) -> None:
        log = MagicMock()
        with patch.object(vb, "save_call_transcript", new=AsyncMock()) as mock_save:
            await vb._save_call_transcript_wrapper("call-1", '{"a": 1}', log)
            mock_save.assert_awaited_once_with("call-1", '{"a": 1}', log)

    async def test_lookup_call_context_wrapper_returns_tuple(self) -> None:
        fake_context = MagicMock()
        fake_context.agent = "AGENT"
        fake_context.contact_info = {"name": "n"}
        fake_context.offer_info = {"name": "o"}
        fake_context.timezone = "UTC"
        fake_context.prompt_version_id = "pv-1"

        with patch.object(vb, "lookup_call_context", new=AsyncMock(return_value=fake_context)):
            result = await vb._lookup_call_context_wrapper("call-1", MagicMock())

        assert result == ("AGENT", {"name": "n"}, {"name": "o"}, "UTC", "pv-1")


# ---------------------------------------------------------------------------
# _setup_voice_session — tool callback dispatch + configuration
# ---------------------------------------------------------------------------


class TestSetupVoiceSession:
    async def test_openai_session_receives_tool_callback(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        agent = _make_agent(voice_provider="openai")
        log = MagicMock()

        with patch.object(vb, "create_tool_callback", return_value="CALLBACK") as factory:
            await vb._setup_voice_session(
                session, agent, None, None, "UTC", log, call_control_id="cc-1"
            )

        factory.assert_called_once()
        session.set_tool_callback.assert_called_once_with("CALLBACK")
        session.configure_session.assert_awaited_once()

    async def test_grok_session_receives_tool_callback(self) -> None:
        session = _make_voice_session(GrokVoiceAgentSession)
        agent = _make_agent(voice_provider="grok")
        contact = {"name": "Alice"}
        log = MagicMock()

        with patch.object(vb, "create_tool_callback", return_value="CALLBACK") as factory:
            await vb._setup_voice_session(
                session,
                agent,
                contact,
                None,
                "UTC",
                log,
                call_control_id="cc-1",
                is_outbound=False,
            )

        factory.assert_called_once()
        session.set_tool_callback.assert_called_once_with("CALLBACK")

    async def test_elevenlabs_session_receives_tool_callback(self) -> None:
        session = _make_voice_session(ElevenLabsVoiceAgentSession)
        agent = _make_agent(voice_provider="elevenlabs")
        log = MagicMock()

        with patch.object(vb, "create_tool_callback", return_value="CALLBACK"):
            await vb._setup_voice_session(
                session,
                agent,
                None,
                None,
                "UTC",
                log,
                call_control_id="cc-1",
            )

        session.set_tool_callback.assert_called_once_with("CALLBACK")
        # ElevenLabs is not Grok — IVR detection must NOT be enabled even when
        # the agent has the flag on.
        session.enable_ivr_detection.assert_not_called()

    async def test_grok_outbound_enables_ivr_when_agent_opted_in(self) -> None:
        session = _make_voice_session(GrokVoiceAgentSession)
        agent = _make_agent(voice_provider="grok", enable_ivr=True)
        agent.ivr_navigation_goal = "Reach the dentist"
        log = MagicMock()

        with patch.object(vb, "create_tool_callback", return_value="cb"):
            await vb._setup_voice_session(session, agent, None, None, "UTC", log, is_outbound=True)

        session.enable_ivr_detection.assert_called_once()
        kwargs = session.enable_ivr_detection.call_args.kwargs
        assert kwargs["navigation_goal"] == "Reach the dentist"
        assert kwargs["loop_threshold"] == 2

    async def test_grok_outbound_skips_ivr_when_phase1_handled(self) -> None:
        session = _make_voice_session(GrokVoiceAgentSession)
        agent = _make_agent(voice_provider="grok", enable_ivr=True)
        log = MagicMock()

        with patch.object(vb, "create_tool_callback", return_value="cb"):
            await vb._setup_voice_session(
                session,
                agent,
                None,
                None,
                "UTC",
                log,
                is_outbound=True,
                skip_ivr_detection=True,
            )

        session.enable_ivr_detection.assert_not_called()

    async def test_inject_context_called_with_contact_and_offer(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        agent = _make_agent()
        log = MagicMock()
        contact = {"name": "A"}
        offer = {"name": "Premium"}

        await vb._setup_voice_session(
            session,
            agent,
            contact,
            offer,
            "UTC",
            log,
            is_outbound=False,
        )

        session.inject_context.assert_awaited_once_with(
            contact_info=contact, offer_info=offer, is_outbound=False
        )

    async def test_no_inject_context_when_no_contact_or_offer(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        agent = _make_agent()
        log = MagicMock()

        await vb._setup_voice_session(session, agent, None, None, "UTC", log)

        session.inject_context.assert_not_called()


# ---------------------------------------------------------------------------
# _receive_from_telnyx_and_send_to_provider
# ---------------------------------------------------------------------------


class TestReceiveFromTelnyx:
    async def test_start_event_triggers_greeting_inbound_openai(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        ws.receive_text.side_effect = [
            json.dumps(
                {
                    "event": "start",
                    "stream_id": "s1",
                    "start": {
                        "call_control_id": "c1",
                        "media_format": {
                            "encoding": "PCMU",
                            "sample_rate": 8000,
                            "channels": 1,
                        },
                    },
                }
            ),
            json.dumps({"event": "stop"}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(
            ws, session, log, greeting, holder, is_outbound=False
        )

        assert holder["stream_id"] == "s1"
        session.trigger_initial_response.assert_awaited_once_with(is_outbound=False)
        assert greeting.is_set()

    async def test_start_event_triggers_greeting_outbound_openai(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        ws.receive_text.side_effect = [
            json.dumps(
                {
                    "event": "start",
                    "stream_id": "s1",
                    "start": {"call_control_id": "c1"},
                }
            ),
            json.dumps({"event": "stop"}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(
            ws, session, log, greeting, holder, is_outbound=True
        )

        # Outbound on OpenAI: greeting IS triggered, with is_outbound passed
        # through so the session emits the outbound opener prompt.
        session.trigger_initial_response.assert_awaited_once_with(is_outbound=True)
        assert greeting.is_set()

    async def test_start_event_triggers_greeting_outbound_grok(self) -> None:
        session = _make_voice_session(GrokVoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        ws.receive_text.side_effect = [
            json.dumps(
                {
                    "event": "start",
                    "stream_id": "s1",
                    "start": {"call_control_id": "c1"},
                }
            ),
            json.dumps({"event": "stop"}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(
            ws, session, log, greeting, holder, is_outbound=True
        )

        # Grok/ElevenLabs always get is_outbound passed through.
        session.trigger_initial_response.assert_awaited_once_with(is_outbound=True)

    async def test_media_event_sends_mulaw_directly_for_openai(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        audio = b"\x7f" * 160
        payload = base64.b64encode(audio).decode()

        ws.receive_text.side_effect = [
            json.dumps(
                {
                    "event": "start",
                    "stream_id": "s",
                    "start": {"call_control_id": "c"},
                }
            ),
            json.dumps({"event": "media", "media": {"payload": payload, "chunk": 1}}),
            json.dumps({"event": "stop"}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(
            ws, session, log, greeting, holder, is_outbound=False
        )

        # OpenAI uses g711_ulaw — no conversion, raw µ-law goes through.
        session.send_audio_chunk.assert_awaited_once_with(audio)

    async def test_media_event_converts_for_grok(self) -> None:
        session = _make_voice_session(GrokVoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        audio = b"\x7f" * 160
        payload = base64.b64encode(audio).decode()

        ws.receive_text.side_effect = [
            json.dumps(
                {
                    "event": "start",
                    "stream_id": "s",
                    "start": {"call_control_id": "c"},
                }
            ),
            json.dumps({"event": "media", "media": {"payload": payload}}),
            json.dumps({"event": "stop"}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(
            ws, session, log, greeting, holder, is_outbound=False
        )

        # Grok path runs through convert_telnyx_to_openai → 3x size.
        session.send_audio_chunk.assert_awaited_once()
        sent = session.send_audio_chunk.await_args.args[0]
        assert len(sent) == len(audio) * 6  # 160 µ-law → 320 PCM 8k → 960 PCM 24k = 6x

    async def test_invalid_json_continues_loop(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        ws.receive_text.side_effect = [
            "not json{",
            json.dumps({"event": "stop"}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(ws, session, log, greeting, holder)

        # Logged but didn't crash.
        log.warning.assert_called()

    async def test_websocket_disconnect_handled_cleanly(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        ws.receive_text.side_effect = WebSocketDisconnect(code=1000)

        await vb._receive_from_telnyx_and_send_to_provider(ws, session, log, greeting, holder)

        # The handler swallows clean disconnects, but logs them.
        log.info.assert_any_call(
            "telnyx_websocket_disconnected",
            total_chunks=0,
            duration_secs=pytest.approx(0.0, abs=0.5),
        )

    async def test_phase1_gate_already_started_triggers_immediate_greeting(
        self,
    ) -> None:
        session = _make_voice_session(GrokVoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        # When stream_already_started=True the handler greets first, then
        # waits for events. We feed only a stop so the loop exits.
        ws.receive_text.side_effect = [json.dumps({"event": "stop"})]

        await vb._receive_from_telnyx_and_send_to_provider(
            ws,
            session,
            log,
            greeting,
            holder,
            is_outbound=True,
            stream_already_started=True,
        )

        session.trigger_initial_response.assert_awaited_once_with(is_outbound=True)
        assert greeting.is_set()

    async def test_error_event_breaks_loop(self) -> None:
        session = _make_voice_session(VoiceAgentSession)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        holder: dict[str, str] = {}

        ws.receive_text.side_effect = [
            json.dumps({"event": "error", "error": {"message": "stream broke"}}),
        ]

        await vb._receive_from_telnyx_and_send_to_provider(ws, session, log, greeting, holder)

        log.error.assert_called()


# ---------------------------------------------------------------------------
# _receive_from_provider_and_send_to_telnyx
# ---------------------------------------------------------------------------


class TestReceiveFromProvider:
    async def test_buffers_and_sends_minimum_chunks(self) -> None:
        # ElevenLabs path — bytes are already µ-law, no conversion.
        chunks = [b"\xaa" * 80, b"\xbb" * 80, b"\xcc" * 40]
        session = _make_voice_session(ElevenLabsVoiceAgentSession, audio_chunks=chunks)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        greeting.set()
        holder = {"stream_id": "s1"}

        await vb._receive_from_provider_and_send_to_telnyx(ws, session, log, greeting, holder)

        # We buffer until we hit 160 bytes per chunk, plus a flush for the
        # remaining 40 bytes at the end → 2 sends total.
        assert ws.send_text.await_count == 2

        # Decode the first frame and verify it's our µ-law payload.
        first_msg = json.loads(ws.send_text.await_args_list[0].args[0])
        assert first_msg["event"] == "media"
        decoded = base64.b64decode(first_msg["media"]["payload"])
        assert len(decoded) == TELNYX_MIN_CHUNK_BYTES

    async def test_grok_path_converts_pcm_to_mulaw(self) -> None:
        # 960 bytes of PCM @ 24kHz → 160 bytes µ-law after convert.
        pcm_chunk = b"\x00\x00" * 480
        session = _make_voice_session(GrokVoiceAgentSession, audio_chunks=[pcm_chunk])
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        greeting.set()

        await vb._receive_from_provider_and_send_to_telnyx(
            ws, session, log, greeting, {"stream_id": "s1"}
        )

        assert ws.send_text.await_count == 1
        msg = json.loads(ws.send_text.await_args.args[0])
        assert len(base64.b64decode(msg["media"]["payload"])) == TELNYX_MIN_CHUNK_BYTES

    async def test_interruption_clears_buffer(self) -> None:
        # Feed two big chunks; flip interruption after the first.
        chunks = [b"\xaa" * 160, b"\xbb" * 160]
        session = _make_voice_session(ElevenLabsVoiceAgentSession, audio_chunks=chunks)
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()
        greeting.set()

        interruption = asyncio.Event()
        interruption.set()  # set BEFORE iteration starts

        await vb._receive_from_provider_and_send_to_telnyx(
            ws,
            session,
            log,
            greeting,
            {"stream_id": "s1"},
            interruption_event=interruption,
        )

        # First chunk: interruption set → buffer cleared, nothing sent.
        # Second chunk: interruption was cleared above, so it flows normally.
        # The interruption flag is cleared after the first hit.
        assert ws.send_text.await_count == 1

    async def test_greeting_timeout_does_not_send(self) -> None:
        session = _make_voice_session(VoiceAgentSession, audio_chunks=[])
        ws = _make_websocket()
        log = MagicMock()
        greeting = asyncio.Event()  # never set

        # Patch wait_for to short-circuit the 10s timeout for this test.
        original_wait_for = asyncio.wait_for

        async def fast_wait_for(coro: Any, timeout: float) -> Any:
            return await original_wait_for(coro, 0.05)

        with patch("asyncio.wait_for", new=fast_wait_for):
            await vb._receive_from_provider_and_send_to_telnyx(ws, session, log, greeting, {})

        log.error.assert_called_with("greeting_trigger_timeout", timeout_secs=10)
        ws.send_text.assert_not_called()

    async def test_disconnect_during_send_is_swallowed(self) -> None:
        # The receive_audio_stream emits one chunk then send raises.
        # The inner per-chunk try/except catches the disconnect as a
        # provider_audio_conversion_error rather than the outer disconnect
        # handler, so the function returns cleanly without bubbling.
        chunks = [b"\xaa" * 160]
        session = _make_voice_session(ElevenLabsVoiceAgentSession, audio_chunks=chunks)
        ws = _make_websocket()
        ws.send_text.side_effect = WebSocketDisconnect(code=1001)
        log = MagicMock()
        greeting = asyncio.Event()
        greeting.set()

        # Must not raise.
        await vb._receive_from_provider_and_send_to_telnyx(
            ws, session, log, greeting, {"stream_id": "s1"}
        )

        # The inner per-chunk handler logged the error and the iterator drained.
        log.exception.assert_called()
        assert log.exception.call_args.args[0] == "provider_audio_conversion_error"


# ---------------------------------------------------------------------------
# _relay_audio
# ---------------------------------------------------------------------------


class TestRelayAudio:
    async def test_returns_when_telnyx_side_finishes(self) -> None:
        session = _make_voice_session(VoiceAgentSession, audio_chunks=[])
        ws = _make_websocket()
        log = MagicMock()

        # Telnyx side completes immediately after a stop event.
        ws.receive_text.side_effect = [
            json.dumps({"event": "start", "stream_id": "s", "start": {"call_control_id": "c"}}),
            json.dumps({"event": "stop"}),
        ]

        await vb._relay_audio(ws, session, log, is_outbound=False)

        # When the Telnyx side wins the wait(), the provider task is cancelled.
        log.info.assert_any_call("telnyx_receive_task_completed")

    async def test_sets_interruption_event_on_session(self) -> None:
        session = _make_voice_session(GrokVoiceAgentSession, audio_chunks=[])
        ws = _make_websocket()
        log = MagicMock()

        ws.receive_text.side_effect = [
            json.dumps({"event": "start", "stream_id": "s", "start": {"call_control_id": "c"}}),
            json.dumps({"event": "stop"}),
        ]

        await vb._relay_audio(ws, session, log)
        session.set_interruption_event.assert_called_once()


# ---------------------------------------------------------------------------
# _voice_stream_bridge_body — top-level flow
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _patch_bridge_db() -> Any:
    """Patch every DB-touching helper so the body runs without a database."""
    with (
        patch.object(vb, "_stamp_prompt_version_on_message", new=AsyncMock()),
        patch.object(vb, "_save_call_duration", new=AsyncMock()),
        patch.object(vb, "_save_call_transcript_wrapper", new=AsyncMock()),
    ):
        yield


class TestVoiceStreamBridgeBody:
    async def test_session_creation_failure_returns_policy_violation(
        self,
    ) -> None:
        ws = _make_websocket()
        log = MagicMock()

        with (
            _patch_bridge_db(),
            patch.object(
                vb,
                "create_workspace_voice_session",
                return_value=(None, "no api key"),
            ),
        ):
            await vb._voice_stream_bridge_body(
                websocket=ws,
                call_id="c1",
                is_outbound=False,
                connection_start=0.0,
                log=log,
                agent=_make_agent(),
                contact_info=None,
                offer_info=None,
                timezone="UTC",
                prompt_version_id=None,
                workspace_id=str(uuid.uuid4()),
            )
        ws.send_json.assert_awaited_with({"error": "no api key"})
        ws.close.assert_awaited()
        # First close is the policy violation.
        codes = [c.kwargs.get("code") for c in ws.close.await_args_list]
        assert status.WS_1008_POLICY_VIOLATION in codes

    async def test_openai_connect_failure_returns_internal_error(self) -> None:
        ws = _make_websocket()
        log = MagicMock()
        session = _make_voice_session(VoiceAgentSession, connect_result=False)

        with (
            _patch_bridge_db(),
            patch.object(vb, "create_workspace_voice_session", return_value=(session, None)),
        ):
            await vb._voice_stream_bridge_body(
                websocket=ws,
                call_id="c1",
                is_outbound=False,
                connection_start=0.0,
                log=log,
                agent=_make_agent(voice_provider="openai"),
                contact_info=None,
                offer_info=None,
                timezone="UTC",
                prompt_version_id=None,
                workspace_id=str(uuid.uuid4()),
            )
        ws.send_json.assert_awaited()
        err = ws.send_json.await_args_list[0].args[0]
        assert "Failed to connect" in err["error"]
        # disconnect() is called inside the finally even after connect failure.
        session.disconnect.assert_awaited()

    async def test_elevenlabs_connect_failure_returns_internal_error(self) -> None:
        ws = _make_websocket()
        log = MagicMock()
        session = _make_voice_session(ElevenLabsVoiceAgentSession, connect_result=False)

        with (
            _patch_bridge_db(),
            patch.object(vb, "create_workspace_voice_session", return_value=(session, None)),
        ):
            await vb._voice_stream_bridge_body(
                websocket=ws,
                call_id="c1",
                is_outbound=False,
                connection_start=0.0,
                log=log,
                agent=_make_agent(voice_provider="elevenlabs"),
                contact_info=None,
                offer_info=None,
                timezone="UTC",
                prompt_version_id=None,
                workspace_id=str(uuid.uuid4()),
            )
        ws.send_json.assert_awaited()
        codes = [c.kwargs.get("code") for c in ws.close.await_args_list]
        assert status.WS_1011_INTERNAL_ERROR in codes

    async def test_normal_disconnect_saves_transcript_and_duration(self) -> None:
        ws = _make_websocket()
        log = MagicMock()
        session = _make_voice_session(
            VoiceAgentSession,
            audio_chunks=[],
            transcript_json='[{"role":"user","text":"hi"}]',
        )

        # The relay's Telnyx side terminates on a stop event.
        ws.receive_text.side_effect = [
            json.dumps(
                {
                    "event": "start",
                    "stream_id": "s",
                    "start": {"call_control_id": "c"},
                }
            ),
            json.dumps({"event": "stop"}),
        ]

        save_transcript = AsyncMock()
        save_duration = AsyncMock()

        with (
            patch.object(vb, "_stamp_prompt_version_on_message", new=AsyncMock()),
            patch.object(vb, "_save_call_duration", new=save_duration),
            patch.object(vb, "_save_call_transcript_wrapper", new=save_transcript),
            patch.object(vb, "create_workspace_voice_session", return_value=(session, None)),
        ):
            await vb._voice_stream_bridge_body(
                websocket=ws,
                call_id="c1",
                is_outbound=False,
                connection_start=0.0,
                log=log,
                agent=_make_agent(voice_provider="openai"),
                contact_info=None,
                offer_info=None,
                timezone="UTC",
                prompt_version_id=None,
                workspace_id=str(uuid.uuid4()),
            )
        save_transcript.assert_awaited_once()
        save_duration.assert_awaited_once()
        session.disconnect.assert_awaited()

    async def test_abnormal_disconnect_still_saves_duration(self) -> None:
        ws = _make_websocket()
        log = MagicMock()
        session = _make_voice_session(VoiceAgentSession, audio_chunks=[])

        # Simulate Telnyx hanging up abruptly mid-stream — the relay raises
        # WebSocketDisconnect which propagates up to the body's except clause.
        ws.receive_text.side_effect = WebSocketDisconnect(code=1006)

        save_duration = AsyncMock()

        with (
            patch.object(vb, "_stamp_prompt_version_on_message", new=AsyncMock()),
            patch.object(vb, "_save_call_duration", new=save_duration),
            patch.object(vb, "_save_call_transcript_wrapper", new=AsyncMock()),
            patch.object(vb, "create_workspace_voice_session", return_value=(session, None)),
        ):
            await vb._voice_stream_bridge_body(
                websocket=ws,
                call_id="c1",
                is_outbound=False,
                connection_start=0.0,
                log=log,
                agent=_make_agent(voice_provider="openai"),
                contact_info=None,
                offer_info=None,
                timezone="UTC",
                prompt_version_id=None,
                workspace_id=str(uuid.uuid4()),
            )
        # Even on abrupt disconnect, finally block records the call.
        save_duration.assert_awaited_once()
        session.disconnect.assert_awaited()

    async def test_stamps_prompt_version_when_provided(self) -> None:
        ws = _make_websocket()
        log = MagicMock()
        session = _make_voice_session(VoiceAgentSession, connect_result=False)
        stamp = AsyncMock()

        with (
            patch.object(vb, "_stamp_prompt_version_on_message", new=stamp),
            patch.object(vb, "_save_call_duration", new=AsyncMock()),
            patch.object(vb, "_save_call_transcript_wrapper", new=AsyncMock()),
            patch.object(vb, "create_workspace_voice_session", return_value=(session, None)),
        ):
            await vb._voice_stream_bridge_body(
                websocket=ws,
                call_id="c1",
                is_outbound=False,
                connection_start=0.0,
                log=log,
                agent=_make_agent(),
                contact_info=None,
                offer_info=None,
                timezone="UTC",
                prompt_version_id="pv-123",
                workspace_id=str(uuid.uuid4()),
            )
        stamp.assert_awaited_once_with("c1", "pv-123", log)
