"""ElevenLabs Voice Agent - Hybrid architecture using Grok STT+LLM with ElevenLabs TTS.

This composite session provides:
- Grok Realtime API for Speech-to-Text and LLM (with tool calling for Cal.com)
- ElevenLabs for Text-to-Speech (expressive, high-quality voice output)

Architecture:
    Telnyx Audio In → Grok (STT+LLM+Tools) → Text → ElevenLabs TTS → Telnyx Audio Out
"""

import asyncio
import base64
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import structlog
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, ConnectionClosedError

from app.models.agent import Agent
from app.services.ai.elevenlabs_tts import ElevenLabsTTSSession, get_voice_id
from app.services.ai.voice_agent_base import VoiceAgentBase
from app.services.ai.voice_tools import GROK_BUILTIN_TOOLS, VOICE_BOOKING_TOOLS

logger = structlog.get_logger()


class ElevenLabsVoiceAgentSession(VoiceAgentBase):
    """Hybrid voice agent using Grok STT+LLM with ElevenLabs TTS.

    This session:
    - Connects to Grok Realtime API for speech recognition and LLM processing
    - Connects to ElevenLabs for text-to-speech synthesis
    - Routes input audio to Grok for STT
    - Intercepts Grok's text responses (ignoring Grok's audio)
    - Streams text to ElevenLabs for expressive voice synthesis
    - Returns ElevenLabs audio (ulaw_8000, ready for Telnyx)

    Key benefits:
    - Tool calling preserved (Cal.com booking, web search, X search)
    - ElevenLabs outputs ulaw_8000 directly (no conversion needed)
    - Access to 100+ ElevenLabs voices with rich expressiveness

    Note: This class uses grok_ws instead of ws from base class since it's a hybrid
    architecture with separate Grok and ElevenLabs connections.
    """

    SERVICE_NAME = "elevenlabs_voice_agent"
    GROK_BASE_URL = "wss://api.x.ai/v1/realtime"

    def __init__(
        self,
        xai_api_key: str,
        elevenlabs_api_key: str,
        agent: Agent | None = None,
        enable_tools: bool = False,
        timezone: str = "America/New_York",
    ) -> None:
        """Initialize hybrid voice agent session.

        Args:
            xai_api_key: xAI (Grok) API key for STT+LLM
            elevenlabs_api_key: ElevenLabs API key for TTS
            agent: Optional Agent model for configuration
            enable_tools: Enable Cal.com booking tools
            timezone: Timezone for date context (default: America/New_York)
        """
        super().__init__(agent, timezone)
        self.xai_api_key = xai_api_key
        self.elevenlabs_api_key = elevenlabs_api_key
        self._enable_tools = enable_tools

        # Grok WebSocket for STT+LLM (hybrid - uses grok_ws instead of base ws)
        self.grok_ws: ClientConnection | None = None

        # ElevenLabs TTS session
        self._tts_session: ElevenLabsTTSSession | None = None

        # Tool call handling (delegated to callback)
        self._tool_callback: Callable[[str, str, dict[str, Any]], Any] | None = None
        self._pending_function_calls: dict[str, dict[str, Any]] = {}

        # Audio output queue (ElevenLabs ulaw audio)
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()

        # Task management
        self._grok_receive_task: asyncio.Task[None] | None = None
        self._tts_receive_task: asyncio.Task[None] | None = None

        # Text buffer for streaming to TTS (accumulate before flushing)
        self._text_buffer = ""
        self._text_buffer_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[None] | None = None
        # Delay before flushing accumulated text (allows text to accumulate)
        # 400ms gives Grok time to complete natural sentence fragments
        self._flush_delay_ms = 400

    def set_tool_callback(
        self,
        callback: Callable[[str, str, dict[str, Any]], Any],
    ) -> None:
        """Set callback for tool execution.

        Args:
            callback: Async function(call_id, function_name, arguments) -> result
        """
        self._tool_callback = callback

    async def _buffer_text_for_tts(self, text: str) -> None:
        """Buffer text and schedule delayed flush to ElevenLabs.

        Text is accumulated in a buffer and flushed after a short delay,
        allowing multiple transcript deltas to be combined into a single
        TTS request. This prevents rapid successive flush calls that can
        cause ElevenLabs to drop audio.

        Args:
            text: Text fragment to buffer
        """
        if not text or not self._tts_session or not self._tts_session.is_connected():
            return

        async with self._text_buffer_lock:
            self._text_buffer += text
            buffered_text = self._text_buffer

            self.logger.debug(
                "text_buffered_for_tts",
                new_text=text[:30] if text else "",
                buffer_length=len(self._text_buffer),
            )

            # Smarter sentence boundary detection
            # Only flush immediately on clear sentence endings to avoid mid-word breaks
            # Grok's streaming doesn't align with sentence boundaries, so we need to be
            # more conservative. Only flush on ? or ! at end (usually sentence-final),
            # or period followed by significant content (not abbreviations like "Dr.")
            buffer_stripped = buffered_text.rstrip()

            # Check for clear sentence-ending punctuation
            # Avoid flushing on mid-sentence exclamations like "Hey! It's me..."
            # by requiring minimum buffer length and checking for continuation patterns
            ends_with_question_or_exclaim = buffer_stripped.endswith(("?", "!"))
            ends_with_period = buffer_stripped.endswith(".")

            # Only flush immediately if:
            # 1. Ends with ? or ! AND buffer is substantial (>50 chars = likely complete thought)
            # 2. Ends with period AND buffer is substantial AND doesn't look like abbreviation
            is_substantial = len(buffer_stripped) > 50
            should_flush_now = False

            if ends_with_question_or_exclaim and is_substantial:
                should_flush_now = True
            elif ends_with_period and is_substantial:
                # Check it's not an abbreviation (Mr. Mrs. Dr. etc.)
                # Abbreviations are typically short words followed by period
                words = buffer_stripped.split()
                if words:
                    last_word = words[-1]
                    # If last "word" is just 1-3 chars + period, likely abbreviation
                    is_likely_abbreviation = len(last_word) <= 4 and last_word[0].isupper()
                    should_flush_now = not is_likely_abbreviation

            if should_flush_now:
                # Cancel any pending flush task
                if self._flush_task and not self._flush_task.done():
                    self._flush_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._flush_task

                # Flush immediately on clear sentence end
                await self._flush_text_buffer()
            else:
                # Schedule delayed flush (cancel any existing timer)
                # The 400ms delay gives Grok time to complete natural phrases
                if self._flush_task and not self._flush_task.done():
                    self._flush_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await self._flush_task

                self._flush_task = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        """Flush text buffer after a short delay."""
        try:
            await asyncio.sleep(self._flush_delay_ms / 1000.0)
            async with self._text_buffer_lock:
                await self._flush_text_buffer()
        except asyncio.CancelledError:
            # Flush was cancelled (likely due to sentence-end or new text)
            pass

    async def _flush_text_buffer(self) -> None:
        """Flush accumulated text to ElevenLabs TTS.

        Note: Must be called with _text_buffer_lock held.
        """
        if not self._text_buffer or not self._tts_session:
            return

        text_to_send = self._text_buffer
        self._text_buffer = ""

        try:
            await self._tts_session.send_text(text_to_send, flush=True)
            self.logger.debug(
                "transcript_flushed_to_elevenlabs",
                text_preview=text_to_send[:50] if text_to_send else "",
                text_length=len(text_to_send),
            )
        except Exception as e:
            self.logger.exception("flush_text_buffer_error", error=str(e))

    async def _flush_text_buffer_final(self) -> None:
        """Flush any remaining text in buffer (e.g., on response complete)."""
        # Cancel any pending flush task
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        async with self._text_buffer_lock:
            await self._flush_text_buffer()

    async def connect(self) -> bool:
        """Connect to both Grok and ElevenLabs.

        Returns:
            True if both connections successful, False otherwise
        """
        self.logger.info("connecting_to_hybrid_voice_agent")

        try:
            # Connect to Grok Realtime API
            self.logger.info("connecting_to_grok_stt_llm")
            self.grok_ws = await connect(
                self.GROK_BASE_URL,
                additional_headers={
                    "Authorization": f"Bearer {self.xai_api_key}",
                },
            )
            self.logger.info("connected_to_grok")

            # Determine ElevenLabs voice ID
            voice_id = "gJx1vCzNCD1EQHT212Ls"  # Default: Ava
            if self.agent and self.agent.voice_id:
                voice_id = get_voice_id(self.agent.voice_id)

            # Connect to ElevenLabs TTS
            self.logger.info("connecting_to_elevenlabs_tts", voice_id=voice_id)
            self._tts_session = ElevenLabsTTSSession(
                api_key=self.elevenlabs_api_key,
                voice_id=voice_id,
            )

            if not await self._tts_session.connect(output_format="ulaw_8000"):
                self.logger.error("elevenlabs_connection_failed")
                await self._cleanup_grok()
                return False

            self.logger.info("connected_to_elevenlabs")

            # Configure Grok session (text output only - we ignore audio)
            await self._configure_grok_session()

            # Start background tasks
            self._grok_receive_task = asyncio.create_task(self._receive_from_grok())
            self._tts_receive_task = asyncio.create_task(self._receive_from_tts())

            self.logger.info("hybrid_voice_agent_connected")
            return True

        except Exception as e:
            self.logger.exception("hybrid_connection_failed", error=str(e))
            await self.disconnect()
            return False

    async def disconnect(self) -> None:
        """Disconnect from both Grok and ElevenLabs."""
        self.logger.info("disconnecting_hybrid_voice_agent")

        # Cancel background tasks
        if self._grok_receive_task and not self._grok_receive_task.done():
            self._grok_receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._grok_receive_task

        if self._tts_receive_task and not self._tts_receive_task.done():
            self._tts_receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tts_receive_task

        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task

        # Disconnect ElevenLabs
        if self._tts_session:
            await self._tts_session.disconnect()
            self._tts_session = None

        # Disconnect Grok
        await self._cleanup_grok()

        # Signal end of audio stream
        await self._audio_queue.put(None)

        self.logger.info("hybrid_voice_agent_disconnected")

    async def _cleanup_grok(self) -> None:
        """Clean up Grok WebSocket connection."""
        if self.grok_ws:
            try:
                await self.grok_ws.close()
            except Exception as e:
                self.logger.exception("grok_disconnect_error", error=str(e))
            self.grok_ws = None

    async def _configure_grok_session(self) -> None:
        """Configure Grok session for text output (we handle TTS separately)."""
        if not self.grok_ws:
            return

        # Build full prompt using the prompt builder
        enhanced_prompt = self._prompt_builder.build_full_prompt(
            include_realism=True,
            include_booking=self._enable_tools,
        )

        # Build session config - request TEXT output (we handle TTS)
        session_config: dict[str, Any] = {
            "instructions": enhanced_prompt,
            "audio": {
                "input": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    }
                },
                # Still request audio output so Grok does STT properly
                # but we'll ignore the audio and use the transcript
                "output": {
                    "format": {
                        "type": "audio/pcm",
                        "rate": 24000,
                    }
                },
            },
            "turn_detection": {
                "type": self.agent.turn_detection_mode
                if self.agent and self.agent.turn_detection_mode
                else "server_vad",
                "threshold": 0.8,
                "prefix_padding_ms": 500,
                "silence_duration_ms": 1000,
            },
        }

        # Build tools list
        tools: list[dict[str, Any]] = []

        agent_enabled_tools = (
            self.agent.enabled_tools if self.agent and self.agent.enabled_tools else []
        )

        if "web_search" in agent_enabled_tools:
            tools.append(GROK_BUILTIN_TOOLS["web_search"])
            self.logger.info("grok_web_search_enabled")

        if "x_search" in agent_enabled_tools:
            tools.append(GROK_BUILTIN_TOOLS["x_search"])
            self.logger.info("grok_x_search_enabled")

        # Add Cal.com booking tools if enabled and configured
        if self._enable_tools:
            tools.extend(VOICE_BOOKING_TOOLS)
            self.logger.info("booking_tools_enabled", tool_count=len(VOICE_BOOKING_TOOLS))

        if tools:
            session_config["tools"] = tools

        config = {
            "type": "session.update",
            "session": session_config,
        }

        await self._send_to_grok(config)
        self.logger.info("grok_session_configured_for_elevenlabs_tts")

    async def configure_session(
        self,
        voice: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        turn_detection_mode: str | None = None,
        turn_detection_threshold: float | None = None,
        silence_duration_ms: int | None = None,
    ) -> None:
        """Reconfigure the session.

        Note: Voice changes require reconnecting to ElevenLabs.
        For simplicity, voice is set at connection time based on agent config.
        """
        if not self.grok_ws:
            self.logger.warning("grok_not_connected")
            return

        session_config: dict[str, Any] = {}

        if system_prompt:
            # Build enhanced prompt using prompt builder
            enhanced = self._prompt_builder.build_full_prompt(
                base_prompt=system_prompt,
                include_realism=True,
                include_booking=self._enable_tools,
            )
            session_config["instructions"] = enhanced

        if any([turn_detection_mode, turn_detection_threshold, silence_duration_ms]):
            turn_detection: dict[str, Any] = {"type": turn_detection_mode or "server_vad"}
            if turn_detection_threshold is not None:
                turn_detection["threshold"] = turn_detection_threshold
            if silence_duration_ms is not None:
                turn_detection["silence_duration_ms"] = silence_duration_ms
            turn_detection["prefix_padding_ms"] = 500
            session_config["turn_detection"] = turn_detection

        if session_config:
            config = {
                "type": "session.update",
                "session": session_config,
            }
            await self._send_to_grok(config)
            self.logger.info("session_reconfigured", updates=list(session_config.keys()))

    async def trigger_initial_response(
        self, greeting: str | None = None, is_outbound: bool = False
    ) -> None:
        """Trigger the AI to start speaking with an initial greeting.

        Args:
            greeting: Optional greeting text
            is_outbound: If True, this is an outbound call
        """
        if not self.grok_ws:
            self.logger.warning("grok_not_connected")
            return

        # Use provided greeting or agent's initial greeting
        message = greeting
        if not message and self.agent and self.agent.initial_greeting:
            message = self.agent.initial_greeting

        try:
            # Build prompt using prompt builder
            if is_outbound:
                prompt_text = self._prompt_builder.get_outbound_opener_prompt()
            else:
                prompt_text = self._prompt_builder.get_inbound_greeting_prompt(message)

            event = {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": prompt_text,
                        }
                    ],
                },
            }

            await self._send_to_grok(event)
            await self._send_to_grok({"type": "response.create"})

            self.logger.info(
                "initial_response_triggered",
                has_greeting=bool(message),
            )

        except Exception as e:
            self.logger.exception("trigger_response_error", error=str(e))

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to Grok for STT.

        Args:
            audio_data: PCM audio data (16-bit, 24kHz)
        """
        if not self.grok_ws:
            self.logger.warning("grok_not_connected")
            return

        try:
            encoded = base64.b64encode(audio_data).decode("utf-8")
            event = {
                "type": "input_audio_buffer.append",
                "audio": encoded,
            }
            await self._send_to_grok(event)
        except ConnectionClosedError as e:
            # Connection died - set to None to prevent further send attempts
            self.logger.warning("grok_connection_closed", error=str(e))
            self.grok_ws = None
        except Exception as e:
            self.logger.exception("send_audio_error", error=str(e))

    # Note: Can't use base _send_audio_base64 since this uses grok_ws not ws

    async def receive_audio_stream(self) -> AsyncIterator[bytes]:
        """Stream audio responses from ElevenLabs TTS.

        Yields:
            ulaw_8000 audio chunks (ready for Telnyx, no conversion needed)
        """
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                break
            yield chunk

    async def _receive_from_grok(self) -> None:  # noqa: PLR0912, PLR0915
        """Receive events from Grok and route transcripts to ElevenLabs TTS."""
        if not self.grok_ws:
            return

        responses_completed = 0

        try:
            self.logger.info("starting_grok_receive_loop")

            async for message in self.grok_ws:
                try:
                    event = json.loads(message)
                except json.JSONDecodeError as e:
                    self.logger.warning("invalid_json_from_grok", error=str(e))
                    continue

                event_type = event.get("type", "")

                # Intercept audio transcript and buffer for ElevenLabs
                if event_type == "response.output_audio_transcript.delta":
                    # Skip transcript if we're in interrupted state (barge-in handling)
                    # This prevents sending transcript from cancelled response to TTS
                    if self._is_interrupted:
                        continue

                    transcript = event.get("delta", "")
                    # Buffer transcript for ElevenLabs TTS (will flush on sentence end or delay)
                    if transcript:
                        await self._buffer_text_for_tts(transcript)

                # Ignore Grok's audio output - we use ElevenLabs TTS instead
                elif event_type in ("response.audio.delta", "response.output_audio.delta"):
                    # Explicitly ignoring Grok audio - ElevenLabs handles TTS
                    pass

                elif event_type == "response.done":
                    responses_completed += 1
                    response_data = event.get("response", {})
                    response_status = response_data.get("status", "")

                    # Flush any remaining buffered text to ElevenLabs
                    await self._flush_text_buffer_final()

                    # Handle response completion using base class
                    self._handle_response_done(response_status)

                    self.logger.info(
                        "grok_response_completed",
                        response_num=responses_completed,
                    )

                elif event_type == "response.output_item.done":
                    item = event.get("item", {})
                    if item.get("type") == "function_call":
                        await self._handle_function_call(item)

                elif event_type == "input_audio_buffer.speech_started":
                    # Handle barge-in using base class helper
                    self._handle_speech_started()

                    # Cancel response immediately and clear audio queue
                    await self.cancel_response()

                elif event_type == "input_audio_buffer.speech_stopped":
                    self.logger.debug("user_speech_stopped")

                elif event_type == "response.created":
                    # Handle new response - resets interrupted flag using base class
                    self._handle_response_created()

                elif event_type == "session.created":
                    session = event.get("session", {})
                    self.logger.info(
                        "grok_session_created",
                        session_id=session.get("id"),
                        model=session.get("model"),
                    )

                elif event_type == "error":
                    error = event.get("error", {})
                    self.logger.error(
                        "grok_error",
                        error_type=error.get("type"),
                        error_message=error.get("message"),
                    )

                else:
                    self.logger.debug("grok_event", event_type=event_type)

        except ConnectionClosed as e:
            self.logger.warning(
                "grok_connection_closed",
                code=e.code,
                reason=e.reason,
            )
        except asyncio.CancelledError:
            self.logger.info("grok_receive_cancelled")
        except Exception as e:
            self.logger.exception("grok_receive_error", error=str(e))

    async def _receive_from_tts(self) -> None:
        """Receive audio from ElevenLabs TTS and queue for output."""
        if not self._tts_session:
            return

        try:
            self.logger.info("starting_tts_receive_loop")
            async for audio_chunk in self._tts_session.receive_audio_stream():
                await self._audio_queue.put(audio_chunk)
        except asyncio.CancelledError:
            self.logger.info("tts_receive_cancelled")
        except Exception as e:
            self.logger.exception("tts_receive_error", error=str(e))

    async def _handle_function_call(self, item: dict[str, Any]) -> None:
        """Handle a function call from Grok."""
        call_id = item.get("call_id", "")
        function_name = item.get("name", "")
        arguments_str = item.get("arguments", "{}")

        self.logger.info(
            "function_call_received",
            call_id=call_id,
            function_name=function_name,
        )

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError:
            arguments = {}

        if not self._tool_callback:
            self.logger.warning("no_tool_callback_set", function_name=function_name)
            await self.submit_tool_result(
                call_id,
                {"success": False, "error": "Tool execution not configured"},
            )
            return

        try:
            result = await self._tool_callback(call_id, function_name, arguments)
            self.logger.info(
                "function_call_executed",
                call_id=call_id,
                function_name=function_name,
                success=result.get("success", False) if isinstance(result, dict) else True,
            )
            await self.submit_tool_result(call_id, result)
        except Exception as e:
            self.logger.exception("function_call_error", error=str(e))
            await self.submit_tool_result(
                call_id,
                {"success": False, "error": str(e)},
            )

    async def submit_tool_result(
        self,
        call_id: str,
        result: dict[str, Any],
    ) -> None:
        """Submit tool execution result back to Grok."""
        if not self.grok_ws:
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
            await self._send_to_grok(event)
            await self._send_to_grok({"type": "response.create"})
            self.logger.info("tool_result_submitted", call_id=call_id)
        except Exception as e:
            self.logger.exception("submit_tool_result_error", error=str(e))

    async def cancel_response(self) -> None:
        """Cancel the current Grok response generation (barge-in handling).

        This is called when the user starts speaking during AI response
        to immediately stop Grok's generation. Also clears the TTS text buffer
        and audio queue.
        """
        if not self.grok_ws:
            return
        try:
            await self._send_to_grok({"type": "response.cancel"})
            self.logger.info("response_cancelled_on_interruption")

            # Cancel any pending text flush and clear the text buffer
            if self._flush_task and not self._flush_task.done():
                self._flush_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._flush_task
            async with self._text_buffer_lock:
                if self._text_buffer:
                    self.logger.debug(
                        "clearing_text_buffer_on_interruption",
                        buffer_length=len(self._text_buffer),
                    )
                    self._text_buffer = ""

            # Clear the TTS audio queue
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self.logger.info("tts_audio_queue_cleared")
        except Exception as e:
            self.logger.exception("cancel_response_error", error=str(e))

    async def inject_context(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = True,
    ) -> None:
        """Inject conversation context.

        Args:
            contact_info: Contact information (name, company, etc.)
            offer_info: Offer/product information
            is_outbound: True if this is an outbound call, False for inbound
        """
        if not self.grok_ws:
            return

        if not contact_info and not offer_info:
            return

        # Store context for trigger_initial_response
        self._call_context = {
            "contact": contact_info,
            "offer": offer_info,
        }

        # Build full instructions using prompt builder
        enhanced_prompt = self._prompt_builder.build_full_prompt(
            include_realism=True,
            include_booking=self._enable_tools,
            contact_info=contact_info,
            offer_info=offer_info,
            is_outbound=is_outbound,
        )

        config = {
            "type": "session.update",
            "session": {
                "instructions": enhanced_prompt,
            },
        }

        try:
            await self._send_to_grok(config)
            self.logger.info("context_injected")
        except Exception as e:
            self.logger.exception("inject_context_error", error=str(e))

    async def _send_to_grok(self, event: dict[str, Any]) -> None:
        """Send event to Grok WebSocket."""
        if not self.grok_ws:
            raise RuntimeError("Grok WebSocket not connected")

        try:
            await self.grok_ws.send(json.dumps(event))
        except ConnectionClosedError as e:
            # Mark connection as dead to prevent further send attempts
            self.grok_ws = None
            self.logger.warning("grok_connection_closed_on_send", error=str(e))
            raise
        except Exception as e:
            self.logger.exception("send_to_grok_error", error=str(e))
            raise

    def is_connected(self) -> bool:
        """Check if both connections are active."""
        grok_connected = self.grok_ws is not None
        tts_connected = self._tts_session is not None and self._tts_session.is_connected()
        return grok_connected and tts_connected
