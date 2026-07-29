"""Tests for voice prompt builder.

Tests prompt construction and enhancement for voice agents.
"""

from unittest.mock import MagicMock

import pytest

from app.services.ai.prompt_builder import VoicePromptBuilder


@pytest.fixture
def mock_agent() -> MagicMock:
    """Create a mock Agent model for testing."""
    agent = MagicMock()
    agent.name = "Test Agent"
    agent.system_prompt = "You are a helpful sales assistant."
    agent.enabled_tools = ["web_search", "x_search"]
    return agent


class TestVoicePromptBuilder:
    """Tests for VoicePromptBuilder class."""

    def test_init_with_agent(self, mock_agent: MagicMock) -> None:
        """Test initialization with an agent."""
        builder = VoicePromptBuilder(agent=mock_agent, timezone="America/New_York")
        assert builder.agent == mock_agent
        assert builder.timezone == "America/New_York"

    def test_init_without_agent(self) -> None:
        """Test initialization without an agent."""
        builder = VoicePromptBuilder()
        assert builder.agent is None
        assert builder.timezone == "America/New_York"

    def test_get_date_context(self) -> None:
        """Test date context generation."""
        builder = VoicePromptBuilder(timezone="America/New_York")
        context = builder.get_date_context()

        # Should contain current date info
        assert "CRITICAL DATE CONTEXT" in context
        assert "Today is" in context
        assert "current time" in context.lower()

    def test_get_identity_prefix_with_name(self, mock_agent: MagicMock) -> None:
        """Test identity prefix with agent name."""
        builder = VoicePromptBuilder(agent=mock_agent)
        prefix = builder.get_identity_prefix()

        assert "Test Agent" in prefix
        assert "CRITICAL IDENTITY INSTRUCTION" in prefix

    def test_get_identity_prefix_without_name(self) -> None:
        """Test identity prefix without agent name."""
        builder = VoicePromptBuilder()
        prefix = builder.get_identity_prefix()
        assert prefix == ""

    def test_get_realism_cues(self) -> None:
        """Test realism cues generation."""
        builder = VoicePromptBuilder()
        cues = builder.get_realism_cues()

        assert "[sigh]" in cues
        assert "[laugh]" in cues
        assert "[whisper]" in cues

    def test_get_search_guidance_with_tools(self, mock_agent: MagicMock) -> None:
        """Test search guidance when tools are enabled."""
        builder = VoicePromptBuilder(agent=mock_agent)
        guidance = builder.get_search_guidance()

        assert "web search" in guidance.lower()
        assert "x (twitter) search" in guidance.lower()

    def test_get_search_guidance_without_tools(self) -> None:
        """Test search guidance when no tools enabled."""
        builder = VoicePromptBuilder()
        guidance = builder.get_search_guidance()
        assert guidance == ""

    def test_get_telephony_guidance_inbound(self) -> None:
        """Test telephony guidance for inbound calls."""
        builder = VoicePromptBuilder()
        guidance = builder.get_telephony_guidance(is_outbound=False)

        assert "phone call" in guidance.lower()
        assert "greeting" in guidance.lower() or "caller" in guidance.lower()

    def test_get_telephony_guidance_outbound(self) -> None:
        """Test telephony guidance for outbound calls."""
        builder = VoicePromptBuilder()
        guidance = builder.get_telephony_guidance(is_outbound=True)

        assert "phone call" in guidance.lower()
        assert "YOU initiated" in guidance

    def test_get_booking_instructions(self) -> None:
        """Test booking instructions generation."""
        builder = VoicePromptBuilder(timezone="America/New_York")
        instructions = builder.get_booking_instructions()

        # Should contain date context
        assert "TODAY IS" in instructions
        assert "YYYY-MM-DD" in instructions

        # Should contain booking rules
        assert "check_availability" in instructions
        assert "book_appointment" in instructions
        assert "EMAIL" in instructions

    def test_build_context_section_empty(self) -> None:
        """Test context section with no contact/offer info."""
        builder = VoicePromptBuilder()
        context = builder.build_context_section()
        assert context == ""

    def test_build_context_section_with_contact(self) -> None:
        """Test context section with contact info."""
        builder = VoicePromptBuilder()
        contact_info = {"name": "John Doe", "company": "Acme Corp"}
        context = builder.build_context_section(contact_info=contact_info)

        assert "John Doe" in context
        assert "Acme Corp" in context

    def test_build_context_section_renders_returning_summary(self) -> None:
        """Returning-caller recap threaded through contact_info is rendered."""
        builder = VoicePromptBuilder()
        contact_info = {
            "name": "John Doe",
            "returning_summary": (
                "\n### Returning Caller (recall prior conversations)\n"
                "- Prior completed calls: 2\n  - (Jun 01) Asked about pricing."
            ),
        }
        context = builder.build_context_section(contact_info=contact_info)
        assert "Returning Caller" in context
        assert "Asked about pricing." in context

    def test_build_context_section_outbound(self) -> None:
        """Test context section for outbound calls."""
        builder = VoicePromptBuilder()
        contact_info = {"name": "Jane Smith"}
        context = builder.build_context_section(contact_info=contact_info, is_outbound=True)

        assert "OUTBOUND CALL" in context
        assert "Customer You Are Calling" in context

    def test_build_context_section_inbound(self) -> None:
        """Test context section for inbound calls."""
        builder = VoicePromptBuilder()
        contact_info = {"name": "Jane Smith"}
        context = builder.build_context_section(contact_info=contact_info, is_outbound=False)

        assert "INBOUND CALL" in context
        assert "Customer Information" in context

    def test_build_full_prompt_basic(self, mock_agent: MagicMock) -> None:
        """Test building a full prompt with agent."""
        builder = VoicePromptBuilder(agent=mock_agent)
        prompt = builder.build_full_prompt()

        # Should contain date context
        assert "CRITICAL DATE CONTEXT" in prompt

        # Should contain identity
        assert "Test Agent" in prompt

        # Should contain base prompt
        assert "helpful sales assistant" in prompt

    def test_build_full_prompt_with_options(self, mock_agent: MagicMock) -> None:
        """Test building prompt with various options."""
        builder = VoicePromptBuilder(agent=mock_agent)
        prompt = builder.build_full_prompt(
            include_realism=True,
            include_booking=True,
            is_outbound=True,
        )

        # Should include realism cues
        assert "[sigh]" in prompt or "[laugh]" in prompt

        # Should include booking instructions
        assert "check_availability" in prompt

        # Should include outbound telephony guidance
        assert "YOU initiated" in prompt

    def test_build_full_prompt_without_agent(self) -> None:
        """Test building prompt without agent."""
        builder = VoicePromptBuilder()
        prompt = builder.build_full_prompt()

        # Should use default prompt
        assert "helpful AI voice assistant" in prompt

    def test_get_outbound_opener_prompt(self, mock_agent: MagicMock) -> None:
        """Test outbound opener prompt generation."""
        builder = VoicePromptBuilder(agent=mock_agent)
        prompt = builder.get_outbound_opener_prompt()

        assert "pattern interrupt" in prompt.lower()
        assert "sales call" in prompt.lower()
        assert "hang up" in prompt.lower()

    def test_get_inbound_greeting_prompt_with_greeting(self) -> None:
        """Test inbound greeting prompt with specific greeting."""
        builder = VoicePromptBuilder()
        prompt = builder.get_inbound_greeting_prompt(greeting="Welcome to Acme Corp!")

        assert "Welcome to Acme Corp!" in prompt

    def test_get_inbound_greeting_prompt_default(self, mock_agent: MagicMock) -> None:
        """Test inbound greeting prompt with default."""
        builder = VoicePromptBuilder(agent=mock_agent)
        prompt = builder.get_inbound_greeting_prompt()

        assert "Test Agent" in prompt
        assert "Greet" in prompt
