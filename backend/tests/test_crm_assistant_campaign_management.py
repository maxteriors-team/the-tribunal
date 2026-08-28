"""Campaign creation, editing, detail listing, and enrollment coverage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.campaign import (
    Campaign,
    CampaignContact,
    CampaignContactStatus,
    CampaignStatus,
    CampaignType,
)
from app.models.contact import Contact
from app.services.ai.crm_assistant import _campaign_tools as campaign_module
from app.services.ai.crm_assistant._campaign_tools import CampaignAssistantTools
from app.services.ai.crm_assistant._tool_context import CRMToolContext
from app.services.ai.crm_assistant._tool_metadata import ToolRiskLevel, get_tool_policy
from app.services.ai.crm_assistant._tools import get_crm_tools


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def tools(db: MagicMock, workspace_id: uuid.UUID) -> CampaignAssistantTools:
    return CampaignAssistantTools(CRMToolContext(db=db, workspace_id=workspace_id, user_id=7, role="owner"))


def _campaign(workspace_id: uuid.UUID, **overrides: Any) -> Campaign:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": workspace_id,
        "agent_id": None,
        "offer_id": None,
        "name": "Spring Gutter Cleaning",
        "description": "Past-customer reactivation",
        "campaign_type": CampaignType.SMS,
        "status": CampaignStatus.DRAFT,
        "from_phone_number": "+14155550100",
        "use_number_pool": False,
        "initial_message": "Hi {first_name}, ready for spring gutter cleaning?",
        "email_subject": None,
        "ai_enabled": True,
        "qualification_criteria": "Interested in a spring visit",
        "scheduled_start": datetime(2026, 8, 1, 13, 0, tzinfo=UTC),
        "scheduled_end": None,
        "sending_hours_start": time(9, 0),
        "sending_hours_end": time(17, 0),
        "sending_days": [0, 1, 2, 3, 4],
        "timezone": "America/New_York",
        "messages_per_minute": 10,
        "max_messages_per_contact": 5,
        "max_messages_per_campaign": None,
        "quiet_hours_start": None,
        "quiet_hours_end": None,
        "quiet_hours_timezone": None,
        "follow_up_enabled": True,
        "follow_up_delay_hours": 24,
        "follow_up_message": "Just checking back, {first_name}.",
        "max_follow_ups": 2,
        "total_contacts": 999,
        "messages_sent": 10,
        "messages_delivered": 9,
        "messages_failed": 1,
        "replies_received": 3,
        "contacts_qualified": 2,
        "contacts_opted_out": 0,
        "appointments_booked": 1,
        "created_at": datetime(2026, 7, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 2, tzinfo=UTC),
    }
    values.update(overrides)
    return Campaign(**values)


def _contact(workspace_id: uuid.UUID) -> Contact:
    return Contact(
        id=512,
        workspace_id=workspace_id,
        first_name="Maria",
        last_name="Delgado",
        phone_number="+14155552671",
        phone_hash="phone-hash",
        email="maria@example.com",
        email_hash="email-hash",
        company_name="Delgado Homes",
        status="qualified",
    )


class TestRegistration:
    @pytest.mark.parametrize(
        "name", ["create_campaign", "update_campaign", "list_campaign_contacts"]
    )
    def test_schema_and_handler_registered(self, name: str, tools: CampaignAssistantTools) -> None:
        schemas = {tool["function"]["name"] for tool in get_crm_tools()}

        assert name in schemas
        assert name in tools.handlers()

    @pytest.mark.parametrize("name", ["create_campaign", "update_campaign"])
    def test_draft_writes_are_medium_risk(self, name: str) -> None:
        policy = get_tool_policy(name)
        assert policy.risk_level == ToolRiskLevel.MEDIUM
        assert policy.requires_approval is False

    def test_list_enrollments_is_low_risk(self) -> None:
        assert get_tool_policy("list_campaign_contacts").risk_level == ToolRiskLevel.LOW

    def test_campaign_and_enrollment_statuses_are_real_enums(self) -> None:
        schemas = {
            item["function"]["name"]: item["function"]["parameters"] for item in get_crm_tools()
        }

        assert schemas["create_campaign"]["properties"]["campaign_type"]["enum"] == [
            item.value for item in CampaignType
        ]
        assert schemas["list_campaign_contacts"]["properties"]["status"]["enum"] == [
            item.value for item in CampaignContactStatus
        ]


class TestListCampaigns:
    async def test_returns_message_schedule_and_real_contact_count(
        self,
        tools: CampaignAssistantTools,
        db: MagicMock,
        workspace_id: uuid.UUID,
    ) -> None:
        campaign = _campaign(workspace_id)
        campaign_rows = MagicMock()
        campaign_rows.scalars.return_value.all.return_value = [campaign]
        count_rows = MagicMock()
        count_rows.all.return_value = [(campaign.id, 214)]
        db.execute.side_effect = [campaign_rows, count_rows]
        db.scalar.return_value = 6

        result = await tools.list_campaigns({"status": "draft", "limit": 1})

        assert result["returned"] == 1
        assert result["total"] == 6
        assert result["has_more"] is True
        item = result["data"][0]
        assert item["initial_message"].startswith("Hi {first_name}")
        assert item["schedule"]["start"] == "2026-08-01T13:00:00+00:00"
        assert item["schedule"]["sending_hours_start"] == "09:00"
        # Deliberately differs from the stale denormalized `total_contacts=999`.
        assert item["contact_count"] == 214

    async def test_empty_page_does_not_issue_group_count_query(
        self, tools: CampaignAssistantTools, db: MagicMock
    ) -> None:
        campaign_rows = MagicMock()
        campaign_rows.scalars.return_value.all.return_value = []
        db.execute.return_value = campaign_rows
        db.scalar.return_value = 0

        result = await tools.list_campaigns({})

        assert result["data"] == []
        assert db.execute.await_count == 1


class TestCreateCampaign:
    async def test_creates_email_draft_without_sender(
        self, tools: CampaignAssistantTools, db: MagicMock
    ) -> None:
        result = await tools.create_campaign(
            {
                "name": "August newsletter",
                "campaign_type": "email",
                "initial_message": "Hello {first_name}",
                "email_subject": "August updates",
                "sending_hours_start": "09:00",
                "sending_hours_end": "17:30",
            }
        )

        assert result["success"] is True
        created = db.add.call_args.args[0]
        assert created.status == CampaignStatus.DRAFT
        assert created.from_phone_number is None
        assert created.sending_hours_start == time(9, 0)
        assert created.sending_hours_end == time(17, 30)
        db.flush.assert_awaited_once()
        assert "no contacts" in result["hint"]

    async def test_email_requires_subject(
        self, tools: CampaignAssistantTools, db: MagicMock
    ) -> None:
        result = await tools.create_campaign(
            {
                "name": "Newsletter",
                "campaign_type": "email",
                "initial_message": "Body",
            }
        )

        assert result["code"] == "invalid_argument"
        assert "email_subject" in result["message"]
        db.add.assert_not_called()

    async def test_sms_defaults_to_workspace_sender(
        self, tools: CampaignAssistantTools, db: MagicMock
    ) -> None:
        sender = MagicMock()
        sender.phone_number = "+14155550100"
        sender_result = MagicMock()
        sender_result.scalar_one_or_none.return_value = sender
        db.execute.return_value = sender_result

        result = await tools.create_campaign(
            {
                "name": "SMS draft",
                "campaign_type": "sms",
                "initial_message": "Hi {first_name}",
            }
        )

        assert result["success"] is True
        assert db.add.call_args.args[0].from_phone_number == "+14155550100"
        statement = db.execute.await_args.args[0].compile()
        assert tools.context.workspace_id in statement.params.values()

    async def test_sms_without_usable_sender_is_actionable(
        self, tools: CampaignAssistantTools, db: MagicMock
    ) -> None:
        sender_result = MagicMock()
        sender_result.scalar_one_or_none.return_value = None
        db.execute.return_value = sender_result

        result = await tools.create_campaign(
            {"name": "SMS draft", "campaign_type": "sms", "initial_message": "Hi"}
        )

        assert result["code"] == "unavailable"
        assert "Settings" in result["hint"]

    async def test_bad_sending_window_fails_loudly(
        self, tools: CampaignAssistantTools, db: MagicMock
    ) -> None:
        result = await tools.create_campaign(
            {
                "name": "Email",
                "campaign_type": "email",
                "initial_message": "Body",
                "email_subject": "Subject",
                "sending_hours_start": "banana",
            }
        )

        assert result["code"] == "invalid_argument"
        db.add.assert_not_called()


class TestUpdateCampaign:
    async def test_edits_initial_message_before_launch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: CampaignAssistantTools,
        db: MagicMock,
        workspace_id: uuid.UUID,
    ) -> None:
        campaign = _campaign(workspace_id)
        tools.get_campaign_for_workspace = AsyncMock(return_value=campaign)  # type: ignore[method-assign]
        monkeypatch.setattr(campaign_module, "count_campaign_contacts", AsyncMock(return_value=214))

        result = await tools.update_campaign(
            {
                "campaign_id": str(campaign.id),
                "initial_message": "New opener for {first_name}",
                "messages_per_minute": 15,
            }
        )

        assert result["success"] is True
        assert campaign.initial_message == "New opener for {first_name}"
        assert campaign.messages_per_minute == 15
        assert result["data"]["contact_count"] == 214
        db.flush.assert_awaited_once()

    @pytest.mark.parametrize("status", [CampaignStatus.RUNNING, CampaignStatus.COMPLETED])
    async def test_running_or_completed_campaign_is_immutable(
        self,
        status: CampaignStatus,
        tools: CampaignAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        tools.get_campaign_for_workspace = AsyncMock(  # type: ignore[method-assign]
            return_value=_campaign(workspace_id, status=status)
        )

        result = await tools.update_campaign(
            {"campaign_id": str(uuid.uuid4()), "initial_message": "Changed"}
        )

        assert result["code"] == "conflict"
        assert "Pause" in result["hint"] or "immutable" in result["hint"]

    async def test_requires_at_least_one_field(
        self, tools: CampaignAssistantTools, workspace_id: uuid.UUID
    ) -> None:
        campaign = _campaign(workspace_id)
        tools.get_campaign_for_workspace = AsyncMock(return_value=campaign)  # type: ignore[method-assign]

        result = await tools.update_campaign({"campaign_id": str(campaign.id)})

        assert result["code"] == "invalid_argument"


class TestListCampaignContacts:
    async def test_returns_people_not_just_join_ids(
        self,
        tools: CampaignAssistantTools,
        db: MagicMock,
        workspace_id: uuid.UUID,
    ) -> None:
        campaign = _campaign(workspace_id)
        tools.get_campaign_for_workspace = AsyncMock(return_value=campaign)  # type: ignore[method-assign]
        contact = _contact(workspace_id)
        enrollment = CampaignContact(
            id=uuid.uuid4(),
            campaign_id=campaign.id,
            contact_id=contact.id,
            status=CampaignContactStatus.REPLIED,
            messages_sent=2,
            messages_received=1,
            follow_ups_sent=1,
            is_qualified=True,
            opted_out=False,
            first_sent_at=datetime(2026, 7, 20, tzinfo=UTC),
            last_reply_at=datetime(2026, 7, 21, tzinfo=UTC),
            last_error=None,
            created_at=datetime(2026, 7, 19, tzinfo=UTC),
        )
        rows = MagicMock()
        rows.all.return_value = [(enrollment, contact)]
        db.scalar.return_value = 87
        db.execute.return_value = rows

        result = await tools.list_campaign_contacts(
            {"campaign_id": str(campaign.id), "status": "replied", "limit": 10}
        )

        assert result["returned"] == 1
        assert result["total"] == 87
        assert result["has_more"] is True
        item = result["data"][0]
        assert item["contact_id"] == 512
        assert item["first_name"] == "Maria"
        assert item["email"] == "maria@example.com"
        assert item["status"] == "replied"
        assert item["last_reply_at"].startswith("2026-07-21")

    async def test_campaign_lookup_is_workspace_scoped(
        self,
        tools: CampaignAssistantTools,
    ) -> None:
        lookup = AsyncMock(return_value=None)
        tools.get_campaign_for_workspace = lookup  # type: ignore[method-assign]
        campaign_id = uuid.uuid4()

        result = await tools.list_campaign_contacts({"campaign_id": str(campaign_id)})

        assert result["code"] == "not_found"
        lookup.assert_awaited_once_with(campaign_id)
