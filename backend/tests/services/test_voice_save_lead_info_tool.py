"""Tests for the save_lead_info voice tool.

Voice calls previously had no way to write spoken lead details onto the CRM
contact record — caller-provided name/email/address only survived as free-text
message notes. save_lead_info updates the call's linked contact (creating one
from the caller's number for brand-new leads), scoped entirely to the call
context so the model can never write to another contact or workspace.

Follows the fast-unit convention of the other voice-tool tests: ``AsyncSessionLocal``
is patched with a sequenced stub session, so these never touch a real database.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import app.db.session as db_session_module
from app.models.contact import Contact
from app.services.ai.tool_executor import GATE_EXEMPT_TOOLS, VoiceToolExecutor
from app.services.ai.voice_tools import build_tools_list, is_save_lead_info_enabled


class _Agent:
    def __init__(self, enabled_tools: list[str]) -> None:
        self.enabled_tools = enabled_tools
        self.id = uuid.uuid4()
        self.workspace_id = uuid.uuid4()


class _ExecuteResult:
    def __init__(self, row: Any | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any | None:
        return self._row


class _SequencedSession:
    """Async session stub returning a queued sequence of scalar rows."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)
        self.added: list[Any] = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    async def execute(self, *_args: Any, **_kwargs: Any) -> _ExecuteResult:
        row = self._rows.pop(0) if self._rows else None
        return _ExecuteResult(row)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def __aenter__(self) -> _SequencedSession:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


class _Conversation:
    def __init__(self, contact_id: int | None, contact_phone: str) -> None:
        self.contact_id = contact_id
        self.contact_phone = contact_phone
        self.workspace_id = uuid.uuid4()


class _CallMessage:
    def __init__(self, conversation: _Conversation) -> None:
        self.conversation = conversation
        self.id = uuid.uuid4()
        self.agent_id = uuid.uuid4()


def _executor(workspace_id: uuid.UUID | None = None) -> VoiceToolExecutor:
    return VoiceToolExecutor(
        agent=object(),
        call_control_id="ccid-123",
        workspace_id=workspace_id or uuid.uuid4(),
    )


# --------------------------------------------------------------------------- #
# Exposure / gating
# --------------------------------------------------------------------------- #


def test_gated_on_save_lead_info_or_crm_update() -> None:
    assert is_save_lead_info_enabled(_Agent(["save_lead_info"])) is True
    assert is_save_lead_info_enabled(_Agent(["crm_update"])) is True
    assert is_save_lead_info_enabled(_Agent(["book_appointment"])) is False


def test_tool_present_only_when_enabled() -> None:
    assert "save_lead_info" in {t["name"] for t in build_tools_list(enable_save_lead_info=True)}
    assert "save_lead_info" not in {t["name"] for t in build_tools_list()}


def test_save_lead_info_is_gate_exempt() -> None:
    # Writing the caller's own details must not stall behind operator approval.
    assert "save_lead_info" in GATE_EXEMPT_TOOLS


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


async def test_creates_contact_for_new_caller_and_links_conversation() -> None:
    conversation = _Conversation(contact_id=None, contact_phone="+15125557001")
    session = _SequencedSession([_CallMessage(conversation)])

    with patch.object(db_session_module, "AsyncSessionLocal", lambda: session):
        result = await _executor(conversation.workspace_id)._execute_save_lead_info(
            first_name="Alex",
            email="alex@example.com",
            address="123 Main St, Austin TX 78701",
            interest="wants a kitchen remodel quote in April",
        )

    assert result["success"] is True
    # A new contact was created and added to the session.
    created = [obj for obj in session.added if isinstance(obj, Contact)]
    assert len(created) == 1
    contact = created[0]
    assert contact.first_name == "Alex"
    assert contact.email == "alex@example.com"
    assert contact.email_hash is not None
    assert contact.address_city == "Austin"
    assert contact.address_state == "TX"
    assert "kitchen remodel" in (contact.notes or "")
    assert contact.source == "inbound_call"
    session.commit.assert_awaited_once()


async def test_updates_existing_contact_without_blanking_or_replacing() -> None:
    conversation = _Conversation(contact_id=42, contact_phone="+15125557002")
    existing = Contact(
        id=42,
        workspace_id=conversation.workspace_id,
        first_name="Jamie",
        phone_number="+15125557002",
        phone_hash="hash",
        notes="existing note",
    )
    session = _SequencedSession([_CallMessage(conversation), existing])

    with patch.object(db_session_module, "AsyncSessionLocal", lambda: session):
        result = await _executor(conversation.workspace_id)._execute_save_lead_info(
            email="jamie@corp.com",
            company_name="Corp LLC",
            interest="ready to buy",
        )

    assert result["success"] is True
    # No new contact created; the existing one was mutated in place.
    assert [obj for obj in session.added if isinstance(obj, Contact)] == []
    assert existing.first_name == "Jamie"  # omitted first_name never blanks
    assert existing.email == "jamie@corp.com"
    assert existing.company_name == "Corp LLC"
    assert existing.notes is not None
    assert "existing note" in existing.notes  # appended, not replaced
    assert "ready to buy" in existing.notes


async def test_no_fields_returns_error_without_touching_db() -> None:
    session = _SequencedSession([])
    with patch.object(db_session_module, "AsyncSessionLocal", lambda: session):
        result = await _executor()._execute_save_lead_info()

    assert result["success"] is False
    session.commit.assert_not_awaited()


async def test_no_call_control_id_returns_error() -> None:
    executor = VoiceToolExecutor(agent=object(), call_control_id=None)

    result = await executor._execute_save_lead_info(first_name="Alex")

    assert result["success"] is False
