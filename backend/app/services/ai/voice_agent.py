"""OpenAI Realtime API integration for voice conversations."""

import asyncio
import base64
import binascii
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.core.metrics import openai_realtime_latency_ms
from app.models.agent import Agent
from app.services.ai.voice_agent_base import VoiceAgentBase

logger = structlog.get_logger()


class VoiceAgentSession(VoiceAgentBase):
    """OpenAI Realtime API session for voice conversations.

    Manages:
    - WebSocket connection to OpenAI Realtime API
    - Audio streaming and format conversion
    - Session configuration and context injection
    - Conversation state management

    Inherits from VoiceAgentBase for:
    - Transcript tracking
    - Interruption handling
    - Prompt building via VoicePromptBuilder
    """

    SERVICE_NAME = "openai_voice_agent"
    BASE_URL = "wss://api.openai.com/v1/realtime"
    MODEL = "gpt-realtime"

    def __init__(self, api_key: str, agent: Agent | None = None) -> None:
        """Initialize voice agent session.

        Args:
            api_key: OpenAI API key
            agent: Optional Agent model for configuration
        """
        super().__init__(agent)
        self.api_key = api_key
        self._connection_task: asyncio.Task[None] | None = None
        # Monotonic timestamp of the most recent response.create event we
        # sent. Cleared once response.created is observed so we measure
        # request → ack latency for each turn without double-counting.
        self._pending_response_create_at: float | None = None

    async def connect(self) -> bool:
        """Connect to OpenAI Realtime API.

        Returns:
            True if successful, False otherwise
        """
        url = f"{self.BASE_URL}?model={self.MODEL}"
        self.logger.info(
            "========== CONNECTING TO OPENAI REALTIME API ==========",
            url=url,
            model=self.MODEL,
            api_key_prefix=self.api_key[:10] + "..." if self.api_key else "None",
        )

        try:
            self.ws = await connect(
                url,
                additional_headers={
                    "Authorization": f"Bearer {self.api_key}",
                },
            )

            self.logger.info(
                "websocket_connected_to_openai",
                ws_connected=self.ws is not None,
            )

            # Send session configuration
            self.logger.info("configuring_openai_session")
            await self._configure_session()
            self.logger.info("openai_session_configured")

            return True
        except InvalidStatus as e:
            self.logger.error(
                "openai_connection_rejected",
                status_code=e.response.status_code if hasattr(e, "response") else "unknown",
                error=str(e),
                hint="Check if API key is valid",
            )
            return False
        except Exception as e:
            self.logger.exception(
                "openai_connection_failed",
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def disconnect(self) -> None:
        """Disconnect from OpenAI Realtime API."""
        await self._disconnect_ws()

    async def _configure_session(self) -> None:
        """Configure the Realtime session with agent settings.

        Uses g711_ulaw at 8kHz - this matches Telnyx's format directly,
        eliminating the need for audio conversion (lower latency, no quality loss).
        """
        # Build full prompt using the prompt builder
        instructions = self._prompt_builder.build_full_prompt(
            include_realism=False,
            include_booking=False,
        )

        config: dict[str, Any] = {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": instructions,
                "voice": self.agent.voice_id if self.agent else "alloy",
                # g711_ulaw at 8kHz - matches Telnyx format directly (no conversion!)
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
                "turn_detection": {
                    "type": self.agent.turn_detection_mode
                    if self.agent and self.agent.turn_detection_mode
                    else "server_vad",
                    # Lower threshold = more sensitive to speech detection
                    "threshold": 0.5,
                    # More padding before speech starts (captures audio before VAD triggers)
                    "prefix_padding_ms": 800,
                    # Wait for silence before responding
                    "silence_duration_ms": 700,
                },
                # Enable noise reduction to reduce static from caller environment
                "input_audio_noise_reduction": {"type": "near_field"},
                "temperature": 0.8,
            },
        }

        await self._send_event(config)
        self.logger.info("session_configured", audio_format="g711_ulaw")

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

        This method allows updating session settings after connection.

        Args:
            voice: Voice ID (alloy, shimmer, nova, etc.)
            system_prompt: System instructions for the assistant
            temperature: Response temperature (0.0-1.0)
            turn_detection_mode: Turn detection type (server_vad, none)
            turn_detection_threshold: VAD threshold (0.0-1.0)
            silence_duration_ms: Silence duration before turn ends
        """
        if not self.ws:
            self.logger.warning("websocket_not_connected")
            return

        session_config: dict[str, Any] = {
            # CRITICAL: Always include modalities and audio formats to prevent them being cleared
            # Must use g711_ulaw to match Telnyx format - pcm16 would break audio!
            "modalities": ["text", "audio"],
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
        }

        if voice:
            session_config["voice"] = voice

        if system_prompt:
            # Build enhanced prompt using prompt builder
            enhanced_prompt = self._prompt_builder.build_full_prompt(
                base_prompt=system_prompt,
                include_realism=False,
                include_booking=False,
            )
            session_config["instructions"] = enhanced_prompt

        if temperature is not None:
            session_config["temperature"] = temperature

        # Configure turn detection
        if any([turn_detection_mode, turn_detection_threshold, silence_duration_ms]):
            turn_detection: dict[str, Any] = {"type": turn_detection_mode or "server_vad"}
            if turn_detection_threshold is not None:
                turn_detection["threshold"] = turn_detection_threshold
            if silence_duration_ms is not None:
                turn_detection["silence_duration_ms"] = silence_duration_ms
            turn_detection["prefix_padding_ms"] = 800
            session_config["turn_detection"] = turn_detection

        if session_config:
            config = {
                "type": "session.update",
                "session": session_config,
            }
            await self._send_event(config)
            self.logger.info("session_reconfigured", updates=list(session_config.keys()))

    async def send_greeting(self, greeting: str) -> None:
        """Send an initial greeting message.

        This sends a text message that will be spoken by the assistant.

        Args:
            greeting: The greeting text to speak
        """
        if not self.ws:
            self.logger.warning("websocket_not_connected")
            return

        # Store the greeting for later use by trigger_initial_response
        self._pending_greeting = greeting

        # Create a conversation item with the greeting as assistant message
        # and trigger response generation
        event = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": greeting,
                    }
                ],
            },
        }

        try:
            await self._send_event(event)

            # Request the assistant to respond (which will speak the greeting)
            response_event = {
                "type": "response.create",
                "response": {
                    "modalities": ["audio", "text"],
                },
            }
            await self._send_event(response_event)

            self.logger.info("greeting_sent", greeting_length=len(greeting))
        except Exception as e:
            self.logger.exception("send_greeting_error", error=str(e))

    async def trigger_initial_response(
        self,
        greeting: str | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Trigger the AI to start speaking with the initial greeting.

        Call this after the audio stream is established to initiate the conversation.
        Creates a user message prompting the AI to greet, then triggers response.create().

        For OUTBOUND calls, we tell the AI it initiated the call and use a pattern
        interrupt opener to be honest and disarming.

        Args:
            greeting: Optional greeting text. If not provided, uses the pending greeting
                     from send_greeting or agent's initial greeting.
            is_outbound: If True, this is an outbound call and we use a pattern interrupt
                        opener instead of waiting for the caller.
        """
        self.logger.info(
            "========== TRIGGER INITIAL RESPONSE ==========",
            ws_connected=self.ws is not None,
            ws_is_connected=self.is_connected(),
            provided_greeting=greeting[:50] if greeting else None,
        )

        if not self.ws:
            self.logger.error(
                "cannot_trigger_response_ws_not_connected",
                hint="WebSocket connection to OpenAI was not established",
            )
            return

        # For OUTBOUND calls: Use a pattern interrupt opener
        # Be honest and disarming - give them control
        if is_outbound:
            self.logger.info(
                "openai_outbound_call_pattern_interrupt",
                is_outbound=True,
                has_call_context=hasattr(self, "_call_context") and bool(self._call_context),
            )
            prompt_text = self._prompt_builder.get_outbound_opener_prompt()
        else:
            # For INBOUND calls: Use configured greeting or default
            # Use provided greeting, or pending greeting, or agent's initial greeting
            message = greeting
            if not message and hasattr(self, "_pending_greeting"):
                message = self._pending_greeting
                msg_len = len(message) if message else 0
                self.logger.debug("using_pending_greeting", greeting_length=msg_len)
            if not message and self.agent and self.agent.initial_greeting:
                message = self.agent.initial_greeting
                msg_len = len(message) if message else 0
                self.logger.debug("using_agent_initial_greeting", greeting_length=msg_len)

            prompt_text = self._prompt_builder.get_inbound_greeting_prompt(message)

        try:
            self.logger.info(
                "sending_greeting_prompt",
                prompt_text=prompt_text[:100],
                has_custom_greeting=bool(message if not is_outbound else False),
                is_outbound=is_outbound,
            )

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

            await self._send_event(event)
            self.logger.info(
                "greeting_conversation_item_created",
                has_greeting=bool(message),
                greeting_length=len(message) if message else 0,
            )

            # Trigger response generation with audio modality
            # This tells OpenAI to respond to the conversation item we just created
            self.logger.info("sending_response_create_event", modalities=["text", "audio"])
            await self._send_event(
                {
                    "type": "response.create",
                    "response": {
                        "modalities": ["text", "audio"],
                    },
                }
            )
            self.logger.info(
                "response_create_sent_successfully",
                hint="AI should now generate audio response",
            )

        except Exception as e:
            self.logger.exception(
                "trigger_response_error",
                error=str(e),
                error_type=type(e).__name__,
            )

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        """Send audio chunk to OpenAI.

        Args:
            audio_data: PCM audio data (16-bit, 16kHz)
        """
        await self._send_audio_base64(audio_data)

    async def receive_audio_stream(self) -> AsyncIterator[bytes]:  # noqa: PLR0912, PLR0915
        """Stream audio responses from OpenAI.

        This generator continuously yields audio chunks from the OpenAI Realtime API.
        It does NOT break on response.done - instead it keeps listening for more
        responses as the conversation continues.

        Yields:
            PCM audio chunks (16-bit, 16kHz)
        """
        self.logger.info(
            "========== STARTING AUDIO RECEIVE STREAM ==========",
            ws_connected=self.ws is not None,
            ws_is_connected=self.is_connected(),
        )

        if not self.ws:
            self.logger.error(
                "cannot_receive_audio_ws_not_connected",
                hint="OpenAI WebSocket connection was not established",
            )
            return

        audio_chunks_received = 0
        total_audio_bytes = 0
        responses_completed = 0

        try:
            self.logger.info(
                "entering_websocket_receive_loop",
                ws_is_connected=self.is_connected(),
            )

            async for message in self.ws:
                # Parse JSON with error handling to prevent stream crash
                try:
                    event = json.loads(message)
                except json.JSONDecodeError as e:
                    self.logger.warning(
                        "invalid_json_from_openai",
                        error=str(e),
                        message_preview=str(message)[:100],
                    )
                    continue

                event_type = event.get("type", "")

                if event_type == "response.audio.delta":
                    # Skip audio if we're in interrupted state (barge-in handling)
                    # OpenAI continues sending audio for a brief period after cancel
                    if self._is_interrupted:
                        continue

                    # Audio chunk received
                    audio_data = event.get("delta", "")
                    if audio_data:
                        # Decode base64 with error handling
                        try:
                            decoded = base64.b64decode(audio_data)
                        except (binascii.Error, ValueError) as e:
                            self.logger.warning(
                                "invalid_base64_audio_from_openai",
                                error=str(e),
                            )
                            continue

                        audio_chunks_received += 1
                        total_audio_bytes += len(decoded)

                        # Log first chunk and periodically
                        if audio_chunks_received == 1:
                            self.logger.info(
                                "first_audio_chunk_received",
                                chunk_bytes=len(decoded),
                            )
                        elif audio_chunks_received % 100 == 0:
                            self.logger.debug(
                                "audio_stream_progress",
                                chunks=audio_chunks_received,
                                total_bytes=total_audio_bytes,
                                responses=responses_completed,
                            )

                        yield decoded

                elif event_type == "response.audio_transcript.delta":
                    # Agent's speech transcript (what the AI is saying)
                    transcript = event.get("delta", "")
                    if transcript:
                        self._append_agent_transcript_delta(transcript)
                        self.logger.debug("audio_transcript_chunk", text=transcript[:50])

                elif event_type == "conversation.item.input_audio_transcription.completed":
                    # User's speech transcript (what the human said)
                    user_text = event.get("transcript", "")
                    if user_text:
                        self._add_user_transcript(user_text)

                elif event_type == "response.text.delta":
                    # Text response (not audio) - this means audio is NOT being generated
                    text = event.get("delta", "")
                    self.logger.warning(
                        "text_delta_received_not_audio",
                        text_preview=text[:100] if text else "",
                        text_length=len(text) if text else 0,
                    )

                elif event_type == "response.text.done":
                    text = event.get("text", "")
                    self.logger.warning(
                        "text_response_done_not_audio",
                        text_preview=text[:200] if text else "",
                        text_length=len(text) if text else 0,
                    )

                elif event_type == "response.done":
                    # Response complete - but DON'T break!
                    # Keep listening for more responses in the conversation
                    responses_completed += 1
                    response = event.get("response", {})
                    usage = response.get("usage", {})
                    output = response.get("output", [])
                    response_status = response.get("status", "")
                    output_summary = [
                        {
                            "type": o.get("type"),
                            "role": o.get("role"),
                            "content_types": [c.get("type") for c in o.get("content", [])],
                        }
                        for o in output
                    ]

                    # Handle response completion - saves transcript and resets flags
                    self._handle_response_done(response_status)

                    self.logger.info(
                        "response_completed",
                        response_num=responses_completed,
                        response_id=response.get("id"),
                        status=response.get("status"),
                        status_details=response.get("status_details"),
                        modalities=response.get("modalities"),
                        output_count=len(output),
                        output_summary=output_summary,
                        total_tokens=usage.get("total_tokens"),
                        input_tokens=usage.get("input_tokens"),
                        output_tokens=usage.get("output_tokens"),
                        total_audio_chunks=audio_chunks_received,
                        total_audio_bytes=total_audio_bytes,
                    )
                    # Continue listening for next response

                elif event_type == "input_audio_buffer.speech_started":
                    # Handle barge-in using base class helper
                    self._handle_speech_started()

                    # Cancel response immediately - production pattern from VideoSDK/LiveKit
                    await self.cancel_response()

                elif event_type == "input_audio_buffer.speech_stopped":
                    self.logger.debug("user_speech_stopped")

                elif event_type == "input_audio_buffer.committed":
                    self.logger.debug("audio_buffer_committed")

                elif event_type == "conversation.item.created":
                    item = event.get("item", {})
                    self.logger.debug(
                        "conversation_item_created",
                        item_type=item.get("type"),
                        role=item.get("role"),
                    )

                elif event_type == "response.created":
                    # Observe request → ack latency for the matching
                    # response.create event (if any) before resetting state.
                    if self._pending_response_create_at is not None:
                        openai_realtime_latency_ms.observe(
                            (time.monotonic() - self._pending_response_create_at) * 1000.0
                        )
                        self._pending_response_create_at = None
                    # Handle new response - resets interrupted flag using base class
                    self._handle_response_created()

                    response = event.get("response", {})
                    self.logger.info(
                        "response_created",
                        response_id=response.get("id"),
                        status=response.get("status"),
                        modalities=response.get("modalities"),
                        output=response.get("output"),
                    )

                elif event_type == "response.output_item.added":
                    item = event.get("item", {})
                    self.logger.info(
                        "response_output_item_added",
                        item_id=item.get("id"),
                        item_type=item.get("type"),
                        role=item.get("role"),
                        content_types=[c.get("type") for c in item.get("content", [])],
                    )

                elif event_type == "response.content_part.added":
                    part = event.get("part", {})
                    self.logger.info(
                        "response_content_part_added",
                        part_type=part.get("type"),
                        content_index=event.get("content_index"),
                    )

                elif event_type == "session.created":
                    session = event.get("session", {})
                    self.logger.info(
                        "session_created",
                        session_id=session.get("id"),
                        model=session.get("model"),
                        modalities=session.get("modalities"),
                        voice=session.get("voice"),
                        input_audio_format=session.get("input_audio_format"),
                        output_audio_format=session.get("output_audio_format"),
                    )

                elif event_type == "session.updated":
                    session = event.get("session", {})
                    self.logger.info(
                        "session_updated",
                        modalities=session.get("modalities"),
                        voice=session.get("voice"),
                        input_audio_format=session.get("input_audio_format"),
                        output_audio_format=session.get("output_audio_format"),
                    )

                elif event_type == "error":
                    error = event.get("error", {})
                    self.logger.error(
                        "openai_realtime_error",
                        error_type=error.get("type"),
                        error_message=error.get("message"),
                        error_code=error.get("code"),
                    )
                    # Don't break - some errors are recoverable

                elif event_type == "rate_limits.updated":
                    self.logger.debug(
                        "rate_limits_updated",
                        limits=event.get("rate_limits", []),
                    )

                else:
                    # Log unknown event types for debugging
                    self.logger.debug("openai_event", event_type=event_type)

        except ConnectionClosed as e:
            self.logger.warning(
                "openai_websocket_closed",
                code=e.code,
                reason=e.reason,
                chunks_received=audio_chunks_received,
            )
        except Exception as e:
            self.logger.exception(
                "receive_audio_stream_error",
                error=str(e),
                chunks_received=audio_chunks_received,
            )

        # Log stream end stats
        self.logger.info(
            "audio_stream_ended",
            total_chunks=audio_chunks_received,
            total_bytes=total_audio_bytes,
            total_responses=responses_completed,
            transcript_entry_count=len(self._transcript_entries),
        )

    async def inject_context(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> None:
        """Inject conversation context by updating system instructions.

        This updates the session instructions to include contact and offer
        context, rather than injecting as user messages which confuses the AI.

        Args:
            contact_info: Contact information (name, company, etc.)
            offer_info: Offer/product information
            is_outbound: If True, this is an outbound call (AI initiated)
        """
        if not self.ws:
            self.logger.warning("websocket_not_connected")
            return

        if not contact_info and not offer_info:
            return

        # Store context for use in trigger_initial_response
        self._call_context = {
            "contact": contact_info,
            "offer": offer_info,
        }

        # Build full instructions using prompt builder
        full_instructions = self._prompt_builder.build_full_prompt(
            include_realism=False,
            include_booking=False,
            contact_info=contact_info,
            offer_info=offer_info,
            is_outbound=is_outbound,
        )

        # Send session update with full context
        config: dict[str, Any] = {
            "type": "session.update",
            "session": {
                "instructions": full_instructions,
                # CRITICAL: Always include modalities and audio formats
                "modalities": ["text", "audio"],
                "input_audio_format": "g711_ulaw",
                "output_audio_format": "g711_ulaw",
            },
        }

        try:
            await self._send_event(config)
            self.logger.info(
                "context_injected_to_instructions",
                is_outbound=is_outbound,
            )
        except Exception as e:
            self.logger.exception("inject_context_error", error=str(e))

    async def cancel_response(self) -> None:
        """Cancel the current response generation (barge-in handling).

        This is called when the user starts speaking during AI response
        to immediately stop OpenAI's audio generation.
        """
        if not self.ws:
            return
        try:
            await self._send_event({"type": "response.cancel"})
            self.logger.info("response_cancelled_on_interruption")
        except Exception as e:
            self.logger.exception("cancel_response_error", error=str(e))

    async def _send_event(self, event: dict[str, Any]) -> None:
        """Send event to WebSocket.

        Args:
            event: Event dictionary to send
        """
        if not self.ws:
            raise RuntimeError("WebSocket not connected")

        event_type = event.get("type", "unknown")

        # Log important events with details
        if event_type == "session.update":
            session = event.get("session", {})
            self.logger.info(
                "sending_session_update",
                modalities=session.get("modalities"),
                voice=session.get("voice"),
                input_audio_format=session.get("input_audio_format"),
                output_audio_format=session.get("output_audio_format"),
                has_instructions=bool(session.get("instructions")),
                turn_detection=session.get("turn_detection"),
            )
        elif event_type == "response.create":
            response = event.get("response", {})
            # Mark request-send time so the receive loop can observe latency
            # when the matching response.created event arrives.
            self._pending_response_create_at = time.monotonic()
            self.logger.info(
                "sending_response_create",
                modalities=response.get("modalities"),
                has_instructions=bool(response.get("instructions")),
            )
        elif event_type == "conversation.item.create":
            item = event.get("item", {})
            content = item.get("content", [])
            self.logger.info(
                "sending_conversation_item_create",
                role=item.get("role"),
                item_type=item.get("type"),
                content_types=[c.get("type") for c in content],
            )
        else:
            self.logger.debug("sending_event", event_type=event_type)

        try:
            await self.ws.send(json.dumps(event))
        except Exception as e:
            self.logger.exception("send_event_error", error=str(e))
            raise
