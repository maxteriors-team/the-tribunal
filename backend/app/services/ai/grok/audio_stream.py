"""Audio stream management for Grok voice agent.

This module provides audio streaming infrastructure for the Grok Realtime API,
including statistics tracking, WebSocket message parsing, and stream management.
"""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import structlog
import websockets
from websockets.asyncio.client import ClientConnection

logger = structlog.get_logger()


@dataclass
class AudioStreamStats:
    """Statistics for audio streaming.

    Tracks metrics about audio chunks, responses, and errors during a session.

    Attributes:
        chunks_received: Total audio chunks received
        bytes_received: Total audio bytes received
        responses_completed: Number of response.done events
        errors_encountered: Number of error events
        events_processed: Total events processed
    """

    chunks_received: int = 0
    bytes_received: int = 0
    responses_completed: int = 0
    errors_encountered: int = 0
    events_processed: int = 0

    def record_audio_chunk(self, size: int) -> None:
        """Record an audio chunk received.

        Args:
            size: Size of the audio chunk in bytes
        """
        self.chunks_received += 1
        self.bytes_received += size

    def record_response_done(self) -> None:
        """Record a response completion."""
        self.responses_completed += 1

    def record_error(self) -> None:
        """Record an error event."""
        self.errors_encountered += 1

    def record_event(self) -> None:
        """Record any event processed."""
        self.events_processed += 1


@dataclass
class AudioStreamConfig:
    """Configuration for audio streaming.

    Attributes:
        log_interval: Log progress every N chunks
        log_all_events: Whether to log all non-audio events at INFO level
    """

    log_interval: int = 100
    log_all_events: bool = False


