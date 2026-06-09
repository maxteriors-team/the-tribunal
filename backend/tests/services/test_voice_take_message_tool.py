"""Tests for the "take a message" voice tool (``take_message``).

The tool lets a receptionist agent capture a structured message for a human
(name, callback number, reason/topic, urgency, preferred callback time, and a
free-text message), persist it, and notify operators via push + email. These
tests pin:

- The tool is opt-in (only exposed when ``take_message`` is in enabled_tools).
- A happy-path capture persists a :class:`PhoneMessage` with normalized fields
  and notifies opted-in operators by push and email.
- Sensible fallbacks (callback number / caller name from the call context) and
  urgency normalization.
- Missing call context returns a safe error without persisting.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import app.db.session as db_session_module
from app.models.agent import Agent
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.phone_message import PhoneMessage, PhoneMessageUrgency
from app.services.ai.tool_executor import VoiceToolExecutor
from app.services.ai.voice_tools import (
    TAKE_MESSAGE_TOOL,
    get_tools_from_agent_config,
    is_take_message_enabled,
)

CALL_CONTROL_ID = "caller-ccid-take-message-1"


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


class _CaptureSession:
    """Async session stub that records added rows and resolves notify queries."""

    def __init__(
        self,
        *,
        message: Message | None,
        users: list[Any],
        workspace: Any,
    ) -> None:
        self.message = message
        self.users = users
        self.workspace = workspace
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any, *_a: Any, **_k: Any) -> _Result:
        entity = stmt.column_descriptions[0]["entity"]
        name = entity.__name__
        if name == "Message":
            return _Result([self.message] if self.message is not None else [])
        if name == "User":
            return _Result(self.users)
        return _Result([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: Any) -> None:
        return None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return self.workspace

    async def __aenter__(self) -> _CaptureSession:
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
        "description": "Takes messages",
        "channel_mode": "voice",
        "voice_provider": "openai",
        "voice_id": "cedar",
        "language": "en-US",
        "system_prompt": "Be concise.",
        "temperature": 0.7,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "calcom_event_type_id": None,
        "enabled_tools": ["take_message"],
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


# --------------------------------------------------------------------------- #
# Tool exposure
# --------------------------------------------------------------------------- #


def test_take_message_tool_exposed_only_when_enabled() -> None:
    enabled = _make_agent()
    disabled = _make_agent(enabled_tools=["web_search"])

    assert is_take_message_enabled(enabled) is True
    assert is_take_message_enabled(disabled) is False
    assert TAKE_MESSAGE_TOOL["name"] == "take_message"
    assert "take_message" in {t.get("name") for t in get_tools_from_agent_config(enabled)}
    assert "take_message" not in {t.get("name") for t in get_tools_from_agent_config(disabled)}


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_take_message_persists_and_notifies() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    conversation = _make_conversation(workspace_id, contact_id=42)
    message = _make_call_message(agent, conversation)
    workspace = SimpleNamespace(id=workspace_id, name="Acme Co")
    users = [
        SimpleNamespace(id=1, email="op@acme.test", notification_email=True),
        SimpleNamespace(id=2, email="muted@acme.test", notification_email=False),
        SimpleNamespace(id=3, email=None, notification_email=True),
    ]
    session = _CaptureSession(message=message, users=users, workspace=workspace)

    push_mock = AsyncMock(return_value=True)
    email_mock = AsyncMock(return_value=True)

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=session),
        patch(
            "app.services.push_notifications.push_notification_service.send_to_workspace_members",
            push_mock,
        ),
        patch("app.services.email.send_taken_message_notification", email_mock),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=workspace_id,
        ).execute(
            "take_message",
            {
                "caller_name": "Jordan Lee",
                "callback_number": "+15557654321",
                "reason": "Wants a quote on the premium plan",
                "urgency": "high",
                "preferred_callback_time": "tomorrow afternoon",
                "message": "Please call me back about pricing.",
            },
        )

    assert result["success"] is True
    assert result["message_id"]

    # Persisted exactly one PhoneMessage with the captured + scoped fields.
    captured = [o for o in session.added if isinstance(o, PhoneMessage)]
    assert len(captured) == 1
    pm = captured[0]
    assert pm.workspace_id == workspace_id
    assert pm.message_id == message.id
    assert pm.conversation_id == conversation.id
    assert pm.contact_id == 42
    assert pm.agent_id == agent.id
    assert pm.caller_name == "Jordan Lee"
    assert pm.callback_number == "+15557654321"
    assert pm.reason == "Wants a quote on the premium plan"
    assert pm.urgency == PhoneMessageUrgency.HIGH
    assert pm.preferred_callback_time == "tomorrow afternoon"
    assert pm.message_body == "Please call me back about pricing."
    assert session.committed is True

    # Notified: one push to the workspace, one email to the single opted-in user.
    push_mock.assert_awaited_once()
    assert push_mock.await_args.kwargs["notification_type"] == "message"
    assert email_mock.await_count == 1
    assert email_mock.await_args.kwargs["to_email"] == "op@acme.test"
    assert email_mock.await_args.kwargs["urgency"] == "high"


@pytest.mark.asyncio
async def test_take_message_normalizes_urgency_and_falls_back_to_contact_phone() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    conversation = _make_conversation(workspace_id, contact_id=7)
    message = _make_call_message(agent, conversation)
    workspace = SimpleNamespace(id=workspace_id, name="Acme Co")
    session = _CaptureSession(message=message, users=[], workspace=workspace)

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=session),
        patch(
            "app.services.push_notifications.push_notification_service.send_to_workspace_members",
            AsyncMock(return_value=True),
        ),
        patch("app.services.email.send_taken_message_notification", AsyncMock(return_value=True)),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=workspace_id,
        ).execute(
            "take_message",
            {"urgency": "super-urgent", "message": "Call me."},
        )

    assert result["success"] is True
    pm = next(o for o in session.added if isinstance(o, PhoneMessage))
    # Unknown urgency normalizes to medium; callback number defaults to the
    # caller's number on the conversation.
    assert pm.urgency == PhoneMessageUrgency.MEDIUM
    assert pm.callback_number == "+15550002222"


# --------------------------------------------------------------------------- #
# Missing call context
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_take_message_without_call_control_id_errors() -> None:
    agent = _make_agent()

    result = await VoiceToolExecutor(agent=agent, call_control_id=None).execute(
        "take_message", {"message": "Hello"}
    )

    assert result["success"] is False
    assert "active call" in result["error"].lower()


@pytest.mark.asyncio
async def test_take_message_unknown_call_errors_without_persist() -> None:
    agent = _make_agent()
    session = _CaptureSession(message=None, users=[], workspace=None)

    with patch.object(db_session_module, "AsyncSessionLocal", return_value=session):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id=CALL_CONTROL_ID,
            workspace_id=agent.workspace_id,
        ).execute("take_message", {"message": "Hello"})

    assert result["success"] is False
    assert session.added == []
    assert session.committed is False
