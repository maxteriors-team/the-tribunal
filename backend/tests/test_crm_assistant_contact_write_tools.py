"""Coverage for CRM assistant contact reads, edits, notes, tags, and filters."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.contact import Contact
from app.services.ai.crm_assistant import _contact_tools as contact_module
from app.services.ai.crm_assistant._contact_tools import ContactAssistantTools
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
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def tools(db: MagicMock, workspace_id: uuid.UUID) -> ContactAssistantTools:
    return ContactAssistantTools(CRMToolContext(db=db, workspace_id=workspace_id, user_id=7, role="owner"))


def _contact(workspace_id: uuid.UUID, **overrides: Any) -> Contact:
    values: dict[str, Any] = {
        "id": 512,
        "workspace_id": workspace_id,
        "first_name": "Bob",
        "last_name": "Marchetti",
        "phone_number": "+15554829910",
        "phone_hash": "phone-hash",
        "email": "bob@example.com",
        "email_hash": "email-hash",
        "company_name": "Ridgeline Property Group",
        "address_line1": "1 Main St",
        "address_line2": None,
        "address_city": "Albany",
        "address_state": "NY",
        "address_zip": "12207",
        "status": "qualified",
        "lead_score": 76,
        "engagement_score": 60,
        "is_qualified": True,
        "qualification_signals": {"interest_level": "high"},
        "notes": "Original note",
        "important_dates": {"birthday": "1980-01-02"},
        "source": "referral",
        "last_appointment_status": "completed",
        "last_engaged_at": datetime(2026, 7, 20, tzinfo=UTC),
        "created_at": datetime(2026, 1, 2, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 20, tzinfo=UTC),
    }
    values.update(overrides)
    contact = Contact(**values)
    contact.__dict__["contact_tags"] = []
    return contact


class TestRegistration:
    @pytest.mark.parametrize(
        "name",
        [
            "get_contact",
            "update_contact",
            "add_contact_note",
            "add_contact_tags",
            "find_contacts",
        ],
    )
    def test_tool_schema_and_handler_are_registered(
        self, name: str, tools: ContactAssistantTools
    ) -> None:
        schemas = {tool["function"]["name"] for tool in get_crm_tools()}

        assert name in schemas
        assert name in tools.handlers()

    @pytest.mark.parametrize("name", ["get_contact", "find_contacts"])
    def test_read_tools_are_low_risk(self, name: str) -> None:
        assert get_tool_policy(name).risk_level == ToolRiskLevel.LOW

    @pytest.mark.parametrize("name", ["update_contact", "add_contact_note", "add_contact_tags"])
    def test_write_tools_are_medium_risk_without_model_bypass(self, name: str) -> None:
        policy = get_tool_policy(name)
        assert policy.risk_level == ToolRiskLevel.MEDIUM
        assert policy.requires_approval is False

    def test_update_schema_cannot_replace_notes_or_tags(self) -> None:
        schema = next(
            tool["function"]
            for tool in get_crm_tools()
            if tool["function"]["name"] == "update_contact"
        )
        properties = schema["parameters"]["properties"]

        assert "notes" not in properties
        assert "tags" not in properties
        assert properties["status"]["enum"] == [
            "new",
            "contacted",
            "qualified",
            "converted",
            "lost",
        ]


class TestGetContact:
    async def test_returns_full_record_including_notes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        contact = _contact(workspace_id)
        lookup = AsyncMock(return_value=contact)
        monkeypatch.setattr(contact_module, "get_contact_by_id", lookup)

        result = await tools.get_contact({"contact_id": 512})

        assert result["success"] is True
        data = result["data"]
        assert data["id"] == 512
        assert data["notes"] == "Original note"
        assert data["phone"] == "+15554829910"
        assert data["address"]["city"] == "Albany"
        lookup.assert_awaited_once_with(512, workspace_id, tools.context.db)

    async def test_missing_contact_is_structured_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tools: ContactAssistantTools
    ) -> None:
        monkeypatch.setattr(contact_module, "get_contact_by_id", AsyncMock(return_value=None))

        result = await tools.get_contact({"contact_id": 999})

        assert result["code"] == "not_found"
        assert "search_contacts" in result["hint"]

    async def test_timeline_is_opt_in_and_bounded(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        monkeypatch.setattr(
            contact_module, "get_contact_by_id", AsyncMock(return_value=_contact(workspace_id))
        )
        timeline = AsyncMock(
            return_value=[
                {
                    "id": uuid.uuid4(),
                    "timestamp": datetime(2026, 7, 20, tzinfo=UTC),
                    "type": "sms",
                    "content": "Hi Bob",
                }
            ]
        )
        monkeypatch.setattr(contact_module, "get_contact_timeline", timeline)

        result = await tools.get_contact(
            {"contact_id": 512, "include_timeline": True, "timeline_limit": 500}
        )

        assert result["data"]["recent_timeline"][0]["timestamp"].startswith("2026-07-20")
        assert isinstance(result["data"]["recent_timeline"][0]["id"], str)
        timeline.assert_awaited_once_with(512, workspace_id, tools.context.db, limit=50)


class TestUpdateContact:
    async def test_updates_in_place_through_existing_repository(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        contact = _contact(workspace_id)
        monkeypatch.setattr(contact_module, "get_contact_by_id", AsyncMock(return_value=contact))

        async def update(existing: Contact, _db: Any, updates: dict[str, Any]) -> Contact:
            assert existing is contact
            for field, value in updates.items():
                setattr(existing, field, value)
            return existing

        repository = AsyncMock(side_effect=update)
        monkeypatch.setattr(contact_module, "repository_update_contact", repository)

        result = await tools.update_contact(
            {
                "contact_id": 512,
                "email": "new@example.com",
                "company_name": "New Company",
                "status": "converted",
            }
        )

        assert result["success"] is True
        assert result["data"]["email"] == "new@example.com"
        updates = repository.await_args.args[2]
        assert updates == {
            "email": "new@example.com",
            "company_name": "New Company",
            "status": "converted",
        }

    async def test_rejects_empty_update(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        monkeypatch.setattr(
            contact_module, "get_contact_by_id", AsyncMock(return_value=_contact(workspace_id))
        )

        result = await tools.update_contact({"contact_id": 512})

        assert result["code"] == "invalid_argument"
        assert "No contact fields" in result["message"]

    async def test_normalizes_phone_and_blocks_duplicate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        db: MagicMock,
        workspace_id: uuid.UUID,
    ) -> None:
        monkeypatch.setattr(
            contact_module, "get_contact_by_id", AsyncMock(return_value=_contact(workspace_id))
        )
        duplicate = _contact(workspace_id, id=987)
        duplicate_result = MagicMock()
        duplicate_result.scalar_one_or_none.return_value = duplicate
        db.execute.return_value = duplicate_result
        repository = AsyncMock()
        monkeypatch.setattr(contact_module, "repository_update_contact", repository)

        result = await tools.update_contact({"contact_id": 512, "phone_number": "(415) 555-2671"})

        assert result["code"] == "conflict"
        assert result["data"]["id"] == 987
        repository.assert_not_awaited()

    async def test_rejects_invalid_email(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        monkeypatch.setattr(
            contact_module, "get_contact_by_id", AsyncMock(return_value=_contact(workspace_id))
        )

        result = await tools.update_contact({"contact_id": 512, "email": "not-an-email"})

        assert result["code"] == "invalid_argument"
        assert "validation" in result["message"].lower()


class TestAddNote:
    async def test_appends_without_overwriting_existing_note(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        workspace_id: uuid.UUID,
    ) -> None:
        contact = _contact(workspace_id, notes="Keep me")
        monkeypatch.setattr(contact_module, "get_contact_by_id", AsyncMock(return_value=contact))

        async def update(existing: Contact, _db: Any, updates: dict[str, Any]) -> Contact:
            existing.notes = updates["notes"]
            return existing

        repository = AsyncMock(side_effect=update)
        monkeypatch.setattr(contact_module, "repository_update_contact", repository)

        result = await tools.add_contact_note(
            {"contact_id": 512, "note": "Wants a spring gutter quote"}
        )

        notes = result["data"]["notes"]
        assert notes.startswith("Keep me\n\n[")
        assert notes.endswith("Wants a spring gutter quote")
        assert result["data"]["note_added"] == "Wants a spring gutter quote"

    async def test_blank_note_is_rejected_before_write(
        self, monkeypatch: pytest.MonkeyPatch, tools: ContactAssistantTools
    ) -> None:
        lookup = AsyncMock()
        monkeypatch.setattr(contact_module, "get_contact_by_id", lookup)

        result = await tools.add_contact_note({"contact_id": 512, "note": "   "})

        assert result["code"] == "invalid_argument"
        lookup.assert_not_awaited()


class TestAddTags:
    async def test_adds_tags_idempotently_and_commits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tools: ContactAssistantTools,
        db: MagicMock,
        workspace_id: uuid.UUID,
    ) -> None:
        monkeypatch.setattr(
            contact_module, "get_contact_by_id", AsyncMock(return_value=_contact(workspace_id))
        )
        added = [MagicMock(name="hot-lead"), MagicMock(name="vip")]
        added[0].name = "hot-lead"
        added[1].name = "vip"
        service = MagicMock()
        service.add_tags_to_contact = AsyncMock(return_value=added)
        monkeypatch.setattr(contact_module, "TagService", MagicMock(return_value=service))
        result_rows = MagicMock()
        result_rows.scalars.return_value.all.return_value = ["hot-lead", "past-customer", "vip"]
        db.execute.return_value = result_rows

        result = await tools.add_contact_tags({"contact_id": 512, "tags": ["hot-lead", "vip"]})

        assert result["success"] is True
        assert result["data"]["added_tags"] == ["hot-lead", "vip"]
        assert result["data"]["tags"] == ["hot-lead", "past-customer", "vip"]
        service.add_tags_to_contact.assert_awaited_once_with(
            workspace_id=workspace_id,
            contact_id=512,
            names=["hot-lead", "vip"],
        )
        db.commit.assert_awaited_once()


class TestFindContacts:
    async def test_reports_true_total_for_structured_filters(
        self,
        tools: ContactAssistantTools,
        db: MagicMock,
        workspace_id: uuid.UUID,
    ) -> None:
        contact = _contact(workspace_id)
        rows = MagicMock()
        rows.scalars.return_value.unique.return_value.all.return_value = [contact]
        db.execute.return_value = rows
        db.scalar.return_value = 300

        result = await tools.find_contacts(
            {
                "filters": {
                    "status": "qualified",
                    "not_contacted_days": 30,
                    "include_never_contacted": True,
                },
                "limit": 10,
            }
        )

        assert result["returned"] == 1
        assert result["total"] == 300
        assert result["has_more"] is True
        statement = db.execute.await_args.args[0]
        compiled = statement.compile()
        assert workspace_id in compiled.params.values()
        assert "qualified" in compiled.params.values()

    async def test_unknown_tag_yields_empty_result_not_all_contacts(
        self, tools: ContactAssistantTools, db: MagicMock
    ) -> None:
        tag_rows = MagicMock()
        tag_rows.all.return_value = []
        db.execute.return_value = tag_rows

        result = await tools.find_contacts(
            {"filters": {"tags": ["does-not-exist"], "tags_match": "any"}}
        )

        assert result["total"] == 0
        assert result["data"] == []
        assert result["unresolved_tags"] == ["does-not-exist"]
        db.scalar.assert_not_awaited()

    async def test_invalid_date_returns_actionable_error(
        self, tools: ContactAssistantTools
    ) -> None:
        result = await tools.find_contacts({"filters": {"created_after": "last banana"}})

        assert result["code"] == "invalid_argument"
        assert "ISO" in result["hint"]
