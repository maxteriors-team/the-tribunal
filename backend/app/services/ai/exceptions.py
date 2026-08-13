"""Voice agent exception hierarchy.

This module defines custom exceptions for voice agent operations,
following the pattern established in google_calendar.py for consistent
error handling across the application.

Exception Hierarchy:
    VoiceAgentError (base)
    ├── VoiceAgentConnectionError - Connection failures
    └── VoiceAgentTimeoutError - Operation timeouts
"""


class VoiceAgentError(Exception):
    """Base exception for voice agent errors.

    All voice agent-related exceptions should inherit from this class
    to enable consistent error handling at the voice bridge level.
    """

    def __init__(self, message: str, provider: str | None = None) -> None:
        """Initialize voice agent error.

        Args:
            message: Human-readable error message
            provider: Voice provider name (openai, grok, elevenlabs)
        """
        self.message = message
        self.provider = provider
        super().__init__(message)

    def __str__(self) -> str:
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message


class VoiceAgentConnectionError(VoiceAgentError):
    """Error connecting to voice provider API.

    Raised when:
    - WebSocket connection fails
    - Network connectivity issues
    - Provider service is unavailable
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        status_code: int | None = None,
    ) -> None:
        """Initialize connection error.

        Args:
            message: Error message
            provider: Voice provider name
            status_code: HTTP/WebSocket status code if available
        """
        super().__init__(message, provider)
        self.status_code = status_code


class VoiceAgentTimeoutError(VoiceAgentError):
    """Timeout waiting for voice provider response.

    Raised when:
    - Connection attempt times out
    - Tool execution exceeds timeout
    - Response generation takes too long
    """

    def __init__(
        self,
        message: str,
        provider: str | None = None,
        timeout_seconds: float | None = None,
        operation: str | None = None,
    ) -> None:
        """Initialize timeout error.

        Args:
            message: Error message
            provider: Voice provider name
            timeout_seconds: The timeout value that was exceeded
            operation: The operation that timed out (e.g., "connect", "tool_call")
        """
        super().__init__(message, provider)
        self.timeout_seconds = timeout_seconds
        self.operation = operation


class AudioConversionError(Exception):
    """Error during audio format conversion.

    Raised when:
    - Invalid audio data received
    - Conversion between formats fails
    - Sample rate conversion fails
    """

    def __init__(
        self,
        message: str,
        source_format: str | None = None,
        target_format: str | None = None,
    ) -> None:
        """Initialize audio conversion error.

        Args:
            message: Error message
            source_format: Source audio format (e.g., "mulaw_8k", "pcm16_24k")
            target_format: Target audio format
        """
        self.message = message
        self.source_format = source_format
        self.target_format = target_format
        super().__init__(message)
