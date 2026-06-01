"""Telnyx voice service for making and receiving calls."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone
from app.core.metrics import (
    latency_ms_timer,
    observe_voice_call_started,
    telnyx_api_latency_ms,
)
from app.models.conversation import Conversation, Message, MessageStatus
from app.services.idempotency import (
    encode_client_state,
    idempotency_headers,
    resolve_message_idempotency,
)

logger = structlog.get_logger()

# Cache for Call Control Application ID
_call_control_app_id_cache: str | None = None


@dataclass
class CallInfo:
    """Call information from Telnyx."""

    id: str
    call_control_id: str
    state: str  # initiated, ringing, answered, completed, failed
    from_number: str
    to_number: str
    duration: int | None = None
    recording_url: str | None = None


class TelnyxVoiceService:
    """Voice service for Telnyx Call Control API.

    Handles:
    - Initiating outbound calls
    - Answering/hanging up calls
    - Managing call control streams
    - Tracking call state and duration
    """

    BASE_URL = "https://api.telnyx.com/v2"

    def __init__(self, api_key: str) -> None:
        """Initialize voice service.

        Args:
            api_key: Telnyx API key
        """
        self.api_key = api_key
        self._client: httpx.AsyncClient | None = None
        self.logger = logger.bind(service="telnyx_voice")

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _normalize_e164(self, phone: str) -> str:
        """Normalize phone number to E.164 format (+1XXXXXXXXXX)."""
        # Remove any non-digit characters except leading +
        if phone.startswith("+"):
            return "+" + "".join(c for c in phone[1:] if c.isdigit())
        digits = "".join(c for c in phone if c.isdigit())
        # Add + prefix if missing (assume US/Canada if 10-11 digits)
        if len(digits) == 10:
            return f"+1{digits}"
        if len(digits) == 11 and digits.startswith("1"):
            return f"+{digits}"
        return f"+{digits}"

    async def _get_call_control_application_id(self, webhook_url: str) -> str:
        """Get or create a Telnyx Call Control Application for outbound calls.

        Call Control Applications are required for the Call Control API.
        They define how calls should be handled and where webhooks are sent.

        Args:
            webhook_url: Webhook URL for call events

        Returns:
            Call Control Application ID string

        Raises:
            ValueError: If no application ID is found or created
        """
        global _call_control_app_id_cache

        # Return cached ID if available
        if _call_control_app_id_cache:
            self.logger.debug("using_cached_app_id", app_id=_call_control_app_id_cache)
            return _call_control_app_id_cache

        try:
            self.logger.info("fetching_call_control_applications")
            # List existing Call Control Applications
            response = await self.client.get("/call_control_applications")
            try:
                data = response.json()
            except (ValueError, TypeError) as json_err:
                self.logger.error("invalid_json_response", error=str(json_err))
                msg = f"Telnyx API returned invalid JSON: {json_err}"
                raise ValueError(msg) from json_err

            applications = data.get("data", [])
            self.logger.debug("found_applications", count=len(applications))

            if applications:
                # Find the first application with a valid webhook_event_url
                for app in applications:
                    app_id = app.get("id")
                    app_webhook = app.get("webhook_event_url")

                    if app_id and app_webhook:
                        self.logger.info(
                            "using_existing_call_control_application",
                            app_id=app_id,
                            app_name=app.get("application_name", "unknown"),
                        )
                        _call_control_app_id_cache = str(app_id)
                        return _call_control_app_id_cache

            # Create a new Call Control Application if none exists
            self.logger.info("creating_new_call_control_application")
            base_webhook_url = webhook_url.split("?")[0] if "?" in webhook_url else webhook_url

            app_payload = {
                "application_name": "aicrm-voice-agent",
                "active": True,
                "webhook_event_url": base_webhook_url,
            }

            response = await self.client.post(
                "/call_control_applications",
                json=app_payload,
            )
            try:
                new_data = response.json()
            except (ValueError, TypeError) as json_err:
                self.logger.error("invalid_json_on_create", error=str(json_err))
                msg = f"Telnyx API returned invalid JSON on create: {json_err}"
                raise ValueError(msg) from json_err
            app_id = new_data.get("data", {}).get("id")

            if not app_id:
                msg = "Failed to create Call Control Application"
                raise ValueError(msg)

            self.logger.info("call_control_application_created", app_id=app_id)
            _call_control_app_id_cache = str(app_id)
            return _call_control_app_id_cache

        except Exception as e:
            self.logger.exception("get_call_control_app_failed", error=str(e))
            raise ValueError(f"Failed to get Call Control Application: {e}") from e

    async def initiate_call(  # noqa: PLR0915
        self,
        to_number: str,
        from_number: str,
        connection_id: str | None,
        webhook_url: str,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        contact_phone: str | None = None,
        agent_id: uuid.UUID | None = None,
        enable_machine_detection: bool = False,
        campaign_id: uuid.UUID | None = None,
        idempotency_key: uuid.UUID | None = None,
    ) -> Message:
        """Initiate outbound call via Telnyx Call Control API.

        Args:
            to_number: Recipient phone number (E.164)
            from_number: Caller ID phone number (E.164)
            connection_id: Telnyx connection ID (optional, auto-discovered if not provided)
            webhook_url: Webhook URL for call events
            db: Database session
            workspace_id: Workspace ID
            contact_phone: Contact's phone number for conversation linking
            agent_id: Optional agent ID if call is agent-assisted
            enable_machine_detection: If True, enables voicemail/machine detection
            campaign_id: Optional campaign ID for tracking
            idempotency_key: Optional stable UUID for crash-safe retries.
                Workers compute this from a domain entity (e.g. campaign
                contact id + call attempt) so a crash between the Message
                row insert and the Telnyx /calls request is recoverable on
                retry without double-dialling. If a Message already exists
                for this key it is returned unchanged. The key is also
                forwarded to Telnyx as both ``client_state`` (base64) and
                the ``X-Idempotency-Key`` header.

        Returns:
            Created (or pre-existing) Message record with channel="voice".
        """
        # Normalize phone numbers to E.164 format
        to_number = self._normalize_e164(to_number)
        from_number = self._normalize_e164(from_number)

        log = self.logger.bind(to=to_number, from_=from_number)

        # Idempotency: if a Message row already exists for this key, the
        # call was already initiated on a prior attempt that survived its
        # DB commit. Return it unchanged unless the prior attempt rolled
        # back to QUEUED (DB row written but Telnyx call never made), in
        # which case we resume the dial with the same id + client_state.
        idempotency_state = await resolve_message_idempotency(db, idempotency_key)
        if idempotency_state.should_skip and idempotency_state.existing_message is not None:
            existing = idempotency_state.existing_message
            log.info(
                "call_initiate_idempotent_skip",
                idempotency_key=str(idempotency_key),
                message_id=str(existing.id),
                status=existing.status,
            )
            return existing

        log.info(
            "initiating_call",
            idempotency_key=str(idempotency_key) if idempotency_key else None,
        )

        # Auto-discover connection ID if not provided
        if not connection_id:
            connection_id = await self._get_call_control_application_id(webhook_url)
            log.info("auto_discovered_connection_id", connection_id=connection_id)

        # Get or create conversation
        conversation = await self._get_or_create_conversation(
            db=db,
            workspace_phone=from_number,
            contact_phone=contact_phone or to_number,
            workspace_id=workspace_id,
        )

        # Resume or create the Message row. ``effective_key`` is what we
        # send to Telnyx so the provider also rejects duplicates if the
        # local row was rolled back after the API call.
        effective_key = idempotency_state.effective_key

        message = idempotency_state.existing_message

        if message is None:
            message = Message(
                conversation_id=conversation.id,
                direction="outbound",
                channel="voice",
                body="",  # Voice calls don't have body text
                status="queued",
                agent_id=agent_id,
                is_ai=agent_id is not None,
                campaign_id=campaign_id,
                idempotency_key=effective_key,
            )
            db.add(message)
            await db.flush()

        # Initiate call via Telnyx
        try:
            # ``client_state`` round-trips through every Telnyx webhook for
            # this call, so the receiver side can also key on the same UUID
            # if it needs to dedupe inbound events. Telnyx requires it as a
            # base64 string.
            client_state_b64 = encode_client_state(effective_key)
            payload: dict[str, Any] = {
                "to": to_number,
                "from": from_number,
                "connection_id": connection_id,
                "webhook_url": webhook_url,
                "webhook_url_method": "POST",
                "audio_codec": "ulaw",  # μ-law for PSTN compatibility
                "client_state": client_state_b64,
            }

            # Enable machine detection for voicemail/answering machine
            if enable_machine_detection:
                payload["answering_machine_detection"] = "detect"
                payload["answering_machine_detection_config"] = {
                    "wait_for_beep_timeout_millis": 3000,  # ms to wait for beep
                    "total_analysis_time_millis": 5000,  # Total analysis time
                }
                log.info("machine_detection_enabled")

            with latency_ms_timer(telnyx_api_latency_ms):
                response = await self.client.post(
                    "/calls",
                    json=payload,
                    headers=idempotency_headers(effective_key),
                )
            response_data = response.json()

            log.info(
                "telnyx_response",
                status_code=response.status_code,
            )

            if response.status_code in (200, 201):
                data = response_data.get("data", {})
                call_id = data.get("id")
                call_control_id = data.get("call_control_id")

                message.provider_message_id = call_control_id  # Store call_control_id
                message.status = MessageStatus.RINGING
                observe_voice_call_started(workspace_id)
                log.info(
                    "call_initiated",
                    call_id=call_id,
                    call_control_id=call_control_id,
                )
            else:
                errors = response_data.get("errors", [])
                first_error = errors[0] if errors else {}
                error_code = str(first_error.get("code", "API_ERROR") or "API_ERROR")
                error_msg = first_error.get("detail") or response.text
                message.status, message.error_code = MessageStatus.FAILED, error_code
                message.error_message = error_msg[:500] if error_msg else None
                log.error("call_initiation_failed", error=error_msg, error_code=error_code)

        except Exception as e:
            message.status = MessageStatus.FAILED
            message.error_code = "EXCEPTION"
            message.error_message = str(e)[:500]
            log.exception("call_initiation_exception", error=str(e))

        # Update conversation
        conversation.channel = "voice"
        conversation.last_message_preview = "Voice call"
        conversation.last_message_at = datetime.now(UTC)

        # Assign agent to conversation when initiating call with specific agent
        # This ensures the selected agent overrides any existing phone number assignment
        if agent_id:
            conversation.assigned_agent_id = agent_id
            conversation.ai_enabled = True

        await db.commit()
        await db.refresh(message)

        return message

    async def answer_call(
        self,
        call_control_id: str,
    ) -> bool:
        """Answer incoming call.

        Args:
            call_control_id: Telnyx call control ID

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(
            "========== ANSWERING CALL ==========",
            call_control_id=call_control_id,
        )

        try:
            response = await self.client.post(
                f"/calls/{call_control_id}/actions/answer",
            )

            self.logger.info(
                "answer_call_response",
                call_control_id=call_control_id,
                status_code=response.status_code,
                response_text=response.text[:500] if response.text else "empty",
            )

            response.raise_for_status()
            self.logger.info(
                "call_answered_successfully",
                call_control_id=call_control_id,
            )
            return True
        except httpx.HTTPStatusError as e:
            self.logger.error(
                "answer_call_http_error",
                call_control_id=call_control_id,
                status_code=e.response.status_code,
                response_text=e.response.text[:500] if e.response.text else "empty",
                error=str(e),
            )
            return False
        except Exception as e:
            self.logger.exception(
                "answer_call_failed",
                call_control_id=call_control_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def hangup_call(
        self,
        call_control_id: str,
    ) -> bool:
        """Hang up call.

        Args:
            call_control_id: Telnyx call control ID

        Returns:
            True if successful, False otherwise
        """
        self.logger.info("hanging_up_call", call_control_id=call_control_id)

        try:
            response = await self.client.post(
                f"/calls/{call_control_id}/actions/hangup",
            )
            response.raise_for_status()
            self.logger.info("call_hung_up", call_control_id=call_control_id)
            return True
        except Exception as e:
            self.logger.exception(
                "hangup_call_failed",
                call_control_id=call_control_id,
                error=str(e),
            )
            return False

    async def start_streaming(
        self,
        call_control_id: str,
        stream_url: str,
        stream_track: str = "inbound_track",
    ) -> bool:
        """Start bidirectional audio streaming for AI integration.

        Enables real-time audio streaming between Telnyx and a WebSocket endpoint.
        Uses bidirectional RTP mode to allow the AI to speak back to the caller.

        Args:
            call_control_id: Telnyx call control ID
            stream_url: WebSocket URL for audio stream (wss://...)
            stream_track: Which audio track to stream (inbound_track recommended
                         to avoid AI hearing itself)

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(
            "========== STARTING AUDIO STREAM ==========",
            call_control_id=call_control_id,
            stream_url=stream_url,
            stream_track=stream_track,
        )

        try:
            payload: dict[str, Any] = {
                "stream_url": stream_url,
                "stream_track": stream_track,
                # Enable bidirectional streaming to send audio back to caller
                "stream_bidirectional_mode": "rtp",
                # Use PCMU codec (μ-law) at 8kHz for PSTN compatibility
                "stream_bidirectional_codec": "PCMU",
            }

            self.logger.info(
                "sending_streaming_start_request",
                call_control_id=call_control_id,
                payload=payload,
                endpoint=f"/calls/{call_control_id}/actions/streaming_start",
            )

            response = await self.client.post(
                f"/calls/{call_control_id}/actions/streaming_start",
                json=payload,
            )

            self.logger.info(
                "streaming_start_response",
                call_control_id=call_control_id,
                status_code=response.status_code,
                response_text=response.text[:500] if response.text else "empty",
            )

            response.raise_for_status()
            self.logger.info(
                "streaming_started_successfully",
                call_control_id=call_control_id,
                stream_url=stream_url,
                bidirectional=True,
            )
            return True
        except httpx.HTTPStatusError as e:
            self.logger.error(
                "start_streaming_http_error",
                call_control_id=call_control_id,
                status_code=e.response.status_code,
                response_text=e.response.text[:500] if e.response.text else "empty",
                error=str(e),
            )
            return False
        except Exception as e:
            self.logger.exception(
                "start_streaming_failed",
                call_control_id=call_control_id,
                error=str(e),
                error_type=type(e).__name__,
            )
            return False

    async def stop_streaming(
        self,
        call_control_id: str,
    ) -> bool:
        """Stop audio streaming.

        Args:
            call_control_id: Telnyx call control ID

        Returns:
            True if successful, False otherwise
        """
        self.logger.info("stopping_stream", call_control_id=call_control_id)

        try:
            response = await self.client.post(
                f"/calls/{call_control_id}/actions/streaming_stop",
            )
            response.raise_for_status()
            self.logger.info(
                "streaming_stopped",
                call_control_id=call_control_id,
            )
            return True
        except Exception as e:
            self.logger.exception(
                "stop_streaming_failed",
                call_control_id=call_control_id,
                error=str(e),
            )
            return False

    async def start_recording(
        self,
        call_control_id: str,
        channels: str = "dual",
        format: str = "mp3",
    ) -> bool:
        """Start recording an active call.

        Args:
            call_control_id: Telnyx call control ID
            channels: Recording channels - "single" or "dual" (separate tracks)
            format: Recording format - "mp3" or "wav"

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(
            "starting_call_recording",
            call_control_id=call_control_id,
            channels=channels,
            format=format,
        )

        try:
            payload: dict[str, Any] = {
                "format": format,
                "channels": channels,
            }

            response = await self.client.post(
                f"/calls/{call_control_id}/actions/record_start",
                json=payload,
            )
            response.raise_for_status()

            self.logger.info(
                "call_recording_started",
                call_control_id=call_control_id,
            )
            return True

        except httpx.HTTPStatusError as e:
            self.logger.error(
                "start_recording_http_error",
                call_control_id=call_control_id,
                status_code=e.response.status_code,
                response_text=e.response.text[:500] if e.response.text else "empty",
                error=str(e),
            )
            return False
        except Exception as e:
            self.logger.exception(
                "start_recording_failed",
                call_control_id=call_control_id,
                error=str(e),
            )
            return False

    async def send_dtmf(
        self,
        call_control_id: str,
        digits: str,
        duration_millis: int = 250,
    ) -> bool:
        """Send DTMF tones during an active call.

        Used for IVR menu navigation. Valid digits: 0-9, A-D, *, #
        Pauses: 'w' (0.5s), 'W' (1s)

        Args:
            call_control_id: Telnyx call control ID
            digits: DTMF digits to send (e.g., "1", "0w0", "123#")
            duration_millis: Duration per digit in ms (100-500, default 250)

        Returns:
            True if successful, False otherwise
        """
        self.logger.info(
            "sending_dtmf",
            call_control_id=call_control_id,
            digits=digits,
            duration_millis=duration_millis,
        )

        try:
            payload: dict[str, Any] = {
                "digits": digits,
                "duration_millis": max(100, min(500, duration_millis)),
            }

            response = await self.client.post(
                f"/calls/{call_control_id}/actions/send_dtmf",
                json=payload,
            )
            response.raise_for_status()

            self.logger.info(
                "dtmf_sent_successfully",
                call_control_id=call_control_id,
                digits=digits,
            )
            return True

        except httpx.HTTPStatusError as e:
            self.logger.error(
                "send_dtmf_http_error",
                call_control_id=call_control_id,
                digits=digits,
                status_code=e.response.status_code,
                response_text=e.response.text[:500] if e.response.text else "empty",
                error=str(e),
            )
            return False
        except Exception as e:
            self.logger.exception(
                "send_dtmf_failed",
                call_control_id=call_control_id,
                digits=digits,
                error=str(e),
            )
            return False

    async def update_message_call_status(
        self,
        db: AsyncSession,
        provider_message_id: str,
        status: str,
        duration_seconds: int | None = None,
        recording_url: str | None = None,
    ) -> Message | None:
        """Update call message status and recording info.

        Args:
            db: Database session
            provider_message_id: Telnyx call_control_id
            status: Call status (initiated, ringing, answered, completed, failed)
            duration_seconds: Call duration if completed
            recording_url: URL to call recording if available

        Returns:
            Updated message or None if not found
        """
        result = await db.execute(
            select(Message).where(Message.provider_message_id == provider_message_id)
        )
        message = result.scalar_one_or_none()

        if not message:
            self.logger.warning(
                "message_not_found",
                provider_message_id=provider_message_id,
            )
            return None

        # Map Telnyx status to our status
        status_map: dict[str, MessageStatus] = {
            "initiated": MessageStatus.INITIATED,
            "ringing": MessageStatus.RINGING,
            "answered": MessageStatus.ANSWERED,
            "completed": MessageStatus.COMPLETED,
            "failed": MessageStatus.FAILED,
            "busy": MessageStatus.FAILED,
            "no_answer": MessageStatus.FAILED,
        }

        message.status = status_map.get(status, MessageStatus(status))
        if duration_seconds is not None:
            message.duration_seconds = duration_seconds
        if recording_url:
            message.recording_url = recording_url

        await db.commit()
        await db.refresh(message)

        self.logger.info(
            "call_message_updated",
            message_id=str(message.id),
            status=message.status,
            duration=duration_seconds,
        )

        return message

    async def _get_or_create_conversation(
        self,
        db: AsyncSession,
        workspace_phone: str,
        contact_phone: str,
        workspace_id: uuid.UUID,
    ) -> Conversation:
        """Get or create conversation for voice call.

        Args:
            db: Database session
            workspace_phone: Our phone number
            contact_phone: Contact's phone number
            workspace_id: Workspace ID

        Returns:
            Existing or new conversation
        """
        from app.models.contact import Contact

        # Look for existing conversation
        result = await db.execute(
            select(Conversation).where(
                Conversation.workspace_id == workspace_id,
                Conversation.workspace_phone == workspace_phone,
                Conversation.contact_phone == contact_phone,
            )
        )
        conversation = result.scalar_one_or_none()

        if conversation:
            return conversation

        # Try to find contact by phone number
        contact_result = await db.execute(
            select(Contact).where(
                Contact.workspace_id == workspace_id,
                Contact.phone_hash == hash_phone(contact_phone),
            )
        )
        contact = contact_result.scalar_one_or_none()

        # Create new conversation
        conversation = Conversation(
            workspace_id=workspace_id,
            contact_id=contact.id if contact else None,
            workspace_phone=workspace_phone,
            contact_phone=contact_phone,
            channel="voice",
            ai_enabled=True,  # Enable AI for voice calls by default
        )
        db.add(conversation)
        await db.flush()

        self.logger.info(
            "conversation_created",
            conversation_id=str(conversation.id),
            contact_id=contact.id if contact else None,
            channel="voice",
        )

        return conversation

    @staticmethod
    def build_stream_url(
        call_control_id: str,
        api_base_url: str,
        is_outbound: bool = False,
    ) -> str:
        """Build WebSocket URL for audio streaming.

        Args:
            call_control_id: Telnyx call control ID
            api_base_url: Base API URL (e.g., https://example.com)
            is_outbound: If True, adds is_outbound=true query param

        Returns:
            WebSocket URL for audio streaming
        """
        # Convert https to wss for WebSocket
        ws_base = api_base_url.replace("https://", "wss://").replace("http://", "ws://")
        # Path is /voice/stream/ (not /ws/voice/stream/)
        stream_url = f"{ws_base}/voice/stream/{call_control_id}"
        if is_outbound:
            stream_url += "?is_outbound=true"
        return stream_url

    async def start_audio_streaming(
        self,
        call_control_id: str,
        api_base_url: str,
        is_outbound: bool = False,
    ) -> bool:
        """Start audio streaming with automatic URL building.

        Convenience method that builds the stream URL and starts streaming.

        Args:
            call_control_id: Telnyx call control ID
            api_base_url: Base API URL (e.g., https://example.com)
            is_outbound: If True, adds is_outbound=true to URL

        Returns:
            True if streaming started successfully, False otherwise
        """
        stream_url = self.build_stream_url(call_control_id, api_base_url, is_outbound)

        self.logger.info(
            "starting_audio_streaming",
            call_control_id=call_control_id,
            stream_url=stream_url,
            is_outbound=is_outbound,
        )

        # Only stream caller's audio to avoid AI hearing itself
        return await self.start_streaming(
            call_control_id=call_control_id,
            stream_url=stream_url,
            stream_track="inbound_track",
        )
