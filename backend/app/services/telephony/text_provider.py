"""Provider-neutral text messaging interface and factory."""

import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.conversation import (
    MESSENGER_CHANNELS,
    Conversation,
    Message,
    MessageChannel,
)
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
        sender_user_id: int | None = None,
        sender_display_name: str | None = None,
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
    if conversation.channel in MESSENGER_CHANNELS:
        return conversation.channel
    return None


class UnreachableConversationError(ValueError):
    """A thread has no address to reply to on its own transport."""


def outbound_addresses(conversation: Conversation) -> tuple[str, str]:
    """Return the ``(recipient, sender)`` addresses for replying into a thread.

    Phone-keyed threads answer on their phone pair; Messenger and Instagram
    threads answer to a Page-Scoped ID and have no workspace phone at all, so
    the sender is resolved from the workspace's Meta integration at send time
    and is empty here.

    Raises :class:`UnreachableConversationError` instead of returning ``None``: every
    caller here is about to send, and a silent ``None`` would surface as a
    provider error long after the real cause.
    """
    if conversation.channel in MESSENGER_CHANNELS:
        if not conversation.messenger_psid:
            raise UnreachableConversationError("Messenger conversation has no recipient id")
        return conversation.messenger_psid, ""
    if not conversation.contact_phone or not conversation.workspace_phone:
        raise UnreachableConversationError("Conversation has no phone numbers to reply on")
    return conversation.contact_phone, conversation.workspace_phone


def get_text_message_provider(
    preferred_provider: str | None = None,
    *,
    mac_relay_service: str | None = None,
) -> TextMessageProvider:
    """Return the configured text provider, defaulting safely to Telnyx."""
    provider = (preferred_provider or settings.text_message_provider).strip().lower()
    if provider in MESSENGER_CHANNELS:
        from app.services.telephony.messenger import MessengerMessageService

        return MessengerMessageService(channel=MessageChannel(provider))
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
    "UnreachableConversationError",
    "get_text_message_provider",
    "outbound_addresses",
    "provider_for_conversation",
]
