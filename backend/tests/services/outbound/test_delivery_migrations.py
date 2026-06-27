"""Coverage for representative send paths migrated to outbound delivery."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.campaign import CampaignContactStatus
from app.services.approval import approval_delivery_service as approval_module
from app.services.approval.approval_delivery_service import (
    PushApprovalDeliveryHandler,
    SmsApprovalDeliveryHandler,
)
from app.services.campaigns import sms_fallback as sms_fallback_module
from app.services.campaigns.sms_fallback import send_sms_fallback
from app.services.nudges import nudge_delivery as nudge_module
from app.services.nudges.nudge_delivery import NudgeDeliveryService
from app.services.outbound.delivery import OutboundDeliveryChannel, OutboundDeliveryStatus


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _MembershipResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)


class _FakeOutboundService:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def deliver(self, db: Any, request: Any) -> Any:
        self.requests.append(request)
        return SimpleNamespace(
            delivered=True,
            status=OutboundDeliveryStatus.SENT,
            message=SimpleNamespace(id=uuid.uuid4(), conversation_id=uuid.uuid4()),
            reason=None,
        )


@pytest.mark.asyncio
async def test_approval_sms_handler_uses_outbound_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_service = _FakeOutboundService()
    monkeypatch.setattr(approval_module, "outbound_delivery_service", fake_service)
    monkeypatch.setattr(
        approval_module,
        "get_workspace_sms_number",
        AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4(), phone_number="+12025550199")),
    )
    workspace_id = uuid.uuid4()
    action_id = uuid.uuid4()

    delivered = await SmsApprovalDeliveryHandler().send_sms(
        AsyncMock(),
        workspace_id=workspace_id,
        to_number="+12025550123",
        action_id=action_id,
        agent_name="Front Desk",
        description="Send a follow-up",
    )

    assert delivered is True
    request = fake_service.requests[0]
    assert request.workspace_id == workspace_id
    assert request.channel is OutboundDeliveryChannel.SMS
    assert request.to == "+12025550123"
    assert request.from_ == "+12025550199"
    assert request.idempotency_scope == "approval_notification_sms"
    assert request.idempotency_parts == (action_id,)


@pytest.mark.asyncio
async def test_approval_push_handler_uses_outbound_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_service = _FakeOutboundService()
    monkeypatch.setattr(approval_module, "outbound_delivery_service", fake_service)
    workspace_id = uuid.uuid4()
    action = SimpleNamespace(id=uuid.uuid4(), description="Approve this", workspace_id=workspace_id)

    delivered = await PushApprovalDeliveryHandler().send_push(
        AsyncMock(),
        workspace_id=workspace_id,
        action=action,
        agent_name="Concierge",
    )

    assert delivered is True
    request = fake_service.requests[0]
    assert request.channel is OutboundDeliveryChannel.PUSH
    assert request.title == "Approval needed from Concierge"
    assert request.idempotency_scope == "approval_notification_push"
    assert request.idempotency_parts == (action.id,)


@pytest.mark.asyncio
async def test_nudge_delivery_uses_outbound_for_push_and_sms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_service = _FakeOutboundService()
    monkeypatch.setattr(nudge_module, "outbound_delivery_service", fake_service)
    phone = SimpleNamespace(id=uuid.uuid4(), phone_number="+12025550199")
    monkeypatch.setattr(nudge_module, "get_workspace_sms_number", AsyncMock(return_value=phone))
    monkeypatch.setattr(nudge_module.settings, "telnyx_api_key", "telnyx-key")
    # Pin quiet-hours off so SMS delivery is exercised regardless of wall-clock
    # time (default quiet hours are 22:00-08:00 UTC and would otherwise make
    # this assertion time-dependent / flaky).
    monkeypatch.setattr(
        nudge_module.NudgeDeliveryService, "_is_quiet_hours", lambda self, ws: False
    )
    workspace_id = uuid.uuid4()
    user = SimpleNamespace(id=7, is_active=True, notification_sms=True, phone_number="+12025550123")
    workspace = SimpleNamespace(
        id=workspace_id,
        settings={"nudge_settings": {"delivery_channels": ["push", "sms"], "quiet_hours": {}}},
    )
    nudge = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        title="Follow up",
        message="Call this lead",
        assigned_to_user_id=7,
        status="pending",
        delivered_at=None,
        delivered_via=None,
    )
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[_ExecuteResult([workspace]), _ExecuteResult([user])])
    db.commit = AsyncMock()

    delivered = await NudgeDeliveryService().deliver_nudge(db, nudge)

    assert delivered is True
    assert [request.channel for request in fake_service.requests] == [
        OutboundDeliveryChannel.PUSH,
        OutboundDeliveryChannel.SMS,
    ]
    assert fake_service.requests[0].idempotency_scope == "nudge_push"
    assert fake_service.requests[1].idempotency_scope == "nudge_sms"
    assert nudge.status == "sent"
    assert nudge.delivered_via == "push,sms"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_campaign_sms_fallback_uses_outbound_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_service = _FakeOutboundService()
    monkeypatch.setattr(sms_fallback_module, "outbound_delivery_service", fake_service)
    workspace_id = uuid.uuid4()
    campaign = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        sms_fallback_enabled=True,
        sms_fallback_use_ai=False,
        sms_fallback_template="Hi {first_name}, sorry we missed you.",
        sms_fallback_agent_id=None,
        agent_id=uuid.uuid4(),
        from_phone_number="+12025550199",
        sms_fallbacks_sent=0,
        messages_sent=0,
    )
    campaign_contact = SimpleNamespace(
        id=uuid.uuid4(),
        sms_fallback_sent=False,
        sms_fallback_sent_at=None,
        sms_fallback_message_id=None,
        status=None,
        conversation_id=None,
        messages_sent=0,
        last_error=None,
    )
    contact = SimpleNamespace(
        id=123,
        first_name="Ada",
        last_name="Lovelace",
        company_name="Analytical Engines",
        email="ada@example.com",
        phone_number="+12025550123",
        sms_consent_status="opted_in",
    )
    db = AsyncMock()
    db.commit = AsyncMock()

    delivered = await send_sms_fallback(
        db=db,
        campaign=campaign,
        campaign_contact=campaign_contact,
        contact=contact,
        call_outcome="no_answer",
        telnyx_api_key="telnyx-key",
    )

    assert delivered is True
    request = fake_service.requests[0]
    assert request.channel is OutboundDeliveryChannel.SMS
    assert request.body == "Hi Ada, sorry we missed you."
    assert request.contact is contact
    assert request.campaign is campaign
    assert request.campaign_contact is campaign_contact
    assert request.idempotency_scope == "voice_campaign_sms_fallback"
    assert request.idempotency_parts == (campaign_contact.id, "no_answer")
    assert request.require_sms_consent is True
    assert campaign_contact.status is CampaignContactStatus.SMS_FALLBACK_SENT
    assert campaign_contact.sms_fallback_sent is True
    assert campaign.sms_fallbacks_sent == 1
    assert campaign.messages_sent == 1
    db.commit.assert_awaited_once()
