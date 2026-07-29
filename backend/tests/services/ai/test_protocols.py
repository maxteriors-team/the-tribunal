"""Tests for voice agent protocol definitions.

Tests that the protocol interfaces are properly defined and that
implementations correctly satisfy them.
"""

from typing import Any

from app.services.ai.protocols import (
    InterruptibleProtocol,
    ToolCallableProtocol,
    VoiceAgentProtocol,
    supports_interruption,
    supports_tools,
)


class TestVoiceAgentProtocol:
    """Tests for VoiceAgentProtocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """Test that the protocol can be used with isinstance()."""

        # A simple class that implements all required methods
        class FakeAgent:
            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            async def configure_session(self, **kwargs: Any) -> None:
                pass

            async def send_audio_chunk(self, audio_data: bytes) -> None:
                pass

            def receive_audio_stream(self) -> Any:
                return iter([])

            async def trigger_initial_response(self, **kwargs: Any) -> None:
                pass

            async def inject_context(self, **kwargs: Any) -> None:
                pass

            async def cancel_response(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            def get_transcript_json(self) -> str | None:
                return None

        agent = FakeAgent()
        assert isinstance(agent, VoiceAgentProtocol)

    def test_non_compliant_class_fails(self) -> None:
        """Test that a class missing methods doesn't match the protocol."""

        class IncompleteAgent:
            async def connect(self) -> bool:
                return True

            # Missing other required methods

        agent = IncompleteAgent()
        assert not isinstance(agent, VoiceAgentProtocol)


class TestToolCallableProtocol:
    """Tests for ToolCallableProtocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """Test that the protocol can be used with isinstance()."""

        class FakeToolAgent:
            def set_tool_callback(self, callback: Any) -> None:
                pass

            async def submit_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
                pass

        agent = FakeToolAgent()
        assert isinstance(agent, ToolCallableProtocol)


class TestInterruptibleProtocol:
    """Tests for InterruptibleProtocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """Test that the protocol can be used with isinstance()."""
        import asyncio

        class FakeInterruptibleAgent:
            def set_interruption_event(self, event: asyncio.Event) -> None:
                pass

        agent = FakeInterruptibleAgent()
        assert isinstance(agent, InterruptibleProtocol)


class TestProtocolHelpers:
    """Tests for protocol helper functions."""

    def test_supports_tools_with_tool_agent(self) -> None:
        """Test supports_tools returns True for tool-supporting agents."""

        class ToolAgent:
            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            async def configure_session(self, **kwargs: Any) -> None:
                pass

            async def send_audio_chunk(self, audio_data: bytes) -> None:
                pass

            def receive_audio_stream(self) -> Any:
                return iter([])

            async def trigger_initial_response(self, **kwargs: Any) -> None:
                pass

            async def inject_context(self, **kwargs: Any) -> None:
                pass

            async def cancel_response(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            def get_transcript_json(self) -> str | None:
                return None

            def set_tool_callback(self, callback: Any) -> None:
                pass

            async def submit_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
                pass

        agent = ToolAgent()
        assert supports_tools(agent)

    def test_supports_tools_without_tool_support(self) -> None:
        """Test supports_tools returns False for basic agents."""

        class BasicAgent:
            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            async def configure_session(self, **kwargs: Any) -> None:
                pass

            async def send_audio_chunk(self, audio_data: bytes) -> None:
                pass

            def receive_audio_stream(self) -> Any:
                return iter([])

            async def trigger_initial_response(self, **kwargs: Any) -> None:
                pass

            async def inject_context(self, **kwargs: Any) -> None:
                pass

            async def cancel_response(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            def get_transcript_json(self) -> str | None:
                return None

        agent = BasicAgent()
        assert not supports_tools(agent)

    def test_supports_interruption(self) -> None:
        """Test supports_interruption helper function."""
        import asyncio

        class InterruptibleAgent:
            async def connect(self) -> bool:
                return True

            async def disconnect(self) -> None:
                pass

            async def configure_session(self, **kwargs: Any) -> None:
                pass

            async def send_audio_chunk(self, audio_data: bytes) -> None:
                pass

            def receive_audio_stream(self) -> Any:
                return iter([])

            async def trigger_initial_response(self, **kwargs: Any) -> None:
                pass

            async def inject_context(self, **kwargs: Any) -> None:
                pass

            async def cancel_response(self) -> None:
                pass

            def is_connected(self) -> bool:
                return True

            def get_transcript_json(self) -> str | None:
                return None

            def set_interruption_event(self, event: asyncio.Event) -> None:
                pass

        agent = InterruptibleAgent()
        assert supports_interruption(agent)
