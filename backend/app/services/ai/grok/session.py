"""Grok (xAI) Realtime API session for voice conversations.

This is the main entry point for Grok voice agent functionality.
The session acts as a thin coordinator, delegating to specialized modules:
- DTMFHandler for IVR navigation
- EventHandlerRegistry for event processing
- IVRModeController for mode switching
- GrokSessionConfigBuilder for configuration
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any

import structlog
from websockets.asyncio.client import connect

from app.models.agent import Agent
from app.services.ai.grok.audio_stream import AudioStreamConfig, AudioStreamManager
from app.services.ai.grok.constants import GROK_REALTIME_BASE_URL, TOOL_TIMEOUT_SECONDS
from app.services.ai.grok.dtmf_handler import DTMFHandler, DTMFHandlerConfig
from app.services.ai.grok.event_handlers import EventContext, EventHandlerRegistry
from app.services.ai.grok.ivr_mode_controller import IVRModeConfig, IVRModeController
from app.services.ai.grok.session_config import GrokSessionConfigBuilder
from app.services.ai.voice_agent_base import VoiceAgentBase

if TYPE_CHECKING:
    from app.services.ai.ivr_detector import IVRMode

logger = structlog.get_logger()


class GrokVoiceAgentSession(VoiceAgentBase):
    """Grok (xAI) Realtime API session for voice conversations.

    Manages:
    - WebSocket connection to Grok Realtime API
    - Audio streaming and format conversion
    - Session configuration and context injection
    - Tool calling for Cal.com booking integration
    - IVR detection and DTMF navigation

    Inherits from VoiceAgentBase for:
    - Transcript tracking
    - Interruption handling
    - Prompt building via VoicePromptBuilder

    This refactored version delegates to specialized modules:
    - DTMFHandler: DTMF detection and sending
    - EventHandlerRegistry: Event processing
    - IVRModeController: IVR mode switching
    - GrokSessionConfigBuilder: Session configuration
    """

    SERVICE_NAME = "grok_voice_agent"
    BASE_URL = GROK_REALTIME_BASE_URL

    def __init__(
        self,
        api_key: str,
        agent: Agent | None = None,
        enable_tools: bool = False,
        timezone: str = "America/New_York",
    ) -> None:
        """Initialize Grok voice agent session.

        Args:
            api_key: xAI API key
            agent: Optional Agent model for configuration
            enable_tools: Enable booking tools (requires Cal.com config)
            timezone: Timezone for date context (default: America/New_York)
        """
        super().__init__(agent, timezone)
        self.api_key = api_key
        self._connection_task: asyncio.Task[None] | None = None
        self._enable_tools = enable_tools

        # Tool call handling
        self._tool_callback: Callable[[str, str, dict[str, Any]], Any] | None = None

        # Initialize DTMF handler
        self._dtmf_handler = DTMFHandler(
            config=DTMFHandlerConfig(),
            tool_callback=None,  # Set later via set_tool_callback
            get_ivr_status=self.get_ivr_status,
            record_dtmf_attempt=self._record_dtmf_attempt,
        )

        # Initialize event handler registry
        self._event_registry = EventHandlerRegistry()

        # Initialize IVR mode controller
        self._ivr_controller = IVRModeController(
            configure_session=self.configure_session,
            inject_ivr_context=self._inject_ivr_context,
            config=IVRModeConfig(
                default_silence_ms=agent.silence_duration_ms if agent else 700,
                default_threshold=agent.turn_detection_threshold if agent else 0.5,
            ),
            agent_silence_ms=agent.silence_duration_ms if agent else None,
            agent_threshold=agent.turn_detection_threshold if agent else None,
        )

        # Log initialization details
        self.logger.info(
            "grok_voice_agent_initialized",
            agent_name=agent.name if agent else None,
            agent_id=str(agent.id) if agent else None,
            enable_tools=enable_tools,
            calcom_event_type_id=agent.calcom_event_type_id if agent else None,
            enabled_tools=agent.enabled_tools if agent else None,
        )

    def _record_dtmf_attempt(self, digits: str) -> None:
        """Record DTMF attempt in the IVR detector.

        Args:
            digits: DTMF digits that were sent
        """
        if self._ivr_detector:
            self._ivr_detector.record_dtmf_attempt(digits)

    def set_tool_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], Any],
    ) -> None:
        """Set callback for tool execution.

        Args:
            callback: Async function(call_id, function_name, arguments) -> result
        """
        self._tool_callback = callback
        self._dtmf_handler.set_tool_callback(callback)
        self.logger.info(
            "grok_tool_callback_set",
            callback_set=callback is not None,
            enable_tools=self._enable_tools,
        )

    async def connect(self) -> bool:
        """Connect to Grok Realtime API.

        Returns:
            True if successful, False otherwise
        """
        self.logger.info("connecting_to_grok_realtime_api")

        try:
            self.ws = await connect(
                self.BASE_URL,
                additional_headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )

            self.logger.info("connected_to_grok_realtime_api")

            # Send session configuration
            await self._configure_session()

            return True
        except Exception as e:
            self.logger.exception("grok_connection_failed", error=str(e))
            return False

    async def disconnect(self) -> None:
        """Disconnect from Grok Realtime API."""
        # Clean up DTMF handler
        await self._dtmf_handler.cleanup()

        # Disconnect WebSocket
        await self._disconnect_ws()

    async def _configure_session(self) -> None:
        """Configure the Grok Realtime session with agent settings.

        Uses pcm16 at 24kHz - the voice_bridge handles conversion from/to
        Telnyx's μ-law 8kHz format.
        """
        builder = GrokSessionConfigBuilder(
            agent=self.agent,
            prompt_builder=self._prompt_builder,
            timezone=self._timezone,
        )

        config = (
            builder.with_voice()
            .with_instructions(
                include_realism=True,
                include_booking=self._enable_tools,
            )
            .with_audio_config()
            .with_turn_detection()
            .with_tools(
                enable_booking=self._enable_tools,
                ivr_detector_active=self._ivr_detector is not None,
            )
            .build_update_event()
        )

        await self._send_event(config)

        self.logger.info(
            "grok_session_configured",
            tools_enabled=self._enable_tools,
            tool_callback_set=self._tool_callback is not None,
        )

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
            voice: Voice ID (ara, rex, sal, eve, leo)
            system_prompt: System instructions for the assistant
            temperature: Response temperature (may not be supported by Grok)
            turn_detection_mode: Turn detection type (server_vad)
            turn_detection_threshold: VAD threshold (0.0-1.0)
            silence_duration_ms: Silence duration before turn ends
        """
        if not self.ws:
            self.logger.warning("grok_websocket_not_connected")
            return

        builder = GrokSessionConfigBuilder(
            agent=self.agent,
            prompt_builder=self._prompt_builder,
            timezone=self._timezone,
        )

        if voice:
            builder.with_voice(voice)

        if system_prompt:
            builder.with_instructions(
                base_prompt=system_prompt,
                include_realism=True,
                include_booking=self._enable_tools,
            )

        if any([turn_detection_mode, turn_detection_threshold, silence_duration_ms]):
            builder.with_turn_detection(
                mode=turn_detection_mode,
                threshold=turn_detection_threshold,
                silence_duration_ms=silence_duration_ms,
            )

        config = builder.build()
        if config:
            await self._send_event({"type": "session.update", "session": config})
            self.logger.info(
                "grok_session_reconfigured",
                updates=list(config.keys()),
            )

    async def send_greeting(self, greeting: str) -> None:
        """Send an initial greeting message.

        Args:
            greeting: The greeting text to speak
        """
        if not self.ws:
            self.logger.warning("grok_websocket_not_connected")
            return

        # Store the greeting for later use by trigger_initial_response
        self._pending_greeting = greeting

        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": greeting}],
            },
        }

        try:
            await self._send_event(event)
            await self._send_event(
                {
                    "type": "response.create",
                    "response": {"modalities": ["audio", "text"]},
                }
            )
            self.logger.info("grok_greeting_sent", greeting_length=len(greeting))
        except Exception as e:
            self.logger.exception("grok_send_greeting_error", error=str(e))

    async def trigger_initial_response(
        self,
        greeting: str | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Trigger the AI to start speaking with the initial greeting.

        For OUTBOUND calls, we use a pattern interrupt opener.
        For INBOUND calls, we use the configured greeting.

        Args:
            greeting: Optional greeting text override
            is_outbound: If True, this is an outbound call
        """
        if not self.ws:
            self.logger.warning("grok_websocket_not_connected")
            return

        if is_outbound:
            self.logger.info(
                "grok_outbound_call_opener",
                is_outbound=True,
                has_call_context=bool(self._call_context),
            )
            base_prompt = self._prompt_builder.get_outbound_opener_prompt()
            # Only add pattern interrupt realism cues for the default sales opener
            if "pattern interrupt" in base_prompt:
                prompt_text = (
                    base_prompt.replace(
                        "Sound a bit disappointed on 'hang up'.",
                        "Sigh right before 'hang up' - sound disappointed.",
                    )
                    + " Little laugh at the end."
                )
            else:
                prompt_text = base_prompt
        else:
            message = greeting
            if not message and hasattr(self, "_pending_greeting"):
                message = self._pending_greeting
            if not message and self.agent and self.agent.initial_greeting:
                message = self.agent.initial_greeting

            prompt_text = self._prompt_builder.get_inbound_greeting_prompt(message)

        try:
            event = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt_text}],
                },
            }
            await self._send_event(event)
            await self._send_event({"type": "response.create"})

            self.logger.info(
                "grok_initial_response_triggered",
                prompt_length=len(prompt_text),
                is_outbound=is_outbound,
            )
        except Exception as e:
            self.logger.exception("grok_trigger_response_error", error=str(e))

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to Grok.

        Args:
            audio_data: PCM audio data (16-bit, 16kHz)
        """
        await self._send_audio_base64(audio_data)

    async def receive_audio_stream(self) -> AsyncIterator[bytes]:
        """Stream audio responses from Grok.

        This generator continuously yields audio chunks from the Grok Realtime API.
        It does NOT break on response.done - instead it keeps listening for more
        responses as the conversation continues.

        Yields:
            PCM audio chunks (16-bit, 16kHz)
        """
        if not self.ws:
            self.logger.warning("grok_websocket_not_connected_for_audio_stream")
            return

        # Create audio stream manager
        stream_manager = AudioStreamManager(
            self.ws,
            config=AudioStreamConfig(log_interval=100, log_all_events=False),
        )

        # Build event context with callbacks
        context = EventContext(
            is_interrupted=lambda: self._is_interrupted,
            append_agent_transcript=self._append_agent_transcript_delta,
            add_user_transcript=self._add_user_transcript,
            handle_speech_started=self._handle_speech_started,
            handle_response_created=self._handle_response_created,
            handle_response_done=self._handle_response_done,
            handle_function_call=self._handle_function_call,
            cancel_response=self.cancel_response,
            check_dtmf_tags=self._check_and_send_dtmf_tags,
            process_ivr_transcript=self.process_ivr_transcript,
            handle_ivr_mode_switch=self._handle_ivr_mode_switch,
            ivr_detector=self._ivr_detector,
            ivr_mode=self._ivr_mode,
            agent_transcript=lambda: self._agent_transcript,
        )

        self.logger.info("grok_starting_audio_receive_stream")

        # Process events through the handler registry
        async for event in stream_manager.iter_events():
            result = await self._event_registry.dispatch(event, context)

            # Update stats for audio chunks
            for chunk in result.audio_chunks:
                stream_manager.stats.record_audio_chunk(len(chunk))
                yield chunk

            if not result.should_continue:
                break

        # Log final stats
        stream_manager.log_stream_end(len(self._transcript_entries))

    async def _handle_function_call(self, item: dict[str, Any]) -> None:
        """Handle a function call from Grok.

        Executes the tool callback and sends the result back to Grok.

        Args:
            item: Function call item from Grok response
        """
        call_id = item.get("call_id", "")
        function_name = item.get("name", "")
        arguments_str = item.get("arguments", "{}")

        self.logger.info(
            "grok_function_call_received",
            call_id=call_id,
            function_name=function_name,
            arguments=arguments_str[:100],
        )

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            arguments = {}
            self.logger.warning(
                "grok_function_call_invalid_arguments",
                arguments=arguments_str,
            )

        if not self._tool_callback:
            self.logger.warning(
                "grok_no_tool_callback_set",
                function_name=function_name,
            )
            await self.submit_tool_result(
                call_id,
                {"success": False, "error": "Tool execution not configured"},
            )
            return

        try:
            result = await asyncio.wait_for(
                self._tool_callback(call_id, function_name, arguments),
                timeout=TOOL_TIMEOUT_SECONDS,
            )

            self.logger.info(
                "grok_function_call_executed",
                call_id=call_id,
                function_name=function_name,
                success=result.get("success", False) if isinstance(result, dict) else True,
            )

            await self.submit_tool_result(call_id, result)

        except TimeoutError:
            self.logger.error(
                "grok_function_call_timeout",
                call_id=call_id,
                function_name=function_name,
                timeout_seconds=TOOL_TIMEOUT_SECONDS,
            )
            await self.submit_tool_result(
                call_id,
                {"success": False, "error": "Tool execution timed out. Please try again."},
            )

        except Exception as e:
            self.logger.exception(
                "grok_function_call_error",
                call_id=call_id,
                function_name=function_name,
                error=str(e),
            )
            await self.submit_tool_result(
                call_id,
                {"success": False, "error": str(e)},
            )

    async def submit_tool_result(
        self,
        call_id: str,
        result: dict[str, Any],
    ) -> None:
        """Submit tool execution result back to Grok.

        Args:
            call_id: The function call ID from Grok
            result: The result to send back
        """
        if not self.ws:
            self.logger.warning("grok_websocket_not_connected")
            return

        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "function_call_output",
                "call_id": call_id,
                "output": json.dumps(result),
            },
        }

        try:
            await self._send_event(event)
            self.logger.info("grok_tool_result_submitted", call_id=call_id)
            await self._send_event({"type": "response.create"})
        except Exception as e:
            self.logger.exception(
                "grok_submit_tool_result_error",
                call_id=call_id,
                error=str(e),
            )

    async def cancel_response(self) -> None:
        """Cancel the current response generation (barge-in handling)."""
        if not self.ws:
            return
        try:
            await self._send_event({"type": "response.cancel"})
            self.logger.info("grok_response_cancelled_on_interruption")
        except Exception as e:
            self.logger.exception("grok_cancel_response_error", error=str(e))

    async def inject_context(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = True,
    ) -> None:
        """Inject conversation context by updating system instructions.

        Args:
            contact_info: Contact information (name, company, etc.)
            offer_info: Offer/product information
            is_outbound: True if this is an outbound call
        """
        if not self.ws:
            self.logger.warning("grok_websocket_not_connected")
            return

        if not contact_info and not offer_info:
            return

        # Store context for use in trigger_initial_response
        self._call_context = {"contact": contact_info, "offer": offer_info}

        # Build full instructions with context
        builder = GrokSessionConfigBuilder(
            agent=self.agent,
            prompt_builder=self._prompt_builder,
            timezone=self._timezone,
        )

        config = builder.with_instructions(
            include_realism=True,
            include_booking=self._enable_tools,
            contact_info=contact_info,
            offer_info=offer_info,
            is_outbound=is_outbound,
        ).build()

        try:
            await self._send_event({"type": "session.update", "session": config})
            self.logger.info("grok_context_injected_to_instructions")
        except Exception as e:
            self.logger.exception("grok_inject_context_error", error=str(e))

    async def _send_event(self, event: dict[str, Any]) -> None:
        """Send event to WebSocket.

        Args:
            event: Event dictionary to send
        """
        if not self.ws:
            raise RuntimeError("Grok WebSocket not connected")

        try:
            await self.ws.send(json.dumps(event))
        except Exception as e:
            self.logger.exception("grok_send_event_error", error=str(e))

    # -------------------------------------------------------------------------
    # Response Handling Overrides
    # -------------------------------------------------------------------------

    def _handle_response_created(self) -> None:
        """Handle new response starting.

        Extends base class to reset DTMF handler scan position for new response.
        This is critical: the agent transcript resets per response, so the
        DTMF handler's incremental scan position must also reset.
        """
        # Call base class implementation
        super()._handle_response_created()

        # Reset DTMF handler scan position for the new response
        # This ensures DTMF tags in the new response will be detected
        self._dtmf_handler.reset_for_new_response()

    # -------------------------------------------------------------------------
    # IVR Detection Overrides
    # -------------------------------------------------------------------------

    def enable_ivr_detection(
        self,
        navigation_goal: str | None = None,
        loop_threshold: int = 2,
        ivr_config: dict[str, int] | None = None,
    ) -> None:
        """Enable IVR detection for this session.

        Args:
            navigation_goal: Goal for IVR navigation
            loop_threshold: Number of menu repeats before triggering loop action
            ivr_config: Optional IVR timing configuration with keys:
                - silence_duration_ms: Wait time for complete menus (default 3000)
                - post_dtmf_cooldown_ms: Cooldown after DTMF (default 3000)
                - menu_buffer_silence_ms: Buffer silence time (default 2000)
        """
        # Call base class implementation
        super().enable_ivr_detection(navigation_goal, loop_threshold, ivr_config)

        # Update DTMF handler cooldown if configured
        if ivr_config and "post_dtmf_cooldown_ms" in ivr_config:
            self._dtmf_handler._config.post_dtmf_cooldown_ms = ivr_config["post_dtmf_cooldown_ms"]
            self.logger.info(
                "dtmf_cooldown_configured",
                post_dtmf_cooldown_ms=ivr_config["post_dtmf_cooldown_ms"],
            )

        # Update IVR controller config with timing values
        if ivr_config:
            self._ivr_controller._config.ivr_silence_duration_ms = ivr_config.get(
                "silence_duration_ms", 3000
            )
            self._ivr_controller._config.post_dtmf_cooldown_ms = ivr_config.get(
                "post_dtmf_cooldown_ms", 3000
            )
            self._ivr_controller._config.menu_buffer_silence_ms = ivr_config.get(
                "menu_buffer_silence_ms", 2000
            )

        # Update IVR controller with detector reference
        self._ivr_controller.set_ivr_detector(
            self._ivr_detector,
            navigation_goal,
        )

    async def _handle_ivr_mode_switch(
        self,
        old_mode: "IVRMode",
        new_mode: "IVRMode",
    ) -> None:
        """Handle IVR mode switching with Grok-specific behavior.

        Args:
            old_mode: Previous IVR mode
            new_mode: New IVR mode
        """
        await self._ivr_controller.handle_mode_switch(old_mode, new_mode)

    async def _inject_ivr_context(self, ivr_prompt: str) -> None:
        """Inject IVR navigation context into session.

        Args:
            ivr_prompt: IVR navigation prompt to inject
        """
        if not self.ws:
            return

        ivr_text = f"[SYSTEM IVR NAVIGATION] {ivr_prompt}"
        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": ivr_text}],
            },
        }

        try:
            await self._send_event(event)
            self.logger.info("grok_ivr_context_injected")
        except Exception as e:
            self.logger.exception("grok_ivr_context_inject_error", error=str(e))

    # NOTE: _handle_ivr_dtmf() was removed intentionally to fix DTMF duplication.
    # DTMF sending is now handled exclusively by DTMFHandler.check_and_send()
    # which is called via _check_and_send_dtmf_tags().

    async def _check_and_send_dtmf_tags(self, text: str) -> None:
        """Check for DTMF tags in text and send them.

        Delegates to DTMF handler with incremental scanning.

        Args:
            text: Text to check for DTMF tags
        """
        await self._dtmf_handler.check_and_send(text)
