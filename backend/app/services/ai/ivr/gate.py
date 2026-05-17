"""IVR Gate - Phase 1 orchestrator for 2-phase calling.

Intercepts the Telnyx WebSocket before expensive AI connects.
Runs transcribe -> classify -> navigate cycles using cheap Whisper
transcription + regex classification + scripted DTMF navigation.
Returns when a human is detected, voicemail is found, or timeout.
"""

import asyncio
import base64
import contextlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from app.services.ai.ivr.classifier import IVRClassifier
from app.services.ai.ivr.navigator import NavigationAction, ScriptedNavigator
from app.services.ai.ivr.transcriber import WhisperTranscriber
from app.services.ai.ivr.types import IVRMode

logger = structlog.get_logger()

# Timing constants
FIRST_BUFFER_SECONDS = 1.5  # Shorter first buffer for quick human detection
NORMAL_BUFFER_SECONDS = 3.0  # Normal buffer for IVR menus
GATE_TIMEOUT_SECONDS = 45.0  # Max time in Phase 1
POST_DTMF_COOLDOWN_SECONDS = 3.0  # Wait after sending DTMF
KEEPALIVE_INTERVAL_SECONDS = 0.5  # Silence frame interval
MULAW_SILENCE_BYTE = 0xFF  # mu-law silence value
KEEPALIVE_FRAME_SIZE = 160  # 20ms at 8kHz


class GateOutcome(Enum):
    """Outcome of Phase 1 IVR gate."""

    HUMAN_DETECTED = "human_detected"
    VOICEMAIL_DETECTED = "voicemail_detected"
    TIMEOUT = "timeout"
    FALLBACK_AI = "fallback_ai"
    CALL_DROPPED = "call_dropped"
    ERROR = "error"


@dataclass
class GateResult:
    """Result returned by IVRGate.run()."""

    outcome: GateOutcome
    transcript_history: list[str] = field(default_factory=list)
    last_transcript: str = ""
    duration_seconds: float = 0.0
    dtmf_attempts: int = 0


