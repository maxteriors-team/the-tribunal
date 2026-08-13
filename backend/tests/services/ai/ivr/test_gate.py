"""Tests for IVRGate - Phase 1 orchestrator."""

import base64
import json
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.ai.ivr.gate import (
    FIRST_BUFFER_SECONDS,
    NORMAL_BUFFER_SECONDS,
    GateOutcome,
    GateResult,
    IVRGate,
)
from app.services.ai.ivr.types import IVRMode


@pytest.fixture(autouse=True)
def _stub_openai_client() -> Iterator[MagicMock]:
    """Stub ``create_openai_client`` for every test in this module.

    ``IVRGate.__init__`` eagerly constructs a ``WhisperTranscriber`` which
    in turn calls ``create_openai_client()`` and validates credentials. We
    patch the factory so no real OpenAI SDK client is built and no API key
    is required to import/run these tests. Tests still patch
    ``gate._transcriber.transcribe`` for behavior assertions.
    """
    mock_client = MagicMock()
    with patch(
        "app.services.ai.ivr.transcriber.create_openai_client",
        return_value=mock_client,
    ):
        yield mock_client


def _make_start_event(stream_id: str = "test-stream") -> str:
    """Create a Telnyx start event JSON string."""
    return json.dumps(
        {
            "event": "start",
            "stream_id": stream_id,
            "start": {
                "call_control_id": "test-call-id",
                "media_format": {
                    "encoding": "audio/x-mulaw",
                    "sample_rate": 8000,
                    "channels": 1,
                },
            },
        }
    )


def _make_media_event(audio_bytes: bytes) -> str:
    """Create a Telnyx media event JSON string."""
    return json.dumps(
        {
            "event": "media",
            "media": {
                "payload": base64.b64encode(audio_bytes).decode("utf-8"),
                "timestamp": "0",
                "chunk": "1",
            },
        }
    )


def _make_stop_event() -> str:
    """Create a Telnyx stop event JSON string."""
    return json.dumps({"event": "stop"})


def _make_silence(seconds: float) -> bytes:
    """Create mu-law silence audio of given duration."""
    return bytes([0xFF] * int(seconds * 8000))


