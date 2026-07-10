"""Shared pytest fixtures.

Provides:
- Mock voice agent sessions, WebSocket connections, Cal.com / Telnyx services
- Model factory fixtures (``user_factory``, ``workspace_factory``, etc.)
  backed by factory_boy. See ``tests/factories.py`` and ``CONTRIBUTING.md``.
"""

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Keep test security/CORS/worker expectations deterministic even when a
# developer's local backend/.env flips deployment-mode flags.
os.environ.setdefault("SKIP_WEBHOOK_VERIFICATION", "false")
os.environ.setdefault("RUN_BACKGROUND_WORKERS", "true")

import pytest

from tests import factories


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock Agent model for testing.

    Returns:
        MagicMock configured as an Agent model
    """
    agent = MagicMock()
    agent.id = "test-agent-id"
    agent.name = "Test Agent"
    agent.system_prompt = "You are a helpful assistant."
    agent.voice_id = "alloy"
    agent.voice_provider = "openai"
    agent.initial_greeting = "Hello, how can I help you today?"
    agent.temperature = 0.7
    agent.turn_detection_mode = "server_vad"
    agent.turn_detection_threshold = 0.5
    agent.silence_duration_ms = 700
    agent.calcom_event_type_id = "test-event-type"
    agent.enabled_tools = ["web_search"]
    agent.tool_settings = {}
    return agent


@pytest.fixture
def mock_contact_info() -> dict[str, Any]:
    """Create mock contact information for testing.

    Returns:
        Dictionary with contact fields
    """
    return {
        "name": "John Doe",
        "phone": "+15551234567",
        "email": "john@example.com",
        "company": "Acme Corp",
        "status": "active",
    }


@pytest.fixture
def mock_offer_info() -> dict[str, Any]:
    """Create mock offer information for testing.

    Returns:
        Dictionary with offer fields
    """
    return {
        "name": "Premium Plan",
        "description": "Our best plan with unlimited features",
        "discount_type": "percentage",
        "discount_value": 20.0,
        "terms": "Valid for new customers only",
    }


@pytest.fixture
def mock_websocket() -> AsyncMock:
    """Create a mock WebSocket for testing.

    Returns:
        AsyncMock configured as a WebSocket
    """
    websocket = AsyncMock()
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    websocket.send_text = AsyncMock()
    websocket.send_json = AsyncMock()
    websocket.receive_text = AsyncMock()
    websocket.client = MagicMock()
    websocket.client.host = "127.0.0.1"
    websocket.client.port = 12345
    return websocket


@pytest.fixture
def mock_calcom_service() -> AsyncMock:
    """Create a mock Cal.com service for testing.

    Returns:
        AsyncMock configured as CalComService
    """
    service = AsyncMock()
    service.get_availability = AsyncMock(
        return_value=[
            {"time": "09:00", "date": "2024-01-15"},
            {"time": "10:00", "date": "2024-01-15"},
            {"time": "14:00", "date": "2024-01-15"},
        ]
    )
    service.create_booking = AsyncMock(
        return_value={
            "uid": "booking-uid-123",
            "id": "booking-id-456",
        }
    )
    service.close = AsyncMock()
    return service


@pytest.fixture
def mock_telnyx_service() -> AsyncMock:
    """Create a mock Telnyx voice service for testing.

    Returns:
        AsyncMock configured as TelnyxVoiceService
    """
    service = AsyncMock()
    service.send_dtmf = AsyncMock(return_value=True)
    service.close = AsyncMock()
    return service


class MockVoiceAgentSession:
    """Mock voice agent session for testing.

    Implements the VoiceAgentProtocol interface for testing
    without actual WebSocket connections.
    """

    def __init__(self) -> None:
        self._connected = False
        self._tool_callback: Any = None
        self._audio_queue: list[bytes] = []
        self._transcript_entries: list[dict[str, Any]] = []

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def configure_session(
        self,
        voice: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        turn_detection_mode: str | None = None,
        turn_detection_threshold: float | None = None,
        silence_duration_ms: int | None = None,
    ) -> None:
        pass

    async def send_audio_chunk(self, audio_data: bytes) -> None:
        pass

    async def receive_audio_stream(self) -> AsyncIterator[bytes]:
        for chunk in self._audio_queue:
            yield chunk

    async def trigger_initial_response(
        self,
        greeting: str | None = None,
        is_outbound: bool = False,
    ) -> None:
        pass

    async def inject_context(
        self,
        contact_info: dict[str, Any] | None = None,
        offer_info: dict[str, Any] | None = None,
        is_outbound: bool = False,
    ) -> None:
        pass

    async def cancel_response(self) -> None:
        pass

    def is_connected(self) -> bool:
        return self._connected

    def get_transcript_json(self) -> str | None:
        if not self._transcript_entries:
            return None
        import json

        return json.dumps(self._transcript_entries)

    def set_tool_callback(self, callback: Any) -> None:
        self._tool_callback = callback

    async def submit_tool_result(self, call_id: str, result: dict[str, Any]) -> None:
        pass

    def add_test_audio(self, audio: bytes) -> None:
        """Add audio to the mock queue for testing."""
        self._audio_queue.append(audio)

    def add_transcript_entry(self, role: str, text: str) -> None:
        """Add a transcript entry for testing."""
        self._transcript_entries.append({"role": role, "text": text})


@pytest.fixture
def mock_voice_session() -> MockVoiceAgentSession:
    """Create a mock voice agent session for testing.

    Returns:
        MockVoiceAgentSession instance
    """
    return MockVoiceAgentSession()


# ---------------------------------------------------------------------------
# Factory fixtures
# ---------------------------------------------------------------------------
#
# Each fixture yields the factory CLASS (not an instance) so tests can call
# ``user_factory.build(...)`` / ``user_factory.create(...)`` as needed.
#
# Sequence counters are reset between tests so test order doesn't influence
# generated emails/IDs. See ``tests/factories.py`` for the factory definitions
# and ``CONTRIBUTING.md`` for usage patterns.


@pytest.fixture(autouse=True)
def _reset_factory_sequences() -> Iterator[None]:
    """Reset every factory's Sequence counter before each test."""
    factories.reset_factory_sequences()
    yield