class IVRGate:
    """Phase 1 orchestrator that navigates IVR menus before connecting AI.

    Takes control of the Telnyx WebSocket, runs cheap transcription +
    classification cycles, sends DTMF for menu navigation, and returns
    when done. Does NOT close the WebSocket - caller hands it to Phase 2.

    Args:
        call_control_id: Telnyx call control ID for DTMF/hangup
        navigation_goal: What we're trying to reach (e.g., "Reach a human representative")
        agent_config: Dict of agent IVR settings (loop_threshold, cooldown, etc.)
        log: Bound structlog logger
    """

    def __init__(
        self,
        call_control_id: str,
        navigation_goal: str = "Reach a human representative",
        agent_config: dict[str, Any] | None = None,
        log: Any | None = None,
    ) -> None:
        self._call_control_id = call_control_id
        self._log = (log or logger).bind(service="ivr_gate", call_id=call_control_id)

        config = agent_config or {}
        self._post_dtmf_cooldown = (
            config.get("post_dtmf_cooldown_ms", int(POST_DTMF_COOLDOWN_SECONDS * 1000)) / 1000.0
        )
        loop_threshold = config.get("loop_threshold", 2)
        max_attempts = loop_threshold * 4  # More generous than loop threshold

        self._transcriber = WhisperTranscriber()
        self._classifier = IVRClassifier()
        self._navigator = ScriptedNavigator(
            navigation_goal=navigation_goal,
            max_attempts=max_attempts,
        )

        self._transcript_history: list[str] = []
        self._dtmf_attempts = 0
        self._stream_started = False
        self._stream_id = ""
        self._audio_buffer = bytearray()
        self._gate_start = 0.0
        self._is_first_buffer = True
        self._keepalive_task: asyncio.Task[None] | None = None

    async def run(self, websocket: Any) -> GateResult:
        """Run Phase 1 IVR gate on the Telnyx WebSocket.

        Consumes WebSocket events (start, media, stop) and runs
        transcribe -> classify -> navigate cycles.

        Does NOT close the WebSocket. After returning, caller can
        hand it to Phase 2 (AI provider).

        Args:
            websocket: Telnyx WebSocket connection (FastAPI WebSocket)

        Returns:
            GateResult with outcome and collected data
        """
        self._gate_start = time.time()
        self._log.info(
            "ivr_gate_phase1_starting",
            navigation_goal=self._navigator.navigation_goal,
            timeout=GATE_TIMEOUT_SECONDS,
        )

        try:
            result = await asyncio.wait_for(
                self._gate_loop(websocket),
                timeout=GATE_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            elapsed = time.time() - self._gate_start
            self._log.warning("ivr_gate_timeout", elapsed=round(elapsed, 1))
            result = GateResult(
                outcome=GateOutcome.TIMEOUT,
                transcript_history=self._transcript_history,
                last_transcript=self._transcript_history[-1] if self._transcript_history else "",
                duration_seconds=elapsed,
                dtmf_attempts=self._dtmf_attempts,
            )
        except Exception as e:
            elapsed = time.time() - self._gate_start
            self._log.exception("ivr_gate_error", error=str(e))
            result = GateResult(
                outcome=GateOutcome.ERROR,
                transcript_history=self._transcript_history,
                duration_seconds=elapsed,
                dtmf_attempts=self._dtmf_attempts,
            )
        finally:
            if self._keepalive_task and not self._keepalive_task.done():
                self._keepalive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._keepalive_task

        self._log.info(
            "ivr_gate_phase1_complete",
            outcome=result.outcome.value,
            duration=round(result.duration_seconds, 1),
            dtmf_attempts=result.dtmf_attempts,
            transcripts=len(result.transcript_history),
        )
        return result

    async def _gate_loop(self, websocket: Any) -> GateResult:
        """Main gate loop - receive events, buffer audio, process buffers."""
        while True:
            elapsed = time.time() - self._gate_start
            if elapsed > GATE_TIMEOUT_SECONDS:
                return self._make_result(GateOutcome.TIMEOUT)

            try:
                raw_data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=max(1.0, GATE_TIMEOUT_SECONDS - elapsed),
                )
            except TimeoutError:
                return self._make_result(GateOutcome.TIMEOUT)

            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                continue

            event = data.get("event", "")

            if event == "start":
                self._stream_started = True
                self._stream_id = data.get("stream_id", "")
                self._log.info("ivr_gate_stream_started", stream_id=self._stream_id)

                # Start keepalive to prevent Telnyx from closing
                self._keepalive_task = asyncio.create_task(self._send_keepalive(websocket))

            elif event == "media" and self._stream_started:
                media = data.get("media", {})
                payload = media.get("payload", "")
                if payload:
                    audio_bytes = base64.b64decode(payload)
                    self._audio_buffer.extend(audio_bytes)

                    # Check if buffer is full
                    buffer_target = (
                        FIRST_BUFFER_SECONDS if self._is_first_buffer else NORMAL_BUFFER_SECONDS
                    )
                    # At 8kHz mu-law, 1 byte per sample -> 8000 bytes/sec
                    target_bytes = int(buffer_target * 8000)

                    if len(self._audio_buffer) >= target_bytes:
                        result = await self._process_buffer()
                        if result is not None:
                            return result

            elif event == "stop":
                self._log.info("ivr_gate_stream_stopped")
                return self._make_result(GateOutcome.CALL_DROPPED)

            elif event == "error":
                error_msg = data.get("error", {}).get("message", "unknown")
                self._log.error("ivr_gate_stream_error", error=error_msg)
                return self._make_result(GateOutcome.ERROR)

    async def _process_buffer(self) -> GateResult | None:
        """Process accumulated audio buffer: transcribe -> classify -> navigate.

        Returns:
            GateResult if gate should exit, None to continue
        """
        audio_data = bytes(self._audio_buffer)
        self._audio_buffer.clear()
        self._is_first_buffer = False

        # Transcribe
        transcript = await self._transcriber.transcribe(audio_data)
        if not transcript:
            self._log.debug("ivr_gate_empty_transcript", audio_bytes=len(audio_data))
            return None

        self._transcript_history.append(transcript)
        self._log.info(
            "ivr_gate_transcript",
            transcript=transcript[:200],
            buffer_num=len(self._transcript_history),
        )

        # Classify
        mode, confidence = self._classifier.classify(transcript)
        self._log.info(
            "ivr_gate_classification",
            mode=mode.value,
            confidence=round(confidence, 2),
        )

        # Act on classification
        if mode == IVRMode.CONVERSATION:
            self._log.info("ivr_gate_human_detected", confidence=round(confidence, 2))
            return self._make_result(GateOutcome.HUMAN_DETECTED)

        if mode == IVRMode.VOICEMAIL:
            self._log.info("ivr_gate_voicemail_detected", confidence=round(confidence, 2))
            return self._make_result(GateOutcome.VOICEMAIL_DETECTED)

        if mode == IVRMode.IVR:
            # Navigate the IVR menu
            nav_result = self._navigator.select_digit(transcript)

            if nav_result.action == NavigationAction.PRESS_DIGIT:
                await self._send_dtmf(nav_result.digit)
                self._navigator.record_attempt(nav_result.digit)
                self._dtmf_attempts += 1
                self._log.info(
                    "ivr_gate_dtmf_sent",
                    digit=nav_result.digit,
                    reason=nav_result.reason,
                    attempt=self._dtmf_attempts,
                )
                # Wait for IVR to respond after DTMF
                await asyncio.sleep(self._post_dtmf_cooldown)
                return None

            if nav_result.action == NavigationAction.FALLBACK_AI:
                self._log.info(
                    "ivr_gate_fallback_to_ai",
                    reason=nav_result.reason,
                )
                return self._make_result(GateOutcome.FALLBACK_AI)

        # UNKNOWN or NO_ACTION - continue listening
        return None

    async def _send_dtmf(self, digits: str) -> None:
        """Send DTMF tones via Telnyx API."""
        from app.core.config import settings
        from app.services.telephony.telnyx_voice import TelnyxVoiceService

        svc = TelnyxVoiceService(settings.telnyx_api_key)
        success = await svc.send_dtmf(self._call_control_id, digits)
        if not success:
            self._log.warning("ivr_gate_dtmf_send_failed", digits=digits)

    async def _send_keepalive(self, websocket: Any) -> None:
        """Send silence frames to keep Telnyx stream alive.

        Telnyx may close the media stream if no audio is sent for too long.
        This sends mu-law silence frames at regular intervals.
        """
        silence_frame = base64.b64encode(bytes([MULAW_SILENCE_BYTE] * KEEPALIVE_FRAME_SIZE)).decode(
            "utf-8"
        )

        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
                msg = json.dumps(
                    {
                        "event": "media",
                        "media": {"payload": silence_frame},
                    }
                )
                try:
                    await websocket.send_text(msg)
                except (RuntimeError, OSError):
                    self._log.debug("keepalive_send_failed_connection_closed")
                    break
        except asyncio.CancelledError:
            return

    def _make_result(self, outcome: GateOutcome) -> GateResult:
        """Create a GateResult with current state."""
        return GateResult(
            outcome=outcome,
            transcript_history=self._transcript_history,
            last_transcript=self._transcript_history[-1] if self._transcript_history else "",
            duration_seconds=time.time() - self._gate_start,
            dtmf_attempts=self._dtmf_attempts,
        )
