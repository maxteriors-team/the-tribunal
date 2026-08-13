"""Voice agent protocol definitions.

This module defines the formal interfaces that all voice agent implementations
must follow, using Python's Protocol for structural subtyping.

Protocols:
    VoiceAgentProtocol: Core voice agent interface for connection and audio streaming
    ToolCallableProtocol: Interface for agents that support tool/function calling
    InterruptibleProtocol: Interface for agents that support barge-in handling
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VoiceAgentProtocol(Protocol):
    """Protocol defining the core interface for voice agent sessions.

    All voice agent implementations (OpenAI, Grok, ElevenLabs) must implement
    this interface to work with the voice bridge.

    This protocol covers:
    - Connection management (connect, disconnect, is_connected)
    - Audio streaming (send_audio_chunk, receive_audio_stream)
    - Session configuration (configure_session)
    - Conversation initiation (trigger_initial_response)
    - Context injection (inject_context)
    - Transcript retrieval (get_transcript_json)
    """

    async def connect(self) -> bool:
        """Connect to the voice provider API.

        Returns:
            True if connection successful, False otherwise.
        """
        ...

    async def disconnect(self) -> None:
        """Disconnect from the voice provider API.

        Should clean up all resources and close connections gracefully.
        """
        ...

    async def configure_session(
        self,
        voice: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        turn_detection_mode: str | None = None,
        turn_detection_threshold: float | None = None,
        silence_duration_ms: int | None = None,
    ) -> None:
        """Reconfigure the session with custom settings.

        Args:
            voice: Voice ID for text-to-speech
            system_prompt: System instructions for the AI
            temperature: Response randomness (0.0-1.0)
            turn_detection_mode: Turn detection type (server_vad, none)
            turn_detection_threshold: VAD sensitivity threshold
            silence_duration_ms: Silence duration before turn ends
        """
        ...

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to the voice provider.

        Args:
            audio_data: Audio bytes in the provider's expected format.
                       OpenAI: g711_ulaw 8kHz
                       Grok: PCM16 24kHz
                       ElevenLabs: PCM16 24kHz (via Grok STT)
        """
        ...

    def receive_audio_stream(self) -> AsyncIterator[bytes]:
        """Stream audio responses from the voice provider.

        This async generator continuously yields audio chunks from the provider.
        It should NOT break on response completion - keep listening for more
        responses as the conversation continues.

        Yields:
            Audio chunks in provider's output format:
                OpenAI: g711_ulaw 8kHz
                Grok: PCM16 24kHz
                ElevenLabs: ulaw_8000 (ready for Telnyx)
        """
        ...

    async def trigger_initial_response(
        self,
        greeting: str | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Trigger the AI to start speaking with initial greeting.

        Call this after the audio stream is established to initiate conversation.
        For outbound calls, uses a pattern interrupt opener.
        For inbound calls, uses the configured greeting.

        Args:
            greeting: Optional greeting text override
            is_outbound: True if this is an outbound call (AI initiated)
        """
        ...

    async def inject_context(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Inject conversation context into the session.

        Updates the session instructions to include contact and offer context
        for personalized conversation handling.

        Args:
            contact_info: Contact information (name, company, phone, email)
            offer_info: Offer/product information (name, description, terms)
            is_outbound: True if this is an outbound call
        """
        ...

    async def cancel_response(self) -> None:
        """Cancel the current response generation.

        Called during barge-in handling when user starts speaking
        while the AI is responding.
        """
        ...

    def is_connected(self) -> bool:
        """Check if the connection to the voice provider is active.

        Returns:
            True if connected and ready, False otherwise.
        """
        ...

    def get_transcript_json(self) -> str | None:
        """Get the conversation transcript as JSON string.

        Returns the transcript in format:
        [{"role": "user", "text": "..."}, {"role": "agent", "text": "..."}]

        Returns:
            JSON string of transcript entries, or None if no transcript.
        """
        ...


@runtime_checkable
class ToolCallableProtocol(Protocol):
    """Protocol for voice agents that support tool/function calling.

    Implemented by OpenAI, Grok, and ElevenLabs voice agents for calendar scheduling
    booking, web search, X search, and DTMF tools.
    """

    def set_tool_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], Any],
    ) -> None:
        """Set the callback function for tool execution.

        The callback receives:
        - call_id: Unique identifier for the function call
        - function_name: Name of the function to execute
        - arguments: Dictionary of function arguments

        Args:
            callback: Async function(call_id, function_name, arguments) -> result
        """
        ...

    async def submit_tool_result(
        self,
        call_id: str,
        result: dict[str, Any],
    ) -> None:
        """Submit tool execution result back to the voice provider.

        Args:
            call_id: The function call ID from the provider
            result: The result dictionary to send back
        """
        ...


@runtime_checkable
class InterruptibleProtocol(Protocol):
    """Protocol for voice agents that support interruption (barge-in) handling.

    Allows the voice bridge to signal audio buffer clearing when the user
    starts speaking during AI response.
    """

    def set_interruption_event(self, event: asyncio.Event) -> None:
        """Set the event for signaling audio buffer clear on interruption.

        The event is set when the user starts speaking (barge-in detected),
        signaling the audio buffer should be cleared immediately.

        Args:
            event: asyncio.Event to set on user interruption
        """
        ...


@runtime_checkable
class IVRDetectableProtocol(Protocol):
    """Protocol for voice agents that support IVR detection and navigation.

    Implemented by voice agents that can detect IVR menus, track mode changes,
    and automatically navigate using DTMF tones.
    """

    def enable_ivr_detection(
        self,
        navigation_goal: str | None = None,
        loop_threshold: int = 2,
        ivr_config: dict[str, int] | None = None,
    ) -> None:
        """Enable IVR detection with optional navigation goal.

        Args:
            navigation_goal: Goal for IVR navigation (e.g., "reach sales dept")
            loop_threshold: Number of menu repeats before triggering loop action
            ivr_config: Optional IVR timing configuration with keys:
                - silence_duration_ms: Wait time for complete menus (default 3000)
                - post_dtmf_cooldown_ms: Cooldown after DTMF (default 3000)
                - menu_buffer_silence_ms: Buffer silence time (default 2000)
        """
        ...

    async def process_ivr_transcript(
        self,
        transcript: str,
        is_agent: bool = False,
    ) -> Any:
        """Process a transcript through IVR detection.

        Args:
            transcript: Speech transcript to analyze
            is_agent: True if this is agent speech, False for remote party

        Returns:
            Current IVR mode after processing
        """
        ...


# Type alias for voice sessions that may or may not support tools
VoiceAgentType = VoiceAgentProtocol


def supports_tools(agent: VoiceAgentProtocol) -> bool:
    """Check if a voice agent supports tool calling.

    Args:
        agent: Voice agent to check

    Returns:
        True if the agent implements ToolCallableProtocol
    """
    return isinstance(agent, ToolCallableProtocol)


def supports_interruption(agent: VoiceAgentProtocol) -> bool:
    """Check if a voice agent supports interruption handling.

    Args:
        agent: Voice agent to check

    Returns:
        True if the agent implements InterruptibleProtocol
    """
    return isinstance(agent, InterruptibleProtocol)


def supports_ivr_detection(agent: VoiceAgentProtocol) -> bool:
    """Check if a voice agent supports IVR detection.

    Args:
        agent: Voice agent to check

    Returns:
        True if the agent implements IVRDetectableProtocol
    """
    return isinstance(agent, IVRDetectableProtocol)
