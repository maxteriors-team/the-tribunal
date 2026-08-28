"""Tests for CRM assistant automation (workflow) tools."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.automation import Automation
from app.models.pending_action import PendingAction
from app.schemas.automation import AUTOMATION_TRIGGER_TYPES
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import get_approved_action_executor
from app.services.ai.crm_assistant._tools import get_crm_tools
from app.services.approval.approval_gate_service import ApprovalGateService


def _make_automation(**overrides: Any) -> Automation:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Thank reviewers",
        "description": "Text a thank-you when a review comes in",
        "trigger_type": "review_received",
        "trigger_config": {},
        "actions": [{"type": "send_sms", "config": {"message": "Thanks {first_name}!"}}],
        "is_active": True,
        "last_triggered_at": None,
        "last_evaluated_at": None,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 2, tzinfo=UTC),
    }
    defaults.update(overrides)
    return Automation(**defaults)


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
    session.delete = AsyncMock()
    # List tools issue a COUNT(*) through scalar() for the truthful `total`.
    session.scalar = AsyncMock(return_value=1)
    return session


def test_automation_tools_are_registered() -> None:
    names = {tool["function"]["name"] for tool in get_crm_tools()}

    assert {
        "list_automations",
        "get_automation",
        "create_automation",
        "update_automation",
        "enable_automation",
        "disable_automation",
        "delete_automation",
    }.issubset(names)


def test_automation_tool_confirmation_and_executor_bindings() -> None:
    tools_by_name = {tool["function"]["name"]: tool for tool in get_crm_tools()}

    # Gated tools bind an approved-action executor, and none of them expose a
    # model-settable approval flag: approval lives in the executor alone.
    for tool_name in (
        "create_automation",
        "update_automation",
        "enable_automation",
        "delete_automation",
    ):
        properties = tools_by_name[tool_name]["function"]["parameters"]["properties"]
        assert "confirmed" not in properties
        assert get_approved_action_executor(f"crm_assistant.{tool_name}") is not None

    for tool_name in ("list_automations", "get_automation", "disable_automation"):
        properties = tools_by_name[tool_name]["function"]["parameters"]["properties"]
        assert "confirmed" not in properties
        assert get_approved_action_executor(f"crm_assistant.{tool_name}") is None


def test_create_automation_trigger_enum_matches_schema() -> None:
    tools_by_name = {tool["function"]["name"]: tool for tool in get_crm_tools()}
    trigger_property = tools_by_name["create_automation"]["function"]["parameters"]["properties"][
        "trigger_type"
    ]

    assert trigger_property["enum"] == list(AUTOMATION_TRIGGER_TYPES)


async def test_list_automations_returns_summaries(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute("list_automations", {"active_only": True})

    assert result["success"] is True
    assert result["returned"] == 1
    assert result["total"] == 1
    assert result["has_more"] is False
    assert result["data"] == [
        {
            "id": str(automation.id),
            "name": "Thank reviewers",
            "description": "Text a thank-you when a review comes in",
            "trigger_type": "review_received",
            "trigger_config": {},
            "actions": [{"type": "send_sms", "config": {"message": "Thanks {first_name}!"}}],
            "is_active": True,
            "last_triggered_at": None,
            "last_evaluated_at": None,
            "created_at": "2026-06-01T00:00:00+00:00",
            "updated_at": "2026-06-02T00:00:00+00:00",
        }
    ]
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_create_automation_queues_pending_approval_when_not_confirmed(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")
    payload = {
        "name": "Missed call textback",
        "trigger_type": "missed_call",
        "actions": [{"type": "send_sms", "config": {"message": "Sorry we missed you!"}}],
    }

    result = await executor.execute("create_automation", payload)

    assert result == {
        "success": False,
        "code": "pending_approval",
        "pending_approval": True,
        "pending_action_id": str(db.add.call_args.args[0].id),
        "message": "Approval required before I can create this automation.",
        "retryable": False,
        "hint": (
            "Tell the operator it is waiting for their approval in this chat. "
            "Do not call the tool again."
        ),
    }
    pending_action = db.add.call_args.args[0]
    assert pending_action.action_type == "crm_assistant.create_automation"
    assert pending_action.action_payload == payload
    assert pending_action.description == "Create automation Missed call textback"


async def test_approved_create_automation_pending_action_creates_row(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    action = PendingAction(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        agent_id=None,
        action_type="crm_assistant.create_automation",
        action_payload={
            "name": "Missed call textback",
            "trigger_type": "missed_call",
            "actions": [{"type": "send_sms", "config": {"message": "Sorry we missed you!"}}],
        },
        description="Create automation Missed call textback",
        context={"source": "crm_assistant", "user_id": 7, "role": "owner"},
        status="approved",
    )
    service = ApprovalGateService()

    result = await service.execute_approved_action(db, action)

    assert result["success"] is True
    assert result["tool"] == "create_automation"
    created = db.add.call_args.args[0]
    assert isinstance(created, Automation)
    assert created.workspace_id == workspace_id
    assert created.name == "Missed call textback"
    assert created.trigger_type == "missed_call"
    assert created.actions == [{"type": "send_sms", "config": {"message": "Sorry we missed you!"}}]


async def test_create_automation_rejects_invalid_trigger(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "create_automation",
        {
            "name": "Bad trigger",
            "trigger_type": "not_a_trigger",
            "actions": [{"type": "send_sms", "config": {"message": "hi"}}],
        },
        approval_granted=True,
    )

    assert result["success"] is False
    assert result["code"] == "invalid_argument"
    assert "trigger_type" in result["detail"]
    db.add.assert_not_called()


async def test_create_automation_requires_actions(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "create_automation",
        {"name": "No-op", "trigger_type": "review_received", "actions": []},
        approval_granted=True,
    )

    assert result["success"] is False
    assert result["code"] == "invalid_argument"
    assert result["message"] == "An automation needs at least one action."
    db.add.assert_not_called()


async def test_enable_automation_not_found(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    db.execute.return_value = _ExecuteResult([])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "enable_automation",
        {"automation_id": str(uuid.uuid4())},
        approval_granted=True,
    )

    assert result["success"] is False
    assert result["code"] == "not_found"
    assert result["hint"] == "Call list_automations to get a valid id."
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_enable_automation_rejects_invalid_id(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "enable_automation",
        {"automation_id": "not-a-uuid"},
        approval_granted=True,
    )

    assert result["success"] is False
    assert result["code"] == "invalid_argument"
    assert "automation_id" in result["message"]
    db.execute.assert_not_called()


async def test_enable_automation_activates_when_confirmed(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id, is_active=False)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "enable_automation",
        {"automation_id": str(automation.id)},
        approval_granted=True,
    )

    assert result["success"] is True
    assert automation.is_active is True


async def test_disable_automation_sets_inactive_without_confirmation(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id, is_active=True)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "disable_automation",
        {"automation_id": str(automation.id)},
    )

    assert result["success"] is True
    assert automation.is_active is False


def test_automation_trigger_and_action_configs_are_typed() -> None:
    tools_by_name = {tool["function"]["name"]: tool["function"] for tool in get_crm_tools()}
    create_properties = tools_by_name["create_automation"]["parameters"]["properties"]

    trigger_variants = create_properties["trigger_config"]["anyOf"]
    tagged = next(
        variant
        for variant in trigger_variants
        if variant["description"].startswith("contact_tagged")
    )
    assert tagged["required"] == ["tag"]
    assert tagged["properties"]["tag"]["minLength"] == 1
    assert tagged["additionalProperties"] is False

    action_variants = create_properties["actions"]["items"]["anyOf"]
    wait_action = next(
        variant for variant in action_variants if "wait" in variant["properties"]["type"]["enum"]
    )
    assert wait_action["properties"]["config"]["properties"]["hours"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 8760,
    }
    assert wait_action["properties"]["config"]["additionalProperties"] is False


async def test_get_automation_returns_full_workspace_scoped_configuration(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute("get_automation", {"automation_id": str(automation.id)})

    assert result["success"] is True
    assert result["data"]["actions"] == automation.actions
    assert result["data"]["updated_at"] == "2026-06-02T00:00:00+00:00"
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "workspace_id" in compiled
    assert workspace_id.hex in compiled


async def test_update_automation_replaces_wait_with_complete_action_list(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id, is_active=False)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")
    actions = [
        {"type": "send_sms", "config": {"message": "Thanks {first_name}!"}},
        {"type": "wait", "config": {"hours": 24}},
    ]

    result = await executor.execute(
        "update_automation",
        {"automation_id": str(automation.id), "name": "24-hour follow-up", "actions": actions},
        approval_granted=True,
    )

    assert result["success"] is True
    assert automation.name == "24-hour follow-up"
    assert automation.actions == actions
    db.flush.assert_awaited_once()


async def test_update_automation_rejects_empty_actions(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "update_automation",
        {"automation_id": str(automation.id), "actions": []},
        approval_granted=True,
    )

    assert result["code"] == "invalid_argument"
    assert "at least one action" in result["message"]
    db.flush.assert_not_awaited()


async def test_update_automation_without_changes_is_actionable(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "update_automation",
        {"automation_id": str(automation.id)},
        approval_granted=True,
    )

    assert result["code"] == "invalid_argument"
    assert result["hint"] == "Provide at least one field to update."


async def test_delete_automation_removes_workspace_scoped_row_after_approval(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    automation = _make_automation(workspace_id=workspace_id)
    db.execute.return_value = _ExecuteResult([automation])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute(
        "delete_automation",
        {"automation_id": str(automation.id)},
        approval_granted=True,
    )

    assert result == {
        "success": True,
        "data": {"id": str(automation.id), "name": automation.name, "deleted": True},
    }
    db.delete.assert_awaited_once_with(automation)
    db.flush.assert_awaited_once()
