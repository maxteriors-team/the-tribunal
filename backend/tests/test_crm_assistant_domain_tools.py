"""Representative CRM assistant domain tool coverage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.opportunity import Opportunity
from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor
from app.services.ai.crm_assistant._tools import get_crm_tools


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None


class _ExecuteResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return _ScalarResult(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


@pytest.fixture
def workspace_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def db() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.scalar = AsyncMock()
    return session


def _make_contact(workspace_id: uuid.UUID, **overrides: Any) -> Contact:
    defaults: dict[str, Any] = {
        "id": 101,
        "workspace_id": workspace_id,
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


def _make_agent(workspace_id: uuid.UUID, **overrides: Any) -> Agent:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": workspace_id,
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


def test_executor_registers_every_declared_crm_tool(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)
    declared_tools = {tool["function"]["name"] for tool in get_crm_tools()}

    assert declared_tools.issubset(executor.handlers.keys())


async def test_search_contacts_returns_contact_summaries(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    contact = _make_contact(workspace_id)
    db.execute.return_value = _ExecuteResult([contact])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("search_contacts", {"query": "Ava", "limit": 5})

    assert result == {
        "success": True,
        "data": [
            {
                "id": 101,
                "first_name": "Ava",
                "last_name": "Rivera",
                "phone": "+1555000101",
                "email": "ava@example.com",
                "status": "new",
                "company": "Rivera Co",
            }
        ],
        "count": 1,
    }


async def test_create_contact_creates_workspace_contact(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    db.execute.return_value = _ExecuteResult([])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "create_contact",
        {
            "first_name": "Mia",
            "last_name": "Chen",
            "phone": "+1555000202",
            "email": "mia@example.com",
            "notes": "Asked for pricing.",
        },
    )

    assert result["success"] is True
    created_contact = db.add.call_args.args[0]
    assert isinstance(created_contact, Contact)
    assert created_contact.workspace_id == workspace_id
    assert created_contact.first_name == "Mia"
    assert created_contact.last_name == "Chen"
    assert created_contact.phone_number == "+1555000202"
    assert created_contact.email == "mia@example.com"
    assert created_contact.notes == "Asked for pricing."
    db.flush.assert_awaited_once()


async def test_list_appointments_returns_upcoming_summaries(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    scheduled_at = datetime.now(UTC) + timedelta(days=1)
    appointment = Appointment(
        id=301,
        workspace_id=workspace_id,
        contact_id=101,
        scheduled_at=scheduled_at,
        duration_minutes=45,
        status=AppointmentStatus.SCHEDULED,
        notes="Discovery call",
    )
    db.execute.return_value = _ExecuteResult([appointment])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("list_appointments", {"limit": 3})

    assert result == {
        "success": True,
        "data": [
            {
                "id": 301,
                "contact_id": 101,
                "scheduled_at": scheduled_at.isoformat(),
                "duration_minutes": 45,
                "status": AppointmentStatus.SCHEDULED,
                "notes": "Discovery call",
            }
        ],
        "count": 1,
    }


async def test_list_opportunities_returns_pipeline_summaries(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    opportunity = Opportunity(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
        primary_contact_id=101,
        name="Spring HVAC replacement",
        status="open",
        amount=Decimal("12500.50"),
        probability=65,
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
        updated_at=datetime(2026, 5, 2, tzinfo=UTC),
    )
    db.execute.return_value = _ExecuteResult([opportunity])
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute("list_opportunities", {"limit": 10})

    assert result == {
        "success": True,
        "data": [
            {
                "id": str(opportunity.id),
                "name": "Spring HVAC replacement",
                "status": "open",
                "amount": 12500.5,
                "probability": 65,
            }
        ],
        "count": 1,
    }


async def test_confirmed_assign_ai_responder_updates_conversation(
    db: MagicMock,
    workspace_id: uuid.UUID,
) -> None:
    agent = _make_agent(workspace_id)
    conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=101,
        workspace_phone="+15550009999",
        contact_phone="+1555000101",
        ai_enabled=False,
        ai_paused=True,
        ai_paused_until=datetime(2026, 5, 3, tzinfo=UTC),
    )
    db.execute.side_effect = [_ExecuteResult([conversation]), _ExecuteResult([agent])]
    executor = CRMToolExecutor(db=db, workspace_id=workspace_id, user_id=7)

    result = await executor.execute(
        "assign_ai_responder",
        {"conversation_id": str(conversation.id), "agent_id": str(agent.id), "confirmed": True},
    )

    assert result == {
        "success": True,
        "message": "Assigned Front Desk as AI responder",
        "data": {"conversation_id": str(conversation.id), "agent_id": str(agent.id)},
    }
    assert conversation.assigned_agent_id == agent.id
    assert conversation.ai_enabled is True
    assert conversation.ai_paused is False
    assert conversation.ai_paused_until is None
    db.flush.assert_awaited_once()
