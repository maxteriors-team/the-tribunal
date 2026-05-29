"""Campaign worker iMessage sender routing tests."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.campaign import CampaignContactStatus
from app.models.conversation import Message, MessageChannel, MessageStatus
from app.workers.campaign_worker import CampaignWorker
from tests.factories import (
    CampaignContactFactory,
    CampaignFactory,
    ContactFactory,
    PhoneNumberFactory,
)


class _ScalarsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


class _ExecuteResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarsResult:
        return _ScalarsResult(self._rows)


async def test_initial_message_uses_mac_relay_for_imessage_sender() -> None:
    workspace_id = uuid.uuid4()
    campaign = CampaignFactory.build(
        workspace_id=workspace_id,
        from_phone_number="+15551230000",
        initial_message="Hi {first_name}",
    )
    contact = ContactFactory.build(
        id=123,
        workspace_id=workspace_id,
        first_name="Ava",
        phone_number="+15559870000",
    )
    campaign_contact = CampaignContactFactory.build(
        campaign=campaign,
        campaign_id=campaign.id,
        contact=contact,
        contact_id=contact.id,
        status=CampaignContactStatus.PENDING,
    )
    from_phone = PhoneNumberFactory.build(
        workspace_id=workspace_id,
        phone_number="+15551230000",
        imessage_enabled=True,
        mac_relay_sender_id="owner@example.com",
        mac_relay_service="imessage",
    )
    outbound_message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        direction="outbound",
        channel=MessageChannel.IMESSAGE,
        body="Hi Ava",
        status=MessageStatus.SENT,
    )
    text_service = AsyncMock()
    text_service.send_message = AsyncMock(return_value=outbound_message)

    worker = CampaignWorker()
    worker.rate_limiter.check_campaign_rate_limit = AsyncMock(return_value=True)
    worker.number_pool.peek_next_available_number = AsyncMock(return_value=from_phone)
    worker.number_pool.reserve_number_for_send = AsyncMock(return_value=True)
    worker.compliance_service.evaluate = AsyncMock(
        return_value=MagicMock(allowed=True, reason=None)
    )
    worker.compliance_service.apply_suppression = MagicMock()
    worker.reputation_tracker.increment_sent = AsyncMock()

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ExecuteResult([campaign_contact]))
    db.flush = AsyncMock()

    with patch(
        "app.workers.campaign_worker.get_text_message_provider",
        MagicMock(return_value=text_service),
    ) as get_provider:
        await worker._process_initial_messages(campaign, {}, db, MagicMock())

    get_provider.assert_called_once_with("mac_relay", mac_relay_service="imessage")
    text_service.send_message.assert_awaited_once()
    send_kwargs = text_service.send_message.await_args.kwargs
    assert send_kwargs["to_number"] == contact.phone_number
    assert send_kwargs["from_number"] == "owner@example.com"
    assert send_kwargs["phone_number_id"] == from_phone.id
    assert campaign_contact.status == CampaignContactStatus.SENT
    assert campaign_contact.conversation_id == outbound_message.conversation_id
    assert campaign.messages_sent == 1
    worker.compliance_service.evaluate.assert_awaited_once()
    compliance_request = worker.compliance_service.evaluate.await_args.args[0]
    assert compliance_request.channel == "imessage"
    assert compliance_request.action_type == "campaign_initial_imessage"


async def test_initial_message_uses_telnyx_for_sms_sender() -> None:
    workspace_id = uuid.uuid4()
    campaign = CampaignFactory.build(workspace_id=workspace_id, initial_message="Hi {first_name}")
    contact = ContactFactory.build(id=124, workspace_id=workspace_id, first_name="Sam")
    campaign_contact = CampaignContactFactory.build(
        campaign=campaign,
        campaign_id=campaign.id,
        contact=contact,
        contact_id=contact.id,
        status=CampaignContactStatus.PENDING,
    )
    from_phone = PhoneNumberFactory.build(
        workspace_id=workspace_id,
        imessage_enabled=False,
        mac_relay_sender_id="owner@example.com",
    )
    outbound_message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        direction="outbound",
        channel=MessageChannel.SMS,
        body="Hi Sam",
        status=MessageStatus.SENT,
    )
    text_service = AsyncMock()
    text_service.send_message = AsyncMock(return_value=outbound_message)

    worker = CampaignWorker()
    worker.rate_limiter.check_campaign_rate_limit = AsyncMock(return_value=True)
    worker.number_pool.peek_next_available_number = AsyncMock(return_value=from_phone)
    worker.number_pool.reserve_number_for_send = AsyncMock(return_value=True)
    worker.compliance_service.evaluate = AsyncMock(
        return_value=MagicMock(allowed=True, reason=None)
    )
    worker.compliance_service.apply_suppression = MagicMock()
    worker.reputation_tracker.increment_sent = AsyncMock()

    db = MagicMock()
    db.execute = AsyncMock(return_value=_ExecuteResult([campaign_contact]))
    db.flush = AsyncMock()

    with patch(
        "app.workers.campaign_worker.get_text_message_provider",
        MagicMock(return_value=text_service),
    ) as get_provider:
        await worker._process_initial_messages(campaign, {}, db, MagicMock())

    get_provider.assert_called_once_with(None, mac_relay_service=None)
    send_kwargs = text_service.send_message.await_args.kwargs
    assert send_kwargs["from_number"] == from_phone.phone_number
    compliance_request = worker.compliance_service.evaluate.await_args.args[0]
    assert compliance_request.channel == "sms"
    assert compliance_request.action_type == "campaign_initial_sms"
