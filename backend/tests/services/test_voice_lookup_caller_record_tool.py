"""Tests for the read-only ``lookup_caller_record`` voice tool.

The tool lets a receptionist agent answer account-specific questions about the
*current caller* ("when's my appointment?", "what's my status?") by reading only
that caller's own CRM record. These tests pin the two security invariants:

- Every record query is hard-scoped to BOTH the call's ``workspace_id`` and the
  resolved ``contact_id`` — so it can never read another tenant's or another
  person's data.
- Unknown callers (no resolvable contact, or a contact that does not belong to
  the call's workspace) get a safe "no record found" response instead of any
  data or an error.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

import app.db.session as db_session_module
from app.models.agent import Agent
from app.models.appointment import Appointment, AppointmentStatus
from app.models.contact import Contact
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.opportunity import Opportunity
from app.services.ai.tool_executor import VoiceToolExecutor
from app.services.ai.voice_tools import (
    get_tools_from_agent_config,
    is_lookup_caller_record_enabled,
)

CALL_CONTROL_ID = "caller-ccid-lookup-1"


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _IsolatingSession:
    """Async session stub that *enforces* workspace + contact scoping.

    It reads the bound parameter values out of each compiled statement and only
    returns seeded rows whose ``workspace_id``/``contact_id`` actually appear in
    that statement's filters. This makes the stub behave like a real database
    with row-level scoping: a row that belongs to another workspace is dropped
    exactly because the query never binds that workspace's id.
    """

    def __init__(
        self,
        *,
        message: Message | None,
        contacts: list[Contact],
        appointments: list[Appointment],
        opportunities: list[Opportunity],
    ) -> None:
        self.message = message
        self.contacts = contacts
        self.appointments = appointments
        self.opportunities = opportunities
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, *_a: Any, **_k: Any) -> _Result:
        self.statements.append(stmt)
        entity = stmt.column_descriptions[0]["entity"]
        values = set(stmt.compile().params.values())
        name = entity.__name__

        if name == "Message":
            return _Result([self.message] if self.message is not None else [])
        if name == "Contact":
            return _Result(
                [c for c in self.contacts if c.id in values and c.workspace_id in values]
            )
        if name == "Appointment":
            return _Result(
                [
                    a
                    for a in self.appointments
                    if a.workspace_id in values and a.contact_id in values
                ]
            )
        if name == "Opportunity":
            return _Result(
                [
                    o
                    for o in self.opportunities
                    if o.workspace_id in values and o.primary_contact_id in values
                ]
            )
        return _Result([])

    async def __aenter__(self) -> _IsolatingSession:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _make_agent(**overrides: Any) -> Agent:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Front Desk",
        "description": "Reads the caller's own record",
        "channel_mode": "voice",
        "voice_provider": "openai",
        "voice_id": "cedar",
        "language": "en-US",
        "system_prompt": "Be concise.",
        "temperature": 0.7,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "calcom_event_type_id": None,
        "enabled_tools": ["lookup_caller_record"],
        "tool_settings": {},
        "is_active": True,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return Agent(**values)


def _make_conversation(workspace_id: uuid.UUID, contact_id: int | None) -> Conversation:
    return Conversation(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=contact_id,
        workspace_phone="+15550001111",
        contact_phone="+15550002222",
        channel="voice",
        ai_enabled=True,
        last_message_at=datetime(2026, 5, 28, 15, 0, tzinfo=UTC),
        last_message_direction="inbound",
        last_message_preview="Asked about pricing",
    )


def _make_call_message(agent: Agent, conversation: Conversation) -> Message:
    return Message(
        id=uuid.uuid4(),
        conversation=conversation,
        conversation_id=conversation.id,
        direction="inbound",
        channel="voice",
        body="",
        status=MessageStatus.ANSWERED,
        provider_message_id=CALL_CONTROL_ID,
        agent_id=agent.id,
        campaign_id=None,
        is_ai=True,
    )


def _make_contact(workspace_id: uuid.UUID, contact_id: int, **overrides: Any) -> Contact:
    values: dict[str, Any] = {
        "id": contact_id,
        "workspace_id": workspace_id,
        "first_name": "Dana",
        "last_name": "Vargas",
        "phone_number": "+15550002222",
        "status": "qualified",
        "is_qualified": True,
        "notes": "Prefers afternoon calls.",
    }
    values.update(overrides)
    return Contact(**values)


def _make_appointment(
    workspace_id: uuid.UUID, contact_id: int, scheduled_at: datetime
) -> Appointment:
    return Appointment(
        id=1,
        workspace_id=workspace_id,
        contact_id=contact_id,
        scheduled_at=scheduled_at,
        duration_minutes=30,
        status=AppointmentStatus.SCHEDULED,
        service_type="Consultation",
    )


def _make_opportunity(workspace_id: uuid.UUID, contact_id: int) -> Opportunity:
    return Opportunity(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        pipeline_id=uuid.uuid4(),
        stage_id=uuid.uuid4(),
        primary_contact_id=contact_id,
        name="Premium plan upgrade",
        status="open",
        is_active=True,
        amount=Decimal("2500.00"),
        currency="USD",
        created_at=datetime(2026, 5, 1, tzinfo=UTC),
    )


# --------------------------------------------------------------------------- #
# Tool exposure
# --------------------------------------------------------------------------- #


def test_lookup_caller_record_tool_exposed_only_when_enabled() -> None:
    enabled = _make_agent()
    disabled = _make_agent(enabled_tools=["web_search"])

    assert is_lookup_caller_record_enabled(enabled) is True
    assert is_lookup_caller_record_enabled(disabled) is False
    assert "lookup_caller_record" in {t.get("name") for t in get_tools_from_agent_config(enabled)}
    assert "lookup_caller_record" not in {
        t.get("name") for t in get_tools_from_agent_config(disabled)
    }


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lookup_returns_callers_own_record() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    contact_id = 42
    conversation = _make_conversation(workspace_id, contact_id)
    message = _make_call_message(agent, conversation)
    contact = _make_contact(workspace_id, contact_id)
    appt = _make_appointment(workspace_id, contact_id, datetime.now(UTC) + timedelta(days=2))
    opp = _make_opportunity(workspace_id, contact_id)

    session = _IsolatingSession(
        message=message,
        contacts=[contact],
        appointments=[appt],
        opportunities=[opp],
    )

    with patch.object(db_session_module, "AsyncSessionLocal", return_value=session):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=workspace_id,
        ).execute("lookup_caller_record", {})

    assert result["success"] is True
    assert result["found"] is True
    assert result["contact"]["name"] == "Dana Vargas"
    assert result["contact"]["status"] == "qualified"
    assert result["contact"]["notes"] == "Prefers afternoon calls."
    assert len(result["upcoming_appointments"]) == 1
    assert result["upcoming_appointments"][0]["service_type"] == "Consultation"
    assert len(result["open_opportunities"]) == 1
    assert result["open_opportunities"][0]["name"] == "Premium plan upgrade"
    assert result["open_opportunities"][0]["amount"] == 2500.0
    assert result["last_interaction"]["preview"] == "Asked about pricing"


# --------------------------------------------------------------------------- #
# Workspace isolation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lookup_never_returns_cross_workspace_records() -> None:
    """Records owned by another workspace must be invisible to this caller.

    The appointment and opportunity below share the caller's ``contact_id`` but
    belong to a *different* workspace. Because every query is scoped to the
    call's workspace, the isolating session drops them — proving the WHERE
    clause carries the workspace filter, not just the contact filter.
    """
    agent = _make_agent()
    workspace_id = agent.workspace_id
    other_workspace_id = uuid.uuid4()
    contact_id = 42
    conversation = _make_conversation(workspace_id, contact_id)
    message = _make_call_message(agent, conversation)
    contact = _make_contact(workspace_id, contact_id)

    # Same contact id, but rows live in another workspace.
    foreign_appt = _make_appointment(
        other_workspace_id, contact_id, datetime.now(UTC) + timedelta(days=1)
    )
    foreign_opp = _make_opportunity(other_workspace_id, contact_id)

    session = _IsolatingSession(
        message=message,
        contacts=[contact],
        appointments=[foreign_appt],
        opportunities=[foreign_opp],
    )

    with patch.object(db_session_module, "AsyncSessionLocal", return_value=session):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=workspace_id,
        ).execute("lookup_caller_record", {})

    assert result["found"] is True
    assert result["upcoming_appointments"] == []
    assert result["open_opportunities"] == []

    # Defense in depth: the appointment and opportunity statements bind the
    # call's workspace id (never the foreign one).
    def _entity(stmt: Any) -> str:
        name: str = stmt.column_descriptions[0]["entity"].__name__
        return name

    appt_stmt = next(s for s in session.statements if _entity(s) == "Appointment")
    opp_stmt = next(s for s in session.statements if _entity(s) == "Opportunity")
    assert workspace_id in set(appt_stmt.compile().params.values())
    assert contact_id in set(appt_stmt.compile().params.values())
    assert other_workspace_id not in set(appt_stmt.compile().params.values())
    assert workspace_id in set(opp_stmt.compile().params.values())
    assert other_workspace_id not in set(opp_stmt.compile().params.values())


@pytest.mark.asyncio
async def test_lookup_contact_in_other_workspace_returns_no_record() -> None:
    """A contact that does not belong to the call's workspace is not readable."""
    agent = _make_agent()
    workspace_id = agent.workspace_id
    contact_id = 99
    conversation = _make_conversation(workspace_id, contact_id)
    message = _make_call_message(agent, conversation)
    # Contact actually belongs to a different workspace.
    foreign_contact = _make_contact(uuid.uuid4(), contact_id)

    session = _IsolatingSession(
        message=message,
        contacts=[foreign_contact],
        appointments=[],
        opportunities=[],
    )

    with patch.object(db_session_module, "AsyncSessionLocal", return_value=session):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=workspace_id,
        ).execute("lookup_caller_record", {})

    assert result == {
        "success": True,
        "found": False,
        "message": result["message"],
    }
    assert result["found"] is False


# --------------------------------------------------------------------------- #
# Unknown callers
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lookup_unknown_caller_returns_safe_no_record() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    conversation = _make_conversation(workspace_id, contact_id=None)
    message = _make_call_message(agent, conversation)

    session = _IsolatingSession(message=message, contacts=[], appointments=[], opportunities=[])

    with patch.object(db_session_module, "AsyncSessionLocal", return_value=session):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=workspace_id,
        ).execute("lookup_caller_record", {})

    assert result["success"] is True
    assert result["found"] is False
    assert "no" in result["message"].lower()


@pytest.mark.asyncio
async def test_lookup_no_call_control_id_returns_no_record() -> None:
    agent = _make_agent()

    result = await VoiceToolExecutor(agent=agent, call_control_id=None).execute(
        "lookup_caller_record", {}
    )

    assert result["success"] is True
    assert result["found"] is False
