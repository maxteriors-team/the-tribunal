"""CRM assistant calendar tool schemas, safety gates, scope, and CRUD behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.appointment import Appointment, AppointmentStatus
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tool_metadata import get_approved_action_executor
from app.services.ai.crm_assistant._tools import get_crm_tools


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    session.scalar = AsyncMock(return_value=0)
    return session


def _appointment(workspace_id: uuid.UUID, **overrides: Any) -> Appointment:
    values: dict[str, Any] = {
        "id": 301,
        "workspace_id": workspace_id,
        "contact_id": 101,
        "scheduled_at": datetime(2026, 9, 1, 14, 0, tzinfo=UTC),
        "duration_minutes": 60,
        "service_type": "Estimate",
        "status": AppointmentStatus.SCHEDULED,
        "notes": "Bring ladder",
        "meeting_url": None,
        "google_calendar_event_url": None,
        "sync_status": "pending",
    }
    values.update(overrides)
    return Appointment(**values)


def test_appointment_tool_schemas_and_approval_bindings() -> None:
    tools = {tool["function"]["name"]: tool["function"] for tool in get_crm_tools()}

    assert {
        "list_appointments",
        "get_appointment",
        "create_appointment",
        "update_appointment",
        "delete_appointment",
    }.issubset(tools)
    assert tools["create_appointment"]["parameters"]["required"] == [
        "contact_id",
        "scheduled_at",
    ]
    assert "scheduled_at" in tools["update_appointment"]["parameters"]["properties"]
    for name in ("create_appointment", "update_appointment", "delete_appointment"):
        assert "confirmed" not in tools[name]["parameters"]["properties"]
        assert get_approved_action_executor(f"crm_assistant.{name}") is not None


async def test_create_appointment_is_approval_gated(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")
    payload = {
        "contact_id": 101,
        "scheduled_at": "2026-09-01T14:00:00+00:00",
        "duration_minutes": 60,
    }

    result = await executor.execute("create_appointment", payload)

    assert result["code"] == "pending_approval"
    assert result["pending_approval"] is True
    pending = db.add.call_args.args[0]
    assert pending.workspace_id == workspace_id
    assert pending.action_type == "crm_assistant.create_appointment"
    assert pending.action_payload == payload


async def test_approved_create_appointment_executes_crud_handler(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    appointment = _appointment(workspace_id)
    create = AsyncMock(return_value=appointment)
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    with patch(
        "app.services.ai.crm_assistant._appointment_tools.AppointmentService.create_appointment",
        create,
    ):
        result = await executor.execute(
            "create_appointment",
            {
                "contact_id": 101,
                "scheduled_at": "2026-09-01T14:00:00+00:00",
                "duration_minutes": 60,
                "service_type": "Estimate",
            },
            approval_granted=True,
        )

    assert result["success"] is True
    assert result["data"]["id"] == 301
    assert create.await_args.args[0] == workspace_id
    appointment_in = create.await_args.args[1]
    assert appointment_in.contact_id == 101
    assert appointment_in.scheduled_at == datetime(2026, 9, 1, 14, 0, tzinfo=UTC)


async def test_get_appointment_is_workspace_scoped(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    db.execute.return_value = _ExecuteResult([_appointment(workspace_id)])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    result = await executor.execute("get_appointment", {"appointment_id": 301})

    assert result["success"] is True
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert "appointments.workspace_id" in compiled
    assert workspace_id.hex in compiled
    assert "appointments.id = 301" in compiled


async def test_approved_update_reschedules_appointment(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    updated = _appointment(workspace_id, scheduled_at=datetime(2026, 9, 2, 16, 30, tzinfo=UTC))
    update = AsyncMock(return_value=updated)
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    with patch(
        "app.services.ai.crm_assistant._appointment_tools.AppointmentService.update_appointment",
        update,
    ):
        result = await executor.execute(
            "update_appointment",
            {"appointment_id": 301, "scheduled_at": "2026-09-02T16:30:00+00:00"},
            approval_granted=True,
        )

    assert result["success"] is True
    assert result["data"]["scheduled_at"] == "2026-09-02T16:30:00+00:00"
    appointment_in = update.await_args.args[2]
    assert appointment_in.scheduled_at == datetime(2026, 9, 2, 16, 30, tzinfo=UTC)


async def test_approved_delete_checks_scope_then_deletes(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    db.execute.return_value = _ExecuteResult([_appointment(workspace_id)])
    delete = AsyncMock(return_value=None)
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7, role="owner")

    with patch(
        "app.services.ai.crm_assistant._appointment_tools.AppointmentService.delete_appointment",
        delete,
    ):
        result = await executor.execute(
            "delete_appointment",
            {"appointment_id": 301},
            approval_granted=True,
        )

    assert result == {"success": True, "data": {"id": 301, "deleted": True}}
    compiled = str(db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert workspace_id.hex in compiled
    delete.assert_awaited_once_with(workspace_id, 301)
