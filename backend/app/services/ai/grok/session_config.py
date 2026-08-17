"""Grok session configuration builder.

This module provides a builder pattern for constructing Grok Realtime API
session configurations, encapsulating the logic for:
- Voice selection and validation
- Tool configuration (built-in, DTMF, booking)
- Turn detection settings
- Audio format configuration
"""

from typing import Any

import structlog

from app.models.agent import Agent
from app.services.ai.grok.constants import (
    AUDIO_CONFIG,
    DEFAULT_TURN_DETECTION,
    DEFAULT_VOICE,
    GROK_VOICES,
)
from app.services.ai.voice_prompt_builder import VoicePromptBuilder
from app.services.ai.voice_tools import (
    DTMF_TOOL,
    GROK_BUILTIN_TOOLS,
    LOOKUP_CALLER_RECORD_TOOL,
    get_booking_tools,
    is_lookup_caller_record_enabled,
)

logger = structlog.get_logger()


class GrokSessionConfigBuilder:
    """Builder for Grok Realtime API session configuration.

    Provides a fluent interface for constructing session.update payloads
    with proper validation and sensible defaults.

    Usage:
        builder = GrokSessionConfigBuilder(agent, prompt_builder, timezone)
        config = (
            builder
            .with_voice("ara")
            .with_tools(enable_booking=True, ivr_detector_active=True)
            .with_turn_detection(threshold=0.5, silence_ms=700)
            .build()
        )
    """

    def __init__(
        self,
        agent: Agent | None,
        prompt_builder: VoicePromptBuilder,
        timezone: str = "America/New_York",
    ) -> None:
        """Initialize the config builder.

        Args:
            agent: Optional Agent model for configuration
            prompt_builder: VoicePromptBuilder for generating prompts
            timezone: Timezone for date context (IANA format)
        """
        self._agent = agent
        self._prompt_builder = prompt_builder
        self._timezone = timezone
        self._logger = logger.bind(service="grok_session_config")

        # Configuration state
        self._voice: str | None = None
        self._instructions: str | None = None
        self._tools: list[dict[str, Any]] = []
        self._turn_detection: dict[str, Any] | None = None
        self._audio_config: dict[str, Any] | None = None

    def with_voice(self, voice: str | None = None) -> "GrokSessionConfigBuilder":
        """Set the voice for the session.

        Args:
            voice: Voice ID (ara, rex, sal, eve, leo). If None, uses agent's
                   configured voice or defaults to Ara.

        Returns:
            Self for chaining
        """
        if voice:
            voice_lower = voice.lower()
            if voice_lower in GROK_VOICES:
                self._voice = voice_lower.capitalize()
            else:
                self._logger.warning(
                    "invalid_grok_voice",
                    voice=voice,
                    defaulting_to=DEFAULT_VOICE,
                )
                self._voice = DEFAULT_VOICE
        elif self._agent and self._agent.voice_id:
            voice_lower = self._agent.voice_id.lower()
            if voice_lower in GROK_VOICES:
                self._voice = voice_lower.capitalize()
            else:
                self._logger.warning(
                    "invalid_grok_voice",
                    voice=voice_lower,
                    defaulting_to=DEFAULT_VOICE,
                )
                self._voice = DEFAULT_VOICE
        else:
            self._voice = DEFAULT_VOICE

        return self

    def with_instructions(
        self,
        base_prompt: str | None = None,
        include_realism: bool = True,
        include_booking: bool = False,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> "GrokSessionConfigBuilder":
        """Set the instructions for the session.

        Args:
            base_prompt: Optional base prompt override
            include_realism: Include Grok realism enhancement cues
            include_booking: Include booking instructions
            contact_info: Optional contact context
            offer_info: Optional offer context
            is_outbound: True for outbound calls

        Returns:
            Self for chaining
        """
        self._instructions = self._prompt_builder.build_full_prompt(
            base_prompt=base_prompt,
            include_realism=include_realism,
            include_booking=include_booking,
            contact_info=contact_info,
            offer_info=offer_info,
            is_outbound=is_outbound,
        )
        return self

    def with_tools(
        self,
        enable_booking: bool = False,
        ivr_detector_active: bool = False,
        require_caller_record_lookup: bool = False,
    ) -> "GrokSessionConfigBuilder":
        """Configure tools for the session.

        Args:
            enable_booking: Enable Google Calendar booking tools
            ivr_detector_active: Whether IVR detector is active (auto-enables DTMF)
            require_caller_record_lookup: Force live caller CRM evidence for this prompt

        Returns:
            Self for chaining
        """
        self._tools = []
        agent_enabled_tools = (
            self._agent.enabled_tools if self._agent and self._agent.enabled_tools else []
        )

        # Add Grok built-in tools if enabled in agent settings
        if "web_search" in agent_enabled_tools:
            self._tools.append(GROK_BUILTIN_TOOLS["web_search"])
            self._logger.info("grok_web_search_enabled")

        if "x_search" in agent_enabled_tools:
            self._tools.append(GROK_BUILTIN_TOOLS["x_search"])
            self._logger.info("grok_x_search_enabled")

        # Add DTMF tool for IVR navigation if enabled
        if self._should_enable_dtmf(agent_enabled_tools, ivr_detector_active):
            self._tools.append(DTMF_TOOL)
            dtmf_reason = "ivr_detector_active" if ivr_detector_active else "explicit_config"
            self._logger.info("grok_dtmf_tool_enabled", reason=dtmf_reason)

        # The prompt requires this caller-bound read whenever volatile CRM data is present.
        if require_caller_record_lookup or is_lookup_caller_record_enabled(self._agent):
            self._tools.append(LOOKUP_CALLER_RECORD_TOOL)

        # Add Google Calendar booking tools if enabled
        if enable_booking:
            booking_tools = get_booking_tools(self._timezone)
            self._tools.extend(booking_tools)
            self._logger.info(
                "grok_booking_tools_enabled",
                tool_count=len(booking_tools),
            )

        if self._tools:
            tool_names = [t.get("name", t.get("type", "unknown")) for t in self._tools]
            self._logger.info(
                "grok_tools_configured",
                total_tool_count=len(self._tools),
                tool_names=tool_names,
            )

        return self

    def _should_enable_dtmf(
        self,
        agent_enabled_tools: list[str],
        ivr_detector_active: bool,
    ) -> bool:
        """Determine if DTMF tool should be enabled.

        Args:
            agent_enabled_tools: List of enabled tool IDs
            ivr_detector_active: Whether IVR detector is active

        Returns:
            True if DTMF should be enabled
        """
        # Legacy/direct pattern
        if "send_dtmf" in agent_enabled_tools:
            return True

        # Integration-based pattern
        tool_settings = (
            self._agent.tool_settings if self._agent and self._agent.tool_settings else {}
        )
        call_control_tools = tool_settings.get("call_control", []) or []
        if "call_control" in agent_enabled_tools and "send_dtmf" in call_control_tools:
            return True

        # Auto-enable if IVR detection active
        return bool(ivr_detector_active)

    def with_turn_detection(
        self,
        mode: str | None = None,
        threshold: float | None = None,
        silence_duration_ms: int | None = None,
        prefix_padding_ms: int | None = None,
    ) -> "GrokSessionConfigBuilder":
        """Configure turn detection settings.

        Args:
            mode: Turn detection type (server_vad)
            threshold: VAD threshold (0.0-1.0)
            silence_duration_ms: Silence duration before turn ends
            prefix_padding_ms: Padding before speech detection

        Returns:
            Self for chaining
        """
        # Start with defaults
        self._turn_detection = dict(DEFAULT_TURN_DETECTION)

        # Override with agent settings
        if self._agent and self._agent.turn_detection_mode:
            self._turn_detection["type"] = self._agent.turn_detection_mode

        # Override with explicit parameters
        if mode is not None:
            self._turn_detection["type"] = mode
        if threshold is not None:
            self._turn_detection["threshold"] = threshold
        if silence_duration_ms is not None:
            self._turn_detection["silence_duration_ms"] = silence_duration_ms
        if prefix_padding_ms is not None:
            self._turn_detection["prefix_padding_ms"] = prefix_padding_ms

        return self

    def with_audio_config(self) -> "GrokSessionConfigBuilder":
        """Configure audio format settings.

        Returns:
            Self for chaining
        """
        self._audio_config = dict(AUDIO_CONFIG)
        return self

    def build(self) -> dict[str, Any]:
        """Build the complete session configuration.

        Returns:
            Session configuration dictionary ready for session.update event
        """
        session_config: dict[str, Any] = {}

        if self._instructions:
            session_config["instructions"] = self._instructions

        if self._voice:
            session_config["voice"] = self._voice

        if self._audio_config:
            session_config["audio"] = self._audio_config

        if self._turn_detection:
            session_config["turn_detection"] = self._turn_detection

        if self._tools:
            session_config["tools"] = self._tools

        self._logger.info(
            "grok_session_config_built",
            config_keys=list(session_config.keys()),
            has_tools=bool(self._tools),
            tool_count=len(self._tools),
        )

        return session_config

    def build_update_event(self) -> dict[str, Any]:
        """Build a complete session.update event.

        Returns:
            Full event dictionary with type and session config
        """
        return {
            "type": "session.update",
            "session": self.build(),
        }
