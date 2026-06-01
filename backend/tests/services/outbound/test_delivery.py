"""Tests for the unified outbound delivery service."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import ANY, AsyncMock

import pytest

from app.models.conversation import MessageStatus
from app.services.outbound.delivery import (
    OutboundDeliveryChannel,
    OutboundDeliveryRequest,
    OutboundDeliveryService,
    OutboundDeliveryStatus,
)


class _FakeOptOutManager:
    def __init__(self, *, opted_out: bool = False) -> None:
        self.opted_out = opted_out
        self.calls: list[tuple[uuid.UUID, str]] = []

    async def check_opt_out(self, workspace_id: uuid.UUID, phone_number: str, db: Any) -> bool:
        self.calls.append((workspace_id, phone_number))
        return self.opted_out


class _FakeTextProvider:
    def __init__(self, message: Any) -> None:
        self.message = message
        self.send_message = AsyncMock(return_value=message)
        self.close = AsyncMock()


class _FakeEmailProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], uuid.UUID | None]] = []

    async def send_email(
        self,
        params: dict[str, Any],
        *,
        idempotency_key: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        self.calls.append((params, idempotency_key))
        return {"id": "email_123"}


def _unused_text_provider_factory(
    preferred_provider: str | None = None,
    *,
    mac_relay_service: str | None = None,
) -> _FakeTextProvider:
    return _FakeTextProvider(None)


class _FakePushProvider:
    def __init__(self, *, sent: bool = True) -> None:
        self.sent = sent
        self.user_calls: list[dict[str, Any]] = []
        self.workspace_calls: list[dict[str, Any]] = []

    async def send_to_user(
        self,
        db: Any,
        user_id: int,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> bool:
        self.user_calls.append(
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "data": data,
                "notification_type": notification_type,
                "channel_id": channel_id,
            }
        )
        return self.sent

    async def send_to_workspace_members(
        self,
        db: Any,
        workspace_id: str,
        title: str,
        body: str,
        data: dict[str, Any] | None = None,
        notification_type: str | None = None,
        channel_id: str | None = None,
    ) -> bool:
        self.workspace_calls.append(
            {
                "workspace_id": workspace_id,
                "title": title,
                "body": body,
                "data": data,
                "notification_type": notification_type,
                "channel_id": channel_id,
            }
        )
        return self.sent


@pytest.mark.asyncio
async def test_imessage_delivery_uses_mac_relay_preference_and_idempotency_key() -> None:
    workspace_id = uuid.uuid4()
    key = uuid.uuid4()
    message = SimpleNamespace(
        id=uuid.uuid4(),
        status=MessageStatus.SENT,
        provider_message_id="mac-relay:abc",
        error_message=None,
    )
    provider = _FakeTextProvider(message)
    provider_calls: list[tuple[str | None, str | None]] = []

    def provider_factory(
        preferred_provider: str | None = None,
        *,
        mac_relay_service: str | None = None,
    ) -> _FakeTextProvider:
        provider_calls.append((preferred_provider, mac_relay_service))
        return provider

    service = OutboundDeliveryService(
        text_provider_factory=provider_factory,
        email_provider=_FakeEmailProvider(),
        push_provider=_FakePushProvider(),
        opt_out_manager=_FakeOptOutManager(),
    )

    result = await service.deliver(
        AsyncMock(),
        OutboundDeliveryRequest(
            workspace_id=workspace_id,
            channel=OutboundDeliveryChannel.IMESSAGE,
            to="lead@example.com",
            from_="owner@example.com",
            body="Hello",
            idempotency_key=key,
            mac_relay_service="imessage",
            action_type="manual_imessage",
        ),
    )

    assert result.status is OutboundDeliveryStatus.SENT
    assert result.provider == "mac_relay"
    assert result.provider_message_id == "mac-relay:abc"
    assert result.idempotency_key == key
    assert provider_calls == [("mac_relay", "imessage")]
    provider.send_message.assert_awaited_once_with(
        to_number="lead@example.com",
        from_number="owner@example.com",
        body="Hello",
        db=ANY,
        workspace_id=workspace_id,
        agent_id=None,
        campaign_id=None,
        phone_number_id=None,
        idempotency_key=key,
    )
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_sms_delivery_blocks_global_opt_out_before_provider_call() -> None:
    message = SimpleNamespace(
        id=uuid.uuid4(),
        status=MessageStatus.SENT,
        provider_message_id="msg_123",
        error_message=None,
    )
    provider = _FakeTextProvider(message)
    service = OutboundDeliveryService(
        text_provider_factory=lambda preferred_provider=None, *, mac_relay_service=None: provider,
        email_provider=_FakeEmailProvider(),
        push_provider=_FakePushProvider(),
        opt_out_manager=_FakeOptOutManager(opted_out=True),
    )

    result = await service.deliver(
        AsyncMock(),
        OutboundDeliveryRequest(
            workspace_id=uuid.uuid4(),
            channel=OutboundDeliveryChannel.SMS,
            to="+12025550123",
            from_="+12025550199",
            body="Hello",
            action_type="campaign_sms",
        ),
    )

    assert result.status is OutboundDeliveryStatus.BLOCKED
    assert result.reason == "global_opt_out"
    provider.send_message.assert_not_awaited()
    provider.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_delivery_forwards_resend_idempotency_key() -> None:
    key = uuid.uuid4()
    email_provider = _FakeEmailProvider()
    service = OutboundDeliveryService(
        text_provider_factory=_unused_text_provider_factory,
        email_provider=email_provider,
        push_provider=_FakePushProvider(),
        opt_out_manager=_FakeOptOutManager(),
    )

    result = await service.deliver(
        AsyncMock(),
        OutboundDeliveryRequest(
            workspace_id=uuid.uuid4(),
            channel=OutboundDeliveryChannel.EMAIL,
            to="owner@example.com",
            subject="Booked",
            html="<p>Booked</p>",
            idempotency_key=key,
            action_type="appointment_email",
        ),
    )

    assert result.status is OutboundDeliveryStatus.SENT
    assert result.provider == "resend"
    assert result.provider_message_id == "email_123"
    assert email_provider.calls == [
        (
            {
                "from": "AI CRM <noreply@example.com>",
                "to": ["owner@example.com"],
                "subject": "Booked",
                "html": "<p>Booked</p>",
            },
            key,
        )
    ]


@pytest.mark.asyncio
async def test_push_delivery_blocks_disabled_user_preference() -> None:
    user = SimpleNamespace(
        id=42,
        is_active=True,
        notification_push=False,
    )
    push_provider = _FakePushProvider()
    service = OutboundDeliveryService(
        text_provider_factory=_unused_text_provider_factory,
        email_provider=_FakeEmailProvider(),
        push_provider=push_provider,
        opt_out_manager=_FakeOptOutManager(),
    )

    result = await service.deliver(
        AsyncMock(),
        OutboundDeliveryRequest(
            workspace_id=uuid.uuid4(),
            channel=OutboundDeliveryChannel.PUSH,
            user=user,
            user_id=user.id,
            title="Approval needed",
            body="Review this action",
            action_type="approval_push",
        ),
    )

    assert result.status is OutboundDeliveryStatus.BLOCKED
    assert result.reason == "recipient_push_disabled"
    assert push_provider.user_calls == []
