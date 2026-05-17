"""Base class for voice agent implementations.

This module provides the VoiceAgentBase abstract class containing shared
logic that is duplicated across all three voice agent implementations:
- Transcript tracking
- Interruption state management
- Connection status checking
- Logging configuration
- Prompt building via VoicePromptBuilder

By inheriting from this class, voice agents automatically get:
- Consistent transcript management
- Standard interruption handling pattern
- Unified logging setup
- Shared prompt builder for system instructions
"""

import asyncio
import base64
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

import structlog
from websockets import State
from websockets.asyncio.client import ClientConnection

from app.models.agent import Agent
from app.services.ai.ivr_detector import (
    IVRDetector,
    IVRDetectorConfig,
    IVRMode,
    IVRStatus,
)
from app.services.ai.prompt_builder import VoicePromptBuilder
from app.services.ai.protocols import (
    InterruptibleProtocol,
    VoiceAgentProtocol,
)

logger = structlog.get_logger()


class VoiceAgentBase(ABC):
    """Abstract base class for voice agent sessions.

    Provides common functionality shared across all voice agent implementations:
    - WebSocket connection management
    - Transcript tracking (user and agent speech)
    - Interruption (barge-in) handling
    - Connection status checking

    Subclasses must implement the abstract methods defined in VoiceAgentProtocol.

    Attributes:
        agent: Optional Agent model for configuration
        ws: WebSocket connection (or None if not connected)
        logger: Structured logger with service binding
    """

    # Subclasses should override these
    SERVICE_NAME: str = "voice_agent"
    BASE_URL: str = ""

    def __init__(self, agent: Agent | None = None, timezone: str = "America/New_York") -> None:
        """Initialize voice agent base.

        Args:
            agent: Optional Agent model for configuration
            timezone: Timezone for date context in prompts (IANA format)
        """
        self.agent = agent
        self.ws: ClientConnection | None = None
        self.logger = logger.bind(service=self.SERVICE_NAME)

        # Prompt builder for system instructions
        self._prompt_builder = VoicePromptBuilder(agent, timezone)
        self._timezone = timezone

        # Transcript tracking
        self._user_transcript: str = ""
        self._agent_transcript: str = ""
        self._transcript_entries: list[dict[str, Any]] = []

        # Interruption handling (barge-in)
        self._interruption_event: asyncio.Event | None = None
        self._is_interrupted: bool = False

        # Call context storage
        self._call_context: dict[str, Any] | None = None
        self._pending_greeting: str | None = None

        # IVR detection
        self._ivr_detector: IVRDetector | None = None
        self._ivr_mode: IVRMode = IVRMode.UNKNOWN
        self._ivr_navigation_goal: str | None = None

    # -------------------------------------------------------------------------
    # VoiceAgentProtocol implementations (shared logic)
    # -------------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Check if WebSocket is connected.

        Returns:
            True if connected, False otherwise
        """
        if self.ws is None:
            return False
        try:
            return self.ws.state == State.OPEN
        except AttributeError:
            return False

    def get_transcript_json(self) -> str | None:
        """Get the conversation transcript as JSON string.

        Returns the transcript in a format suitable for storage:
        [{"role": "user", "text": "..."}, {"role": "agent", "text": "..."}]

        Returns:
            JSON string of transcript entries, or None if no transcript
        """
        if not self._transcript_entries:
            return None
        return json.dumps(self._transcript_entries)

    # -------------------------------------------------------------------------
    # InterruptibleProtocol implementation
    # -------------------------------------------------------------------------

    def set_interruption_event(self, event: asyncio.Event) -> None:
        """Set event for signaling audio buffer clear on interruption.

        Args:
            event: asyncio.Event to set when user interrupts (barge-in)
        """
        self._interruption_event = event

    # -------------------------------------------------------------------------
    # Transcript management helpers
    # -------------------------------------------------------------------------

    def _add_user_transcript(self, text: str) -> None:
        """Add user speech to transcript.

        Args:
            text: User's spoken text
        """
        if text:
            self._user_transcript = text
            self._transcript_entries.append(
                {
                    "role": "user",
                    "text": text,
                }
            )
            self.logger.info("user_transcript_completed", user_said=text)

    def _add_agent_transcript(self, text: str) -> None:
        """Add agent speech to transcript.

        Args:
            text: Agent's spoken text
        """
        if text:
            self._transcript_entries.append(
                {
                    "role": "agent",
                    "text": text,
                }
            )
            self.logger.info("agent_turn_completed", agent_said=text[:200])

    def _save_current_agent_transcript(self) -> None:
        """Save accumulated agent transcript and reset buffer.

        Call this when a response is complete to persist the agent's
        speech, even if it was interrupted.
        """
        if self._agent_transcript:
            self._add_agent_transcript(self._agent_transcript)
            self._agent_transcript = ""

    def _append_agent_transcript_delta(self, delta: str) -> None:
        """Append delta to current agent transcript.

        Args:
            delta: Incremental transcript text
        """
        if delta:
            self._agent_transcript += delta

    def _log_full_transcript(self) -> None:
        """Log the full conversation transcript at end of call."""
        if self._transcript_entries:
            self.logger.info(
                "full_conversation_transcript",
                transcript=json.dumps(self._transcript_entries, indent=2),
                entry_count=len(self._transcript_entries),
            )

    # -------------------------------------------------------------------------
    # Interruption handling helpers
    # -------------------------------------------------------------------------

    def _handle_speech_started(self) -> None:
        """Handle user speech start (barge-in).

        Sets interrupted flag and signals buffer clear.
        Call this when receiving speech_started event.
        """
        self.logger.info("user_speech_started_interrupting")
        self._is_interrupted = True

        if self._interruption_event:
            self._interruption_event.set()

    def _handle_response_created(self) -> None:
        """Handle new response starting.

        Resets interrupted flag AND clears interruption event to allow
        audio from new response. Critical for proper barge-in handling.
        """
        if self._is_interrupted:
            self.logger.info(
                "resetting_interrupted_flag_on_new_response",
                was_interrupted=True,
            )
            self._is_interrupted = False

            # Clear the interruption event so voice_bridge doesn't clear
            # audio from the NEW response
            if self._interruption_event:
                self._interruption_event.clear()
                self.logger.debug("interruption_event_cleared_for_new_response")

    def _handle_response_done(self, status: str = "") -> None:
        """Handle response completion.

        Saves transcript and resets interrupted flag if needed.

        Args:
            status: Response status (e.g., "cancelled")
        """
        # Save agent transcript first
        self._save_current_agent_transcript()

        # Clear interrupted flag if response was cancelled
        if status == "cancelled" or self._is_interrupted:
            self._is_interrupted = False
            self.logger.info("cancelled_response_complete", status=status)

    def _should_skip_audio(self) -> bool:
        """Check if audio should be skipped due to interruption.

        Returns:
            True if interrupted and audio should be skipped
        """
        return self._is_interrupted

    # -------------------------------------------------------------------------
    # IVR Detection
    # -------------------------------------------------------------------------

    def enable_ivr_detection(
        self,
        navigation_goal: str | None = None,
        loop_threshold: int = 2,
        ivr_config: dict[str, int] | None = None,
    ) -> None:
        """Enable IVR detection for this session.

        Args:
            navigation_goal: Goal for IVR navigation (e.g., "reach sales dept")
            loop_threshold: Number of menu repeats before triggering loop action
            ivr_config: Optional IVR timing configuration with keys:
                - silence_duration_ms: Wait time for complete menus (default 3000)
                - post_dtmf_cooldown_ms: Cooldown after DTMF (default 3000)
                - menu_buffer_silence_ms: Buffer silence time (default 2000)
        """
        self._ivr_navigation_goal = navigation_goal
        self._ivr_config = ivr_config or {}

        config = IVRDetectorConfig(
            consecutive_classifications=loop_threshold,
            loop_similarity_threshold=0.85,
        )

        # NOTE: on_dtmf_detected callback is intentionally NOT set here.
        # DTMF sending is handled exclusively by DTMFHandler.check_and_send()
        # to prevent duplication bugs (same digit sent twice).
        self._ivr_detector = IVRDetector(
            config=config,
            on_mode_change=self._handle_ivr_mode_change,
            on_loop_detected=self._handle_ivr_loop,
            on_dtmf_detected=None,
        )

        self.logger.info(
            "ivr_detection_enabled",
            navigation_goal=navigation_goal,
            loop_threshold=loop_threshold,
            ivr_config=ivr_config,
        )

    def _handle_ivr_mode_change(self, old_mode: IVRMode, new_mode: IVRMode) -> None:
        """Handle IVR mode change callback.

        Override in subclasses to take action on mode changes.

        Args:
            old_mode: Previous IVR mode
            new_mode: New IVR mode
        """
        self._ivr_mode = new_mode
        self.logger.info(
            "ivr_mode_changed",
            old_mode=old_mode.value,
            new_mode=new_mode.value,
        )

    def _handle_ivr_loop(self) -> None:
        """Handle IVR loop detection callback.

        Override in subclasses to take action when IVR loop detected.
        Default action is to log the event.
        """
        self.logger.warning("ivr_loop_detected_in_base")

    async def process_ivr_transcript(
        self,
        transcript: str,
        is_agent: bool = False,
    ) -> IVRMode:
        """Process transcript through IVR detector.

        Args:
            transcript: Speech transcript to process
            is_agent: True if agent speech, False for remote party

        Returns:
            Current IVR mode after processing
        """
        if not self._ivr_detector:
            return IVRMode.UNKNOWN

        return await self._ivr_detector.process_transcript(transcript, is_agent)

    def get_ivr_status(self) -> IVRStatus | None:
        """Get current IVR detection status.

        Returns:
            IVRStatus if detection enabled, None otherwise
        """
        if not self._ivr_detector:
            return None
        return self._ivr_detector.status

    def strip_dtmf_tags(self, text: str) -> str:
        """Strip DTMF tags from text.

        Args:
            text: Text that may contain <dtmf>X</dtmf> tags

        Returns:
            Text with DTMF tags removed
        """
        if not self._ivr_detector:
            return text
        return self._ivr_detector.strip_dtmf_tags(text)

    # -------------------------------------------------------------------------
    # WebSocket helpers
    # -------------------------------------------------------------------------

    async def _send_event(self, event: dict[str, Any]) -> None:
        """Send event to WebSocket.

        Args:
            event: Event dictionary to send

        Raises:
            RuntimeError: If WebSocket not connected
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")

        try:
            await self.ws.send(json.dumps(event))
        except Exception as e:
            self.logger.exception("send_event_error", error=str(e))
            raise

    async def _send_audio_base64(
        self, audio_data: bytes, event_type: str = "input_audio_buffer.append"
    ) -> None:
        """Send base64-encoded audio to provider.

        Args:
            audio_data: Raw audio bytes to encode and send
            event_type: Event type for the audio message
        """
        if not self.ws:
            self.logger.warning("websocket_not_connected")
            return

        try:
            encoded = base64.b64encode(audio_data).decode("utf-8")
            await self._send_event({"type": event_type, "audio": encoded})
        except Exception as e:
            self.logger.exception("send_audio_error", error=str(e))

    async def _disconnect_ws(self) -> None:
        """Template method for WebSocket disconnect.

        Closes the WebSocket connection and logs the full transcript.
        Subclasses can call this from their disconnect() implementation.
        """
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                self.logger.exception("disconnect_error", error=str(e))
            self.ws = None
        self._log_full_transcript()

    # -------------------------------------------------------------------------
    # Abstract methods (must be implemented by subclasses)
    # -------------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> bool:
        """Connect to the voice provider API."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the voice provider API."""
        ...

    @abstractmethod
    async def configure_session(
        self,
        voice: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        turn_detection_mode: str | None = None,
        turn_detection_threshold: float | None = None,
        silence_duration_ms: int | None = None,
    ) -> None:
        """Reconfigure the session with custom settings."""
        ...

    @abstractmethod
    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to the voice provider."""
        ...

    @abstractmethod
    def receive_audio_stream(self) -> AsyncIterator[bytes]:
        """Stream audio responses from the voice provider."""
        ...

    @abstractmethod
    async def trigger_initial_response(
        self,
        greeting: str | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Trigger the AI to start speaking."""
        ...

    @abstractmethod
    async def inject_context(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Inject conversation context."""
        ...

    @abstractmethod
    async def cancel_response(self) -> None:
        """Cancel the current response generation."""
        ...


# Verify that VoiceAgentBase satisfies the protocols
def _verify_protocols() -> None:
    """Type checking verification (not executed at runtime)."""
    # This function exists to help type checkers verify protocol compliance
    # It's never called - just analyzed by mypy
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:

        def check_agent(agent: VoiceAgentBase) -> None:
            _: VoiceAgentProtocol = agent  # noqa: F841
            _i: InterruptibleProtocol = agent  # noqa: F841