class TestGateOutcomes:
    """Tests for different gate outcomes."""

    async def test_human_detected(self):
        """Gate should return HUMAN_DETECTED when classifier sees human."""
        gate = IVRGate(call_control_id="test-call")

        # Build enough audio for first buffer (1.5s)
        audio = _make_silence(FIRST_BUFFER_SECONDS)

        ws = AsyncMock()
        ws.receive_text = AsyncMock(
            side_effect=[
                _make_start_event(),
                _make_media_event(audio),
                # After processing, gate will try to read more - we'll timeout
            ]
        )
        ws.send_text = AsyncMock()

        with (
            patch.object(
                gate._transcriber,
                "transcribe",
                return_value="Hello, how can I help you?",
            ),
            patch.object(
                gate._classifier,
                "classify",
                return_value=(IVRMode.CONVERSATION, 0.9),
            ),
        ):
            result = await gate.run(ws)

        assert result.outcome == GateOutcome.HUMAN_DETECTED
        assert len(result.transcript_history) == 1
        assert result.transcript_history[0] == "Hello, how can I help you?"

    async def test_voicemail_detected(self):
        """Gate should return VOICEMAIL_DETECTED when classifier sees voicemail."""
        gate = IVRGate(call_control_id="test-call")

        audio = _make_silence(FIRST_BUFFER_SECONDS)

        ws = AsyncMock()
        ws.receive_text = AsyncMock(
            side_effect=[
                _make_start_event(),
                _make_media_event(audio),
            ]
        )
        ws.send_text = AsyncMock()

        with (
            patch.object(
                gate._transcriber,
                "transcribe",
                return_value="Please leave a message after the beep.",
            ),
            patch.object(
                gate._classifier,
                "classify",
                return_value=(IVRMode.VOICEMAIL, 0.85),
            ),
        ):
            result = await gate.run(ws)

        assert result.outcome == GateOutcome.VOICEMAIL_DETECTED
        assert "leave a message" in result.transcript_history[0]

    async def test_call_dropped(self):
        """Gate should return CALL_DROPPED on stop event."""
        gate = IVRGate(call_control_id="test-call")

        ws = AsyncMock()
        ws.receive_text = AsyncMock(
            side_effect=[
                _make_start_event(),
                _make_stop_event(),
            ]
        )
        ws.send_text = AsyncMock()

        result = await gate.run(ws)

        assert result.outcome == GateOutcome.CALL_DROPPED
        assert result.dtmf_attempts == 0

    async def test_ivr_sends_dtmf(self):
        """Gate should send DTMF when IVR is detected."""
        gate = IVRGate(call_control_id="test-call")

        audio1 = _make_silence(FIRST_BUFFER_SECONDS)
        audio2 = _make_silence(NORMAL_BUFFER_SECONDS)

        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_start_event()
            if call_count == 2:
                return _make_media_event(audio1)
            if call_count == 3:
                # After DTMF + cooldown, send second audio chunk
                return _make_media_event(audio2)
            # After second classification, stop
            return _make_stop_event()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=mock_receive)
        ws.send_text = AsyncMock()

        transcribe_results = iter(
            [
                "Press 1 for sales. Press 2 for support.",
                "Hello, this is the sales team.",
            ]
        )
        classify_results = iter(
            [
                (IVRMode.IVR, 0.9),
                (IVRMode.CONVERSATION, 0.85),
            ]
        )

        with (
            patch.object(
                gate._transcriber,
                "transcribe",
                side_effect=lambda _: next(transcribe_results),
            ),
            patch.object(
                gate._classifier,
                "classify",
                side_effect=lambda _: next(classify_results),
            ),
            patch.object(gate, "_send_dtmf", new_callable=AsyncMock) as mock_dtmf,
            patch("app.services.ai.ivr.gate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await gate.run(ws)

        assert result.outcome == GateOutcome.HUMAN_DETECTED
        assert result.dtmf_attempts == 1
        mock_dtmf.assert_called_once()

    async def test_empty_transcript_continues(self):
        """Empty transcript should continue listening, not exit."""
        gate = IVRGate(call_control_id="test-call")

        audio1 = _make_silence(FIRST_BUFFER_SECONDS)
        audio2 = _make_silence(NORMAL_BUFFER_SECONDS)

        call_count = 0

        async def mock_receive():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_start_event()
            if call_count == 2:
                return _make_media_event(audio1)
            if call_count == 3:
                return _make_media_event(audio2)
            return _make_stop_event()

        ws = AsyncMock()
        ws.receive_text = AsyncMock(side_effect=mock_receive)
        ws.send_text = AsyncMock()

        transcribe_results = iter(["", "Hello speaking"])
        classify_results = iter([(IVRMode.CONVERSATION, 0.8)])

        with (
            patch.object(
                gate._transcriber,
                "transcribe",
                side_effect=lambda _: next(transcribe_results),
            ),
            patch.object(
                gate._classifier,
                "classify",
                side_effect=lambda _: next(classify_results),
            ),
        ):
            result = await gate.run(ws)

        assert result.outcome == GateOutcome.HUMAN_DETECTED
        # Empty transcript should not be in history
        assert "" not in result.transcript_history

    async def test_fallback_ai_on_navigator_exhaustion(self):
        """Gate should return FALLBACK_AI when navigator gives up."""
        gate = IVRGate(
            call_control_id="test-call",
            agent_config={"loop_threshold": 1},  # Very low = max_attempts=4
        )

        audio = _make_silence(FIRST_BUFFER_SECONDS)

        ws = AsyncMock()
        # Keep sending IVR audio
        ws.receive_text = AsyncMock(
            side_effect=[
                _make_start_event(),
                _make_media_event(audio),
            ]
        )
        ws.send_text = AsyncMock()

        with (
            patch.object(gate._transcriber, "transcribe", return_value="Press 1 for sales."),
            patch.object(gate._classifier, "classify", return_value=(IVRMode.IVR, 0.9)),
            patch.object(gate._navigator, "select_digit") as mock_select,
            patch("app.services.ai.ivr.gate.asyncio.sleep", new_callable=AsyncMock),
        ):
            from app.services.ai.ivr.navigator import NavigationAction, NavigationResult

            mock_select.return_value = NavigationResult(
                action=NavigationAction.FALLBACK_AI,
                reason="all digits exhausted",
            )
            result = await gate.run(ws)

        assert result.outcome == GateOutcome.FALLBACK_AI


class TestGateResult:
    """Tests for GateResult dataclass."""

    def test_default_values(self):
        """Default GateResult should have empty lists and zero values."""
        result = GateResult(outcome=GateOutcome.TIMEOUT)
        assert result.transcript_history == []
        assert result.last_transcript == ""
        assert result.duration_seconds == 0.0
        assert result.dtmf_attempts == 0


class TestGateConfig:
    """Tests for IVRGate configuration."""

    def test_default_config(self):
        """Default config should use reasonable defaults."""
        gate = IVRGate(call_control_id="test")
        assert gate._post_dtmf_cooldown == 3.0
        assert gate._navigator.max_attempts == 8  # default loop_threshold=2, *4

    def test_custom_config(self):
        """Custom config should override defaults."""
        gate = IVRGate(
            call_control_id="test",
            agent_config={
                "post_dtmf_cooldown_ms": 5000,
                "loop_threshold": 3,
            },
        )
        assert gate._post_dtmf_cooldown == 5.0
        assert gate._navigator.max_attempts == 12  # 3 * 4

    def test_custom_navigation_goal(self):
        """Navigation goal should be passed to navigator."""
        gate = IVRGate(
            call_control_id="test",
            navigation_goal="Reach the billing department",
        )
        assert gate._navigator.navigation_goal == "Reach the billing department"


class TestGateKeepalive:
    """Tests for keepalive silence frame sending."""

    async def test_keepalive_sends_silence(self):
        """Keepalive should send silence frames to websocket."""
        gate = IVRGate(call_control_id="test")

        ws = AsyncMock()
        send_count = 0

        async def counting_send(msg: str) -> None:
            nonlocal send_count
            send_count += 1
            if send_count >= 3:
                # Simulate connection failure to break the loop
                raise ConnectionError("done")

        ws.send_text = AsyncMock(side_effect=counting_send)

        # _send_keepalive catches CancelledError and breaks on send exceptions
        with patch("app.services.ai.ivr.gate.KEEPALIVE_INTERVAL_SECONDS", 0.01):
            await gate._send_keepalive(ws)

        assert send_count >= 2
        # Verify the sent messages are media events
        sent_msg = json.loads(ws.send_text.call_args_list[0][0][0])
        assert sent_msg["event"] == "media"
        assert "payload" in sent_msg["media"]