class AudioStreamManager:
    """Manages audio streaming from Grok Realtime API.

    Provides:
    - WebSocket message parsing with error handling
    - Statistics tracking
    - Configurable logging verbosity
    - Stream iteration utilities

    Usage:
        manager = AudioStreamManager(ws, config)

        async for event in manager.iter_events():
            # Process event
            pass

        stats = manager.stats
    """

    def __init__(
        self,
        ws: ClientConnection,
        config: AudioStreamConfig | None = None,
    ) -> None:
        """Initialize the audio stream manager.

        Args:
            ws: WebSocket connection to Grok API
            config: Streaming configuration
        """
        self._ws = ws
        self._config = config or AudioStreamConfig()
        self._stats = AudioStreamStats()
        self._logger = logger.bind(service="audio_stream_manager")

    @property
    def stats(self) -> AudioStreamStats:
        """Get current streaming statistics.

        Returns:
            AudioStreamStats with current metrics
        """
        return self._stats

    async def iter_events(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate over parsed events from the WebSocket.

        Handles JSON parsing errors gracefully and continues streaming.

        Yields:
            Parsed event dictionaries
        """
        try:
            async for message in self._ws:
                event = self._parse_message(message)
                if event:
                    self._stats.record_event()
                    self._maybe_log_event(event)
                    yield event

        except websockets.exceptions.ConnectionClosed as e:
            self._logger.warning(
                "websocket_closed",
                code=e.code,
                reason=e.reason,
                stats=self._stats_summary(),
            )
        except Exception as e:
            self._logger.exception(
                "stream_error",
                error=str(e),
                stats=self._stats_summary(),
            )

    def _parse_message(self, message: str | bytes) -> dict[str, Any] | None:
        """Parse a WebSocket message as JSON.

        Args:
            message: Raw message from WebSocket

        Returns:
            Parsed event dictionary, or None if parsing failed
        """
        try:
            return cast(dict[str, Any], json.loads(message))
        except json.JSONDecodeError as e:
            self._logger.warning(
                "invalid_json",
                error_type=type(e).__name__,
                message_size=len(message),
            )
            return None

    def _maybe_log_event(self, event: dict[str, Any]) -> None:
        """Log event based on configuration and type.

        High-frequency audio delta events are not logged by default.
        Other events are logged at DEBUG level unless log_all_events is True.

        Args:
            event: The event to potentially log
        """
        event_type = event.get("type", "")

        # Never log high-frequency audio deltas
        if event_type in ("response.audio.delta", "response.output_audio.delta"):
            # Just check if we should log progress
            if (
                self._stats.chunks_received > 0
                and self._stats.chunks_received % self._config.log_interval == 0
            ):
                self._logger.debug(
                    "audio_stream_progress",
                    chunks=self._stats.chunks_received,
                    bytes=self._stats.bytes_received,
                    responses=self._stats.responses_completed,
                )
            return

        # Log other events
        level = "info" if self._config.log_all_events else "debug"

        if event_type == "session.created":
            # Session created is always INFO level (important)
            self._logger.info(
                "event_received",
                event_type=event_type,
            )
        elif event_type == "error":
            # Errors are always logged at WARNING+
            self._stats.record_error()
            # Already handled by ErrorHandler
        elif event_type == "response.done":
            self._stats.record_response_done()
            self._logger.debug(
                "event_received",
                event_type=event_type,
                response_count=self._stats.responses_completed,
            )
        else:
            getattr(self._logger, level)(
                "event_received",
                event_type=event_type,
                event_keys=list(event.keys()),
            )

    def _stats_summary(self) -> dict[str, int]:
        """Get a summary of current stats.

        Returns:
            Dictionary with key stats
        """
        return {
            "chunks": self._stats.chunks_received,
            "bytes": self._stats.bytes_received,
            "responses": self._stats.responses_completed,
            "errors": self._stats.errors_encountered,
            "events": self._stats.events_processed,
        }

    def log_stream_end(self, transcript_count: int = 0) -> None:
        """Log final statistics when stream ends.

        Args:
            transcript_count: Number of transcript entries
        """
        self._logger.info(
            "audio_stream_ended",
            total_chunks=self._stats.chunks_received,
            total_bytes=self._stats.bytes_received,
            total_responses=self._stats.responses_completed,
            total_errors=self._stats.errors_encountered,
            transcript_count=transcript_count,
        )


class EventParser:
    """Utility for parsing and extracting data from Grok events.

    Provides type-safe extraction methods for common event fields.
    """

    @staticmethod
    def get_audio_delta(event: dict[str, Any]) -> str | None:
        """Extract audio delta from an event.

        Args:
            event: Audio delta event

        Returns:
            Base64 encoded audio string, or None
        """
        return event.get("delta")

    @staticmethod
    def get_transcript_delta(event: dict[str, Any]) -> str | None:
        """Extract transcript delta from an event.

        Args:
            event: Transcript delta event

        Returns:
            Transcript text, or None
        """
        return event.get("delta")

    @staticmethod
    def get_response_data(event: dict[str, Any]) -> dict[str, Any]:
        """Extract response data from a response event.

        Args:
            event: Response event (created, done)

        Returns:
            Response data dictionary
        """
        result: dict[str, Any] = event.get("response", {})
        return result

    @staticmethod
    def get_session_data(event: dict[str, Any]) -> dict[str, Any]:
        """Extract session data from a session event.

        Args:
            event: Session event (created, updated)

        Returns:
            Session data dictionary
        """
        result: dict[str, Any] = event.get("session", {})
        return result

    @staticmethod
    def get_error_data(event: dict[str, Any]) -> dict[str, Any]:
        """Extract error data from an error event.

        Args:
            event: Error event

        Returns:
            Error data dictionary
        """
        result: dict[str, Any] = event.get("error", {})
        return result

    @staticmethod
    def get_item_data(event: dict[str, Any]) -> dict[str, Any]:
        """Extract item data from an item event.

        Args:
            event: Item event (output_item.done)

        Returns:
            Item data dictionary
        """
        result: dict[str, Any] = event.get("item", {})
        return result
