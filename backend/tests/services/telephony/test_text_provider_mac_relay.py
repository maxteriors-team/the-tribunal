"""Tests for the provider-neutral text sender and Mac relay provider."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.config import settings as app_settings
from app.models.conversation import MessageChannel, MessageStatus
from app.services.telephony.mac_relay import MacRelayMessageService
from app.services.telephony.telnyx import TelnyxSMSService
from app.services.telephony.text_provider import get_text_message_provider


class TestTextProviderFactory:
    def test_defaults_to_telnyx(self) -> None:
        with (
            patch.object(app_settings, "text_message_provider", "telnyx"),
            patch.object(app_settings, "telnyx_api_key", "telnyx-key"),
        ):
            provider = get_text_message_provider()

        assert isinstance(provider, TelnyxSMSService)
        assert not isinstance(provider, MacRelayMessageService)

    def test_selects_mac_relay_only_when_configured(self) -> None:
        with (
            patch.object(app_settings, "text_message_provider", "mac_relay"),
            patch.object(app_settings, "mac_relay_base_url", "http://relay.local:8765"),
            patch.object(app_settings, "mac_relay_token", "relay-token"),
            patch.object(app_settings, "mac_relay_default_service", "imessage"),
        ):
            provider = get_text_message_provider()

        assert isinstance(provider, MacRelayMessageService)
        assert provider.base_url == "http://relay.local:8765"
        assert provider.service == "imessage"

    def test_falls_back_to_telnyx_when_relay_config_missing(self) -> None:
        with (
            patch.object(app_settings, "text_message_provider", "mac_relay"),
            patch.object(app_settings, "mac_relay_base_url", ""),
            patch.object(app_settings, "mac_relay_token", ""),
            patch.object(app_settings, "telnyx_api_key", "telnyx-key"),
        ):
            provider = get_text_message_provider()

        assert isinstance(provider, TelnyxSMSService)
        assert not isinstance(provider, MacRelayMessageService)


class TestMacRelaySender:
    async def test_send_message_posts_relay_payload_and_stores_imessage_channel(self) -> None:
        service = MacRelayMessageService(
            base_url="http://relay.local:8765",
            token="relay-token",
            service="imessage",
        )
        key = uuid.uuid4()
        conversation_id = uuid.uuid4()
        workspace_id = uuid.uuid4()

        conversation = MagicMock(
            id=conversation_id,
            contact_id=None,
            last_message_preview=None,
            last_message_at=None,
            last_message_direction=None,
        )
        db = MagicMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        async def fake_post_message(
            payload: dict[str, str], idempotency_key: uuid.UUID | None
        ) -> dict[str, Any]:
            assert idempotency_key == key
            assert payload == {
                "to": "+12025551234",
                "from": "sender@example.com",
                "text": "hello",
                "service": "imessage",
                "client_message_id": str(key),
            }
            return {"data": {"id": "mac-relay:relay-guid-1"}}

        with (
            patch.object(
                service,
                "_get_or_create_conversation",
                AsyncMock(return_value=conversation),
            ),
            patch.object(service, "_post_message", AsyncMock(side_effect=fake_post_message)),
            patch(
                "app.services.telephony.telnyx.shorten_urls_in_text",
                AsyncMock(side_effect=lambda body, **_kwargs: body),
            ),
        ):
            message = await service.send_message(
                to_number="202-555-1234",
                from_number="Sender@Example.COM",
                body="hello",
                db=db,
                workspace_id=workspace_id,
                idempotency_key=key,
            )

        assert message.channel == MessageChannel.IMESSAGE
        assert message.provider_message_id == "mac-relay:relay-guid-1"
        assert message.status == MessageStatus.SENT
        assert conversation.last_message_direction == "outbound"
        db.commit.assert_awaited_once()
