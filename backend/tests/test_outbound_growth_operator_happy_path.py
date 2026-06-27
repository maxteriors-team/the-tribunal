"""Happy-path coverage for the outbound growth operator workflow."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignContact, CampaignContactStatus, CampaignStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.drip_campaign import ResponseCategory
from app.models.offer import Offer
from app.models.opportunity import Opportunity
from app.models.pending_action import PendingAction
from app.models.pipeline import Pipeline, PipelineStage
from app.models.segment import Segment
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.campaigns.reply_handler import handle_campaign_reply
from app.workers.campaign_worker import CampaignWorker


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


def _make_offer(workspace_id: uuid.UUID) -> Offer:
    return Offer(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Batch Video Ads",
        description="Batch-produced video ads for local businesses",
        discount_type="fixed",
        discount_value=500.0,
        headline="Launch a month of scroll-stopping video ads in one batch",
        cta_text="claim your Batch Video Ads audit",
        is_active=True,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, tzinfo=UTC),
    )


def _make_segment(workspace_id: uuid.UUID) -> Segment:
    return Segment(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Dormant ecommerce leads",
        description="Leads who asked about creative strategy but never booked",
        definition={
            "logic": "and",
            "rules": [{"field": "status", "operator": "equals", "value": "new"}],
        },
        is_dynamic=True,
        contact_count=2,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, tzinfo=UTC),
    )


def _make_agent(workspace_id: uuid.UUID) -> Agent:
    return Agent(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        name="Batch Video Ads Responder",
        description="Qualifies replies for Batch Video Ads",
        channel_mode="text",
        voice_provider="openai",
        voice_id="alloy",
        language="en-US",
        system_prompt="Qualify interest and hand warm leads to humans.",
        temperature=0.4,
        text_response_delay_ms=1000,
        text_max_context_messages=20,
        enabled_tools=["book_appointment"],
        tool_settings={},
        is_active=True,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, tzinfo=UTC),
    )


def _make_contact(contact_id: int, workspace_id: uuid.UUID, first_name: str, phone: str) -> Contact:
    return Contact(
        id=contact_id,
        workspace_id=workspace_id,
        first_name=first_name,
        last_name="Rivera",
        phone_number=phone,
        phone_hash=f"hash-{contact_id}",
        email=f"{first_name.lower()}@example.com",
        email_hash=f"email-hash-{contact_id}",
        company_name="Rivera Retail",
        status="new",
        lead_score=60,
        is_qualified=False,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, tzinfo=UTC),
    )


async def test_outbound_growth_operator_happy_path_drafts_sends_assigns_and_hands_off() -> None:  # noqa: PLR0915
    workspace_id = uuid.uuid4()
    offer = _make_offer(workspace_id)
    segment = _make_segment(workspace_id)
    responder = _make_agent(workspace_id)
    contacts = [
        _make_contact(101, workspace_id, "Ava", "+1555000101"),
        _make_contact(102, workspace_id, "Mia", "+1555000102"),
    ]
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.get = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _ExecuteResult([offer]),
            _ExecuteResult([segment]),
            # _resolve_phone_number always queries for the sending number, even
            # when one is supplied, so it must be accounted for here.
            _ExecuteResult([MagicMock(phone_number="+15550009999")]),
            _ExecuteResult(contacts),
            _ExecuteResult([responder]),
            _ExecuteResult([len(contacts)]),
        ]
    )
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    draft_result = await executor.execute(
        "plan_outbound_growth_workflow",
        {
            "intent": "Reach out about Batch Video Ads to dormant ecommerce leads",
            "offer_id": str(offer.id),
            "segment_id": str(segment.id),
            "from_phone_number": "+15550009999",
            "create_draft": True,
        },
    )

    assert draft_result["success"] is True
    assert draft_result["status"] == "draft_ready"
    assert draft_result["offer"]["name"] == "Batch Video Ads"
    assert draft_result["segment"]["contact_count"] == len(contacts)
    assert [preview["contact_name"] for preview in draft_result["previews"]] == [
        "Ava Rivera",
        "Mia Rivera",
    ]
    assert draft_result["previews"][0]["message"].startswith("Hi Ava")
    assert "batch video ads audit" in draft_result["messages"]["initial"]
    assert draft_result["responder_agent"] == {
        "action": "recommended_existing",
        "agent_id": str(responder.id),
        "name": "Batch Video Ads Responder",
        "rationale": (
            "Use the existing active text/both responder so replies stay in the current "
            "operating model."
        ),
        "system_prompt": None,
    }
    campaign = next(
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Campaign)
    )
    campaign.id = uuid.uuid4()
    campaign.messages_sent = 0
    campaign.messages_failed = 0
    campaign.contacts_opted_out = 0
    campaign.error_count = 0
    campaign.follow_up_enabled = False
    assert campaign.name == "Batch Video Ads → Dormant ecommerce leads"
    assert campaign.agent_id == responder.id
    assert campaign.status == CampaignStatus.DRAFT
    # Enrollment adds CampaignContact rows directly via db.add (appending to the
    # lazy campaign.campaign_contacts collection would emit a sync lazy-load and
    # raise MissingGreenlet under the async engine).
    enrolled = [
        call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], CampaignContact)
    ]
    assert [link.contact_id for link in enrolled] == [101, 102]

    db.execute = AsyncMock(
        side_effect=[_ExecuteResult([campaign]), _ExecuteResult([len(contacts)])]
    )
    start_result = await executor.execute(
        "start_campaign",
        {"campaign_id": str(campaign.id), "confirmed": True},
    )

    assert start_result["success"] is True
    assert start_result["data"] == {
        "campaign_id": str(campaign.id),
        "status": "running",
        "contact_count": len(contacts),
    }
    assert campaign.status == CampaignStatus.RUNNING

    campaign_contact = CampaignContact(
        id=uuid.uuid4(),
        campaign_id=campaign.id,
        campaign=campaign,
        contact_id=contacts[0].id,
        contact=contacts[0],
        status=CampaignContactStatus.PENDING,
        opted_out=False,
        messages_sent=0,
        follow_ups_sent=0,
    )
    outbound_message = Message(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        direction="outbound",
        channel="sms",
        body="Hi Ava, quick note — Batch Video Ads.",
        status=MessageStatus.SENT,
    )
    from_phone = MagicMock()
    from_phone.id = uuid.uuid4()
    from_phone.phone_number = "+15550009999"
    # Plain SMS sender (not an iMessage relay) so the provider-facing address is
    # the phone number rather than a mac_relay_sender_id.
    from_phone.imessage_enabled = False
    sms_service = AsyncMock()
    sms_service.send_message = AsyncMock(return_value=outbound_message)
    worker = CampaignWorker()
    worker.rate_limiter.check_campaign_rate_limit = AsyncMock(return_value=True)
    worker.number_pool.peek_next_available_number = AsyncMock(return_value=from_phone)
    worker.number_pool.reserve_number_for_send = AsyncMock(return_value=True)
    worker.compliance_service.evaluate = AsyncMock(
        return_value=MagicMock(allowed=True, reason=None)
    )
    worker.compliance_service.apply_suppression = MagicMock()
    worker.reputation_tracker.increment_sent = AsyncMock()
    db.execute = AsyncMock(return_value=_ExecuteResult([campaign_contact]))

    # The worker resolves the per-sender transport through a TextProviderCache
    # via ``_get_text_provider``; point it at the stub so the send path is
    # exercised against our mock provider.
    with patch.object(worker, "_get_text_provider", return_value=sms_service):
        await worker._process_initial_messages(campaign, sms_service, db, MagicMock())

    sms_service.send_message.assert_awaited_once()
    send_kwargs = sms_service.send_message.await_args.kwargs
    assert send_kwargs["to_number"] == contacts[0].phone_number
    assert send_kwargs["from_number"] == "+15550009999"
    assert send_kwargs["agent_id"] == responder.id
    assert send_kwargs["body"].startswith("Hi Ava")
    assert campaign_contact.status == CampaignContactStatus.SENT
    assert campaign_contact.conversation_id == outbound_message.conversation_id
    assert campaign.messages_sent == 1
    campaign.replies_received = 0
    campaign.contacts_qualified = 0
    campaign.appointments_booked = 0
    campaign_contact.messages_received = 0
    campaign_contact.is_qualified = False

    conversation = Conversation(
        id=outbound_message.conversation_id,
        workspace_id=workspace_id,
        contact_id=contacts[0].id,
        contact_phone=contacts[0].phone_number,
        workspace_phone="+15550009999",
        assigned_agent_id=responder.id,
        ai_enabled=True,
        unread_count=0,
    )
    inbound_reply = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        direction="inbound",
        channel="sms",
        body="Yes, this is interesting. Can someone send details?",
        status=MessageStatus.RECEIVED,
        created_at=datetime(2026, 5, 20, 15, 0, tzinfo=UTC),
    )
    campaign_contact.status = CampaignContactStatus.DELIVERED
    db.get = AsyncMock(return_value=conversation)
    db.add.reset_mock()
    db.execute = AsyncMock(
        side_effect=[
            _ExecuteResult([campaign_contact]),
            _ExecuteResult([outbound_message, inbound_reply]),
            _ExecuteResult([]),
            _ExecuteResult([]),
            _ExecuteResult([]),
            _ExecuteResult([]),
        ]
    )

    with (
        patch(
            "app.services.campaigns.reply_handler.get_workspace_openai_bearer_token",
            AsyncMock(return_value="sk-test-workspace-token"),
        ),
        patch(
            "app.services.campaigns.reply_handler.classify_response",
            AsyncMock(return_value=ResponseCategory.INTERESTED),
        ),
        patch(
            "app.services.campaigns.reply_handler.push_notification_service.send_to_workspace_members",
            AsyncMock(),
        ),
    ):
        reply_result = await handle_campaign_reply(db, message=inbound_reply)

    assert reply_result is not None
    assert reply_result.category == ResponseCategory.INTERESTED
    assert reply_result.handoff_created is True
    assert campaign_contact.status == CampaignContactStatus.QUALIFIED
    assert conversation.assigned_agent_id == responder.id
    added_records = [call.args[0] for call in db.add.call_args_list]
    assert any(isinstance(record, Pipeline) for record in added_records)
    assert any(isinstance(record, PipelineStage) for record in added_records)
    assert any(isinstance(record, Opportunity) for record in added_records)
    handoff = next(record for record in added_records if isinstance(record, PendingAction))
    assert handoff.action_type == "campaign_reply_handoff"
    assert handoff.action_payload["category"] == "interested"
    assert handoff.context["campaign_id"] == str(campaign.id)
    assert handoff.context["conversation_id"] == str(conversation.id)
