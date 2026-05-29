"""Voice session factory for provider selection.

This module extracts voice session creation logic from voice_bridge.py
into a factory pattern that cleanly handles provider selection and
configuration.

Usage:
    factory = VoiceSessionFactory(settings)
    session, error = factory.create_session(
        provider="grok",
        agent=agent,
        timezone="America/New_York",
    )
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.agent import Agent
from app.services.ai.elevenlabs_voice_agent import ElevenLabsVoiceAgentSession
from app.services.ai.grok import GrokVoiceAgentSession
from app.services.ai.openai_credentials import (
    OpenAICredentialError,
    get_openai_bearer_token,
    is_openai_configured,
    resolve_openai_credentials,
)
from app.services.ai.protocols import VoiceAgentProtocol
from app.services.ai.voice_agent import VoiceAgentSession

logger = structlog.get_logger()

# Type alias for voice session union
VoiceSessionType = VoiceAgentSession | GrokVoiceAgentSession | ElevenLabsVoiceAgentSession


class VoiceSessionFactory:
    """Factory for creating voice agent sessions.

    Handles provider selection, API key validation, and session
    configuration based on agent settings.

    Attributes:
        settings: Application settings with API keys
        logger: Structured logger
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize voice session factory.

        Args:
            settings: Application settings with API keys
        """
        self.settings = settings
        self.logger = logger.bind(service="voice_session_factory")

    def create_session(
        self,
        provider: str,
        agent: Agent | None = None,
        timezone: str = "America/New_York",
    ) -> tuple[VoiceSessionType | None, str | None]:
        """Create appropriate voice session based on provider.

        Args:
            provider: Provider name (openai, grok, elevenlabs)
            agent: Agent model for configuration
            timezone: Timezone for date context

        Returns:
            Tuple of (voice_session, error_message)
            If successful, error_message is None
            If failed, voice_session is None
        """
        provider_lower = provider.lower()

        if provider_lower == "elevenlabs":
            return self._create_elevenlabs_session(agent, timezone)

        if provider_lower == "grok":
            return self._create_grok_session(agent, timezone)

        # Default to OpenAI
        return self._create_openai_session(agent)

    async def create_session_for_workspace(
        self,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        provider: str,
        agent: Agent | None = None,
        timezone: str = "America/New_York",
    ) -> tuple[VoiceSessionType | None, str | None]:
        """Create a voice session using workspace-aware credentials when possible."""
        provider_lower = provider.lower()
        if provider_lower != "openai":
            return self.create_session(provider, agent, timezone)

        try:
            credential_context = await resolve_openai_credentials(db, workspace_id)
        except OpenAICredentialError:
            return None, "OpenAI credential not configured"
        return VoiceAgentSession(
            credential_context.bearer_token,
            agent,
            additional_headers={
                key: value
                for key, value in credential_context.openai_headers().items()
                if key != "Authorization"
            },
            use_client_secret=credential_context.is_oauth,
            credential_source=credential_context.source,
        ), None

    def _create_openai_session(
        self,
        agent: Agent | None,
    ) -> tuple[VoiceSessionType | None, str | None]:
        """Create OpenAI Realtime API session.

        Args:
            agent: Agent model for configuration

        Returns:
            Tuple of (session, error)
        """
        if not is_openai_configured():
            return None, "OpenAI credential not configured"

        return VoiceAgentSession(
            get_openai_bearer_token(),
            agent,
            use_client_secret=bool(self.settings.openai_oauth_access_token),
            credential_source="env_oauth"
            if self.settings.openai_oauth_access_token
            else "env_api_key",
        ), None

    def _create_grok_session(
        self,
        agent: Agent | None,
        timezone: str,
    ) -> tuple[VoiceSessionType | None, str | None]:
        """Create Grok (xAI) Realtime API session.

        Args:
            agent: Agent model for configuration
            timezone: Timezone for date context

        Returns:
            Tuple of (session, error)
        """
        if not self.settings.xai_api_key:
            return None, "xAI API key not configured"

        # Determine if tools should be enabled
        enable_tools = self._should_enable_tools(agent)

        self.logger.info(
            "grok_voice_session_creating",
            agent_name=agent.name if agent else None,
            agent_id=str(agent.id) if agent else None,
            calcom_event_type_id=agent.calcom_event_type_id if agent else None,
            enable_tools=enable_tools,
            agent_enabled_tools=agent.enabled_tools if agent else None,
        )

        if not enable_tools:
            self.logger.warning(
                "grok_tools_disabled",
                reason="Missing requirements for tool enablement",
            )

        session = GrokVoiceAgentSession(
            self.settings.xai_api_key,
            agent,
            enable_tools=enable_tools,
            timezone=timezone,
        )

        # Enable IVR detection if configured on agent
        if agent and agent.enable_ivr_navigation:
            session.enable_ivr_detection(
                navigation_goal=agent.ivr_navigation_goal,
                loop_threshold=agent.ivr_loop_threshold,
            )
            self.logger.info(
                "grok_ivr_detection_enabled",
                agent_id=str(agent.id),
                navigation_goal=agent.ivr_navigation_goal,
                loop_threshold=agent.ivr_loop_threshold,
            )

        return session, None

    def _create_elevenlabs_session(
        self,
        agent: Agent | None,
        timezone: str,
    ) -> tuple[VoiceSessionType | None, str | None]:
        """Create ElevenLabs hybrid session (Grok STT+LLM + ElevenLabs TTS).

        Args:
            agent: Agent model for configuration
            timezone: Timezone for date context

        Returns:
            Tuple of (session, error)
        """
        if not self.settings.elevenlabs_api_key:
            return None, "ElevenLabs API key not configured"

        if not self.settings.xai_api_key:
            return None, "xAI API key required for ElevenLabs mode (used for STT+LLM)"

        # Enable tools if agent has Cal.com configured
        enable_tools = self._should_enable_tools(agent)

        return ElevenLabsVoiceAgentSession(
            xai_api_key=self.settings.xai_api_key,
            elevenlabs_api_key=self.settings.elevenlabs_api_key,
            agent=agent,
            enable_tools=enable_tools,
            timezone=timezone,
        ), None

    def _should_enable_tools(self, agent: Agent | None) -> bool:
        """Determine if tools should be enabled for an agent.

        Tools require:
        - Agent with calcom_event_type_id configured
        - Cal.com API key in settings

        Args:
            agent: Agent to check

        Returns:
            True if tools should be enabled
        """
        if not agent:
            return False

        if not agent.calcom_event_type_id:
            return False

        return bool(self.settings.calcom_api_key)

    def get_provider_for_agent(self, agent: Agent | None) -> str:
        """Get the voice provider for an agent.

        Args:
            agent: Agent to check

        Returns:
            Provider name (openai, grok, elevenlabs)
        """
        if agent and agent.voice_provider:
            return agent.voice_provider.lower()
        return "openai"

    def is_provider_available(self, provider: str) -> bool:
        """Check if a provider's API key is configured.

        Args:
            provider: Provider name to check

        Returns:
            True if provider is available
        """
        provider_lower = provider.lower()

        if provider_lower == "openai":
            return is_openai_configured()

        if provider_lower == "grok":
            return bool(self.settings.xai_api_key)

        if provider_lower == "elevenlabs":
            return bool(self.settings.elevenlabs_api_key) and bool(self.settings.xai_api_key)

        return False


def create_voice_session(
    voice_provider: str,
    agent: Any,
    timezone: str = "America/New_York",
) -> tuple[VoiceSessionType | None, str | None]:
    """Create appropriate voice session based on provider.

    Convenience function that uses global settings.
    For more control, use VoiceSessionFactory directly.

    Args:
        voice_provider: Provider name (openai, grok, elevenlabs)
        agent: Agent model for configuration
        timezone: Timezone for date context

    Returns:
        Tuple of (voice_session, error_message)
    """
    from app.core.config import settings

    factory = VoiceSessionFactory(settings)
    return factory.create_session(voice_provider, agent, timezone)


async def create_workspace_voice_session(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    voice_provider: str,
    agent: Any,
    timezone: str = "America/New_York",
) -> tuple[VoiceSessionType | None, str | None]:
    """Create a voice session with workspace-scoped OpenAI credentials."""
    from app.core.config import settings

    factory = VoiceSessionFactory(settings)
    return await factory.create_session_for_workspace(
        db,
        workspace_id,
        voice_provider,
        agent,
        timezone,
    )


async def setup_voice_session(
    voice_session: VoiceAgentProtocol,
    agent: Any,
    contact_info: dict[str, Any] | None,
    offer_info: dict[str, Any] | None,
    timezone: str,
    log: Any,
    call_control_id: str | None = None,
    is_outbound: bool = False,
) -> None:
    """Configure voice session with agent settings and context.

    Note: The greeting is NOT triggered here. It's triggered when the
    Telnyx stream starts to ensure audio is ready before AI speaks.

    Args:
        voice_session: Voice provider session
        agent: Agent model for configuration
        contact_info: Contact information dict
        offer_info: Offer information dict
        timezone: Timezone for bookings
        log: Logger instance
        call_control_id: Telnyx call control ID
        is_outbound: True if this is an outbound call
    """
    from app.services.ai.protocols import supports_tools
    from app.services.ai.tool_executor import create_tool_callback

    # Set up tool callback if session supports tools
    if supports_tools(voice_session):
        log.info(
            "setting_up_tool_callback",
            session_type=type(voice_session).__name__,
            agent_name=agent.name if agent else None,
            calcom_event_type_id=agent.calcom_event_type_id if agent else None,
        )

        callback = create_tool_callback(
            agent=agent,
            contact_info=contact_info,
            timezone=timezone,
            call_control_id=call_control_id,
            log=log,
        )

        voice_session.set_tool_callback(callback)  # type: ignore[attr-defined]
        log.info("tool_callback_configured", session_type=type(voice_session).__name__)
    else:
        log.info(
            "tool_callback_not_configured",
            session_type=type(voice_session).__name__,
            reason="Session type does not support tools",
        )

    if agent:
        await voice_session.configure_session(
            voice=agent.voice_id,
            system_prompt=agent.system_prompt,
            temperature=agent.temperature,
            turn_detection_mode=agent.turn_detection_mode,
            turn_detection_threshold=agent.turn_detection_threshold,
            silence_duration_ms=agent.silence_duration_ms,
        )
        log.info("session_configured_with_agent_settings", agent_name=agent.name)

    if contact_info or offer_info:
        await voice_session.inject_context(
            contact_info=contact_info,
            offer_info=offer_info,
            is_outbound=is_outbound,
        )
        log.info(
            "context_injected",
            has_contact=bool(contact_info),
            has_offer=bool(offer_info),
            is_outbound=is_outbound,
        )

    if agent and agent.initial_greeting:
        log.info("initial_greeting_prepared", greeting_length=len(agent.initial_greeting))