@pytest.fixture
def user_factory() -> type[factories.UserFactory]:
    return factories.UserFactory


@pytest.fixture
def workspace_factory() -> type[factories.WorkspaceFactory]:
    return factories.WorkspaceFactory


@pytest.fixture
def workspace_membership_factory() -> type[factories.WorkspaceMembershipFactory]:
    return factories.WorkspaceMembershipFactory


@pytest.fixture
def contact_factory() -> type[factories.ContactFactory]:
    return factories.ContactFactory


@pytest.fixture
def tag_factory() -> type[factories.TagFactory]:
    return factories.TagFactory


@pytest.fixture
def contact_tag_factory() -> type[factories.ContactTagFactory]:
    return factories.ContactTagFactory


@pytest.fixture
def agent_factory() -> type[factories.AgentFactory]:
    return factories.AgentFactory


@pytest.fixture
def phone_number_factory() -> type[factories.PhoneNumberFactory]:
    return factories.PhoneNumberFactory


@pytest.fixture
def conversation_factory() -> type[factories.ConversationFactory]:
    return factories.ConversationFactory


@pytest.fixture
def message_factory() -> type[factories.MessageFactory]:
    return factories.MessageFactory


@pytest.fixture
def campaign_factory() -> type[factories.CampaignFactory]:
    return factories.CampaignFactory


@pytest.fixture
def campaign_contact_factory() -> type[factories.CampaignContactFactory]:
    return factories.CampaignContactFactory


@pytest.fixture
def appointment_factory() -> type[factories.AppointmentFactory]:
    return factories.AppointmentFactory


@pytest.fixture
def pipeline_factory() -> type[factories.PipelineFactory]:
    return factories.PipelineFactory


@pytest.fixture
def pipeline_stage_factory() -> type[factories.PipelineStageFactory]:
    return factories.PipelineStageFactory


@pytest.fixture
def opportunity_factory() -> type[factories.OpportunityFactory]:
    return factories.OpportunityFactory
