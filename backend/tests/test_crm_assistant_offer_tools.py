"""Tests for CRM assistant offer management tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent import Agent
from app.models.campaign import Campaign, CampaignStatus
from app.models.contact import Contact
from app.models.offer import Offer
from app.models.pending_action import PendingAction
from app.models.phone_number import PhoneNumber
from app.models.segment import Segment
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import get_approved_action_executor
from app.services.ai.crm_assistant._tools import get_crm_tools
from app.services.approval.approval_gate_service import ApprovalGateService


def _make_agent(**overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Front Desk",
        "description": "Books appointments",
        "channel_mode": "both",
        "voice_provider": "openai",
        "voice_id": "alloy",
        "language": "en-US",
        "system_prompt": "Be helpful.",
        "temperature": 0.7,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "calcom_event_type_id": None,
        "enabled_tools": ["book_appointment"],
        "tool_settings": {},
        "is_active": True,
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Agent(**defaults)


def _make_campaign(**overrides: Any) -> Campaign:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "agent_id": None,
        "name": "Spring Winback",
        "status": CampaignStatus.DRAFT,
        "from_phone_number": "+15550001111",
        "initial_message": "Hi {first_name}, want to book a tune-up?",
        "ai_enabled": True,
        "timezone": "America/New_York",
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Campaign(**defaults)


def _make_contact(**overrides: Any) -> Contact:
    defaults: dict[str, Any] = {
        "id": 101,
        "workspace_id": uuid.uuid4(),
        "first_name": "Ava",
        "last_name": "Rivera",
        "phone_number": "+1555000101",
        "phone_hash": "phone-hash",
        "email": "ava@example.com",
        "email_hash": "email-hash",
        "company_name": "Rivera Co",
        "status": "new",
        "lead_score": 50,
        "is_qualified": False,
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Contact(**defaults)


def _make_segment(**overrides: Any) -> Segment:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Dormant homeowners",
        "description": "Homeowners who have not booked recently",
        "definition": {
            "logic": "and",
            "rules": [{"field": "status", "operator": "equals", "value": "new"}],
        },
        "is_dynamic": True,
        "contact_count": 42,
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Segment(**defaults)


def _make_phone_number(**overrides: Any) -> PhoneNumber:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "phone_number": "+15550001111",
        "friendly_name": "Main line",
        "sms_enabled": True,
        "voice_enabled": True,
        "is_active": True,
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return PhoneNumber(**defaults)


def _make_offer(**overrides: Any) -> Offer:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Spring Tune-Up",
        "description": "Seasonal HVAC campaign offer",
        "discount_type": "fixed",
        "discount_value": 50.0,
        "terms": "New customers only",
        "valid_from": None,
        "valid_until": None,
        "is_active": False,
        "headline": "Get your system ready for spring",
        "subheadline": "Limited tune-up savings",
        "regular_price": 199.0,
        "offer_price": 149.0,
        "savings_amount": 50.0,
        "guarantee_type": "satisfaction",
        "guarantee_days": 30,
        "guarantee_text": "Love it or we make it right.",
        "urgency_type": "limited_time",
        "urgency_text": "Book this week",
        "scarcity_count": 25,
        "value_stack_items": [
            {
                "name": "Inspection",
                "description": "Full system inspection",
                "value": 99.0,
                "included": True,
            }
        ],
        "cta_text": "Book now",
        "cta_subtext": "No obligation",
        "is_public": False,
        "public_slug": None,
        "require_email": True,
        "require_phone": False,
        "require_name": False,
        "page_views": 0,
        "opt_ins": 0,
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Offer(**defaults)


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

    def scalar_one(self) -> Any:
        return self._rows[0]

    def scalar(self) -> Any | None:
        return self._rows[0] if self._rows else None


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


def test_offer_tools_are_registered() -> None:
    names = {tool["function"]["name"] for tool in get_crm_tools()}

    assert {
        "list_offers",
        "get_offer_details",
        "create_offer_draft",
        "update_offer_draft",
        "plan_outbound_growth_workflow",
        "send_initial_message",
        "start_campaign",
        "create_agent",
        "update_agent",
        "assign_ai_responder",
    }.issubset(names)


def test_approval_tool_metadata_drives_schema_and_executor_bindings() -> None:
    tools_by_name = {tool["function"]["name"]: tool for tool in get_crm_tools()}
    confirmation_required = {
        "send_sms",
        "send_initial_message",
        "start_campaign",
        "resume_campaign",
        "create_agent",
        "update_agent",
        "assign_ai_responder",
    }

    for tool_name in confirmation_required:
        assert "confirmed" in tools_by_name[tool_name]["function"]["parameters"]["properties"]
        assert get_approved_action_executor(f"crm_assistant.{tool_name}") is not None

    pause_properties = tools_by_name["pause_campaign"]["function"]["parameters"]["properties"]
    assert "confirmed" not in pause_properties
    assert get_approved_action_executor("crm_assistant.pause_campaign") is None


async def test_list_offers_returns_campaign_ready_summaries(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    offer = _make_offer(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([offer])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("list_offers", {"limit": 5, "active_only": True})

    assert result["success"] is True
    assert result["count"] == 1
    assert result["data"] == [
        {
            "id": str(offer.id),
            "name": "Spring Tune-Up",
            "description": "Seasonal HVAC campaign offer",
            "discount_type": "fixed",
            "discount_value": 50.0,
            "is_active": False,
            "headline": "Get your system ready for spring",
            "offer_price": 149.0,
            "cta_text": "Book now",
            "valid_until": None,
        }
    ]


async def test_get_offer_details_rejects_invalid_offer_id(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("get_offer_details", {"offer_id": "not-a-uuid"})

    assert result == {"success": False, "error": "Invalid offer_id"}
    db.execute.assert_not_called()


async def test_get_offer_details_returns_full_offer(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    offer = _make_offer(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([offer])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("get_offer_details", {"offer_id": str(offer.id)})

    assert result["success"] is True
    assert result["data"]["id"] == str(offer.id)
    assert result["data"]["terms"] == "New customers only"
    assert result["data"]["value_stack_items"] == offer.value_stack_items
    assert result["data"]["created_at"] == "2026-05-01T00:00:00+00:00"
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_get_offer_details_hides_cross_workspace_offers(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    db.execute.return_value = _ExecuteResult([])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("get_offer_details", {"offer_id": str(uuid.uuid4())})

    assert result == {"success": False, "error": "Offer not found"}
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_create_offer_draft_forces_inactive_draft(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "create_offer_draft",
        {
            "name": "Outbound Promo",
            "description": "For winback SMS",
            "discount_type": "percentage",
            "discount_value": 15,
            "is_active": True,
            "value_stack_items": [{"name": "Audit", "value": 100}],
        },
    )

    assert result["success"] is True
    created_offer = db.add.call_args.args[0]
    assert isinstance(created_offer, Offer)
    assert created_offer.workspace_id == workspace_id
    assert created_offer.name == "Outbound Promo"
    assert created_offer.is_active is False
    assert created_offer.value_stack_items == [
        {"name": "Audit", "description": None, "value": 100.0, "included": True}
    ]
    db.flush.assert_awaited_once()


async def test_update_offer_draft_validates_and_updates_existing_offer(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    offer = _make_offer(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([offer])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "update_offer_draft",
        {
            "offer_id": str(offer.id),
            "headline": "Fresh campaign headline",
            "offer_price": 129,
            "cta_text": "Claim offer",
        },
    )

    assert result["success"] is True
    assert offer.headline == "Fresh campaign headline"
    assert offer.offer_price == 129.0
    assert offer.cta_text == "Claim offer"
    assert result["data"]["headline"] == "Fresh campaign headline"
    db.flush.assert_awaited_once()


async def test_update_offer_draft_requires_fields(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    offer = _make_offer(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([offer])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("update_offer_draft", {"offer_id": str(offer.id)})

    assert result == {"success": False, "error": "No offer fields provided"}
    db.flush.assert_not_awaited()


async def test_gated_outbound_action_creates_pending_action(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "create_agent",
        {"name": "Closer", "system_prompt": "Qualify and book."},
    )

    assert result == {
        "success": False,
        "pending_approval": True,
        "pending_action_id": str(db.add.call_args.args[0].id),
        "message": "Approval required before I can create this AI agent.",
    }
    pending_action = db.add.call_args.args[0]
    assert pending_action.workspace_id == workspace_id
    assert pending_action.agent_id is None
    assert pending_action.action_type == "crm_assistant.create_agent"
    assert pending_action.action_payload == {"name": "Closer", "system_prompt": "Qualify and book."}
    assert pending_action.description == "Create AI agent Closer"
    assert pending_action.context == {
        "source": "crm_assistant",
        "user_id": 7,
        "risk_level": "high",
        "requires_confirmation": True,
    }
    assert pending_action.urgency == "normal"


async def test_approved_crm_assistant_pending_action_executes_bound_tool(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    action = PendingAction(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        agent_id=None,
        action_type="crm_assistant.create_agent",
        action_payload={"name": "Closer", "system_prompt": "Qualify and book."},
        description="Create AI agent Closer",
        context={"source": "crm_assistant", "user_id": 7},
        status="approved",
    )
    service = ApprovalGateService()

    result = await service.execute_approved_action(db, action)

    assert result["success"] is True
    assert result["tool"] == "create_agent"
    assert action.status == "executed"
    assert action.execution_result == result
    created_agent = db.add.call_args.args[0]
    assert isinstance(created_agent, Agent)
    assert created_agent.workspace_id == workspace_id
    assert created_agent.name == "Closer"
    db.flush.assert_awaited_once()
    assert db.commit.await_count == 1


async def test_rejected_crm_assistant_pending_action_does_not_execute(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    action = PendingAction(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        agent_id=None,
        action_type="crm_assistant.create_agent",
        action_payload={"name": "Closer", "system_prompt": "Qualify and book."},
        description="Create AI agent Closer",
        context={"source": "crm_assistant", "user_id": 7},
        status="pending",
    )
    db.execute.return_value = _ExecuteResult([action])
    service = ApprovalGateService()

    rejected = await service.reject_action(
        db=db,
        action_id=action.id,
        user_id=42,
        reason="Needs edits",
    )
    result = await service.execute_approved_action(db, rejected)

    assert rejected.status == "rejected"
    assert rejected.reviewed_by_id == 42
    assert rejected.rejection_reason == "Needs edits"
    assert result == {
        "error": "action_not_approved",
        "action_id": str(action.id),
        "status": "rejected",
    }
    db.add.assert_not_called()


async def test_outbound_growth_workflow_asks_for_missing_context(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    db.execute.side_effect = [
        _ExecuteResult([]),
        _ExecuteResult([]),
        _ExecuteResult([]),
        _ExecuteResult([]),
        _ExecuteResult([]),
        _ExecuteResult([]),
    ]
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "plan_outbound_growth_workflow",
        {"intent": "let's reach out to some people"},
    )

    assert result["success"] is True
    assert result["status"] == "needs_input"
    assert [item["field"] for item in result["missing_inputs"]] == [
        "offer_id",
        "segment_id",
        "from_phone_number",
    ]
    assert "Choose an offer" in result["next_approval_step"]


async def test_outbound_growth_workflow_rejects_cross_workspace_sending_number(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    offer = _make_offer(workspace_id=workspace_id)
    segment = _make_segment(workspace_id=workspace_id)
    db.execute.side_effect = [
        _ExecuteResult([offer]),
        _ExecuteResult([segment]),
        _ExecuteResult([]),
        _ExecuteResult([]),
    ]
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "plan_outbound_growth_workflow",
        {
            "intent": "reach out to dormant homeowners",
            "offer_id": str(offer.id),
            "segment_id": str(segment.id),
            "from_phone_number": "+15559999999",
        },
    )

    assert result["success"] is True
    assert result["status"] == "needs_input"
    assert [item["field"] for item in result["missing_inputs"]] == ["from_phone_number"]
    compiled = str(
        db.execute.await_args_list[2].args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled
    assert "+15559999999" in compiled
    db.add.assert_not_called()


async def test_outbound_growth_workflow_creates_draft_campaign(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    offer = _make_offer(workspace_id=workspace_id)
    segment = _make_segment(workspace_id=workspace_id)
    phone = _make_phone_number(workspace_id=workspace_id)
    contact = _make_contact(workspace_id=workspace_id)
    agent = _make_agent(workspace_id=workspace_id)
    db.execute.side_effect = [
        _ExecuteResult([offer]),
        _ExecuteResult([segment]),
        _ExecuteResult([phone]),
        _ExecuteResult([contact]),
        _ExecuteResult([agent]),
        _ExecuteResult([1]),
    ]
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "plan_outbound_growth_workflow",
        {
            "intent": "let's reach out to dormant homeowners",
            "offer_id": str(offer.id),
            "segment_id": str(segment.id),
            "from_phone_number": "+15550001111",
            "create_draft": True,
        },
    )

    assert result["success"] is True
    assert result["status"] == "draft_ready"
    assert result["draft"]["created"] is True
    assert result["responder_agent"]["action"] == "recommended_existing"
    assert result["previews"][0]["message"].startswith("Hi Ava")
    # Preview CampaignContact rows are added after the Campaign itself.
    added_objects = [call.args[0] for call in db.add.call_args_list]
    created_campaign = next(obj for obj in added_objects if isinstance(obj, Campaign))
    assert created_campaign.workspace_id == workspace_id
    assert created_campaign.offer_id == offer.id
    assert created_campaign.agent_id == agent.id
    assert created_campaign.status == CampaignStatus.DRAFT
    assert created_campaign.initial_message is not None
    assert "{first_name}" in created_campaign.initial_message
    assert "explicitly confirm start_campaign" in result["next_approval_step"]


async def test_confirmed_agent_creation_executes_immediately(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "create_agent",
        {"name": "Closer", "system_prompt": "Qualify and book.", "confirmed": True},
    )

    assert result["success"] is True
    created_agent = db.add.call_args.args[0]
    assert isinstance(created_agent, Agent)
    assert created_agent.workspace_id == workspace_id
    assert created_agent.name == "Closer"
    db.flush.assert_awaited_once()


async def test_confirmed_start_campaign_runs_existing_validation(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    campaign = _make_campaign(workspace_id=workspace_id)
    db.execute.side_effect = [_ExecuteResult([campaign]), _ExecuteResult([2])]
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "start_campaign",
        {"campaign_id": str(campaign.id), "confirmed": True},
    )

    assert result["success"] is True
    assert campaign.status == CampaignStatus.RUNNING
    assert campaign.started_at is not None
    db.flush.assert_awaited_once()


async def test_confirmed_start_campaign_rejects_empty_campaign(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    campaign = _make_campaign(workspace_id=workspace_id)
    db.execute.side_effect = [_ExecuteResult([campaign]), _ExecuteResult([0])]
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "start_campaign",
        {"campaign_id": str(campaign.id), "confirmed": True},
    )

    assert result == {"success": False, "error": "Campaign has no contacts"}
    db.flush.assert_not_awaited()
