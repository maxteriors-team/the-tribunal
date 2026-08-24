"""Provider-neutral text messaging interface and factory."""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation import Conversation, Message
from app.services.messaging.outbound_media import OutboundMedia
from app.services.telephony.mac_relay import (
    MacRelayMessageService,
    build_configured_mac_relay_service,
)
from app.services.telephony.telnyx import TelnyxSMSService


class TextMessageProvider(Protocol):
    """Common interface for outbound text message providers."""

    async def send_message(
        self,
        to_number: str,
        from_number: str,
        body: str,
        db: AsyncSession,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        campaign_id: uuid.UUID | None = None,
        phone_number_id: uuid.UUID | None = None,
        idempotency_key: uuid.UUID | None = None,
        media: tuple[OutboundMedia, ...] = (),
    ) -> Message:
        """Send and persist a text message."""
        ...

    async def close(self) -> None:
        """Release provider resources."""
        ...


def provider_for_conversation(conversation: Conversation) -> str | None:
    """Keep outbound replies on the same text transport as the inbound thread.

    Lives here rather than beside any one sender because several unrelated
    callers reply into an existing thread. Homing it in one of them makes the
    others import that sender just to route a message, which is how the AI text
    agent and the quote-acceptance handoff ended up in an import cycle.
    """
    if conversation.channel == "imessage":
        return "mac_relay"
    return None


def get_text_message_provider(
    preferred_provider: str | None = None,
    *,
    mac_relay_service: str | None = None,
) -> TextMessageProvider:
    """Return the configured text provider, defaulting safely to Telnyx."""
    provider = (preferred_provider or settings.text_message_provider).strip().lower()
    if provider in {"mac_relay", "mac-relay", "imessage"} and _mac_relay_configured():
        return build_configured_mac_relay_service(mac_relay_service)
    return TelnyxSMSService(settings.telnyx_api_key)


def _mac_relay_configured() -> bool:
    """Return True when the relay has enough config for outbound sends."""
    return bool(settings.mac_relay_base_url and settings.mac_relay_token)


__all__ = [
    "MacRelayMessageService",
    "TelnyxSMSService",
    "TextMessageProvider",
    "get_text_message_provider",
    "provider_for_conversation",
]
