"""Tests for the live warm/cold call transfer (AI -> human) tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import app.db.session as db_session_module
from app.models.agent import Agent
from app.models.conversation import Conversation, Message, MessageStatus
from app.models.workspace import Workspace
from app.services.ai.tool_executor import VoiceToolExecutor
from app.services.ai.voice_tools import get_tools_from_agent_config, is_transfer_enabled
from app.services.telephony.call_transfer import (
    PendingTransfer,
    build_briefing,
    resolve_transfer_config,
)


def _make_agent(**overrides: Any) -> Agent:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Closer Bot",
        "description": "Hands hot leads to a human",
        "channel_mode": "voice",
        "voice_provider": "openai",
        "voice_id": "cedar",
        "language": "en-US",
        "system_prompt": "Be concise.",
        "temperature": 0.7,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "enabled_tools": ["call_control"],
        "tool_settings": {"call_control": ["transfer_call"]},
        "transfer_destination_number": "+15551234567",
        "transfer_mode": "warm",
        "transfer_briefing_template": None,
        "is_active": True,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return Agent(**values)


def _make_call_message(agent: Agent) -> Message:
    conversation = Conversation(
        id=uuid.uuid4(),
        workspace_id=agent.workspace_id,
        workspace_phone="+15550001111",
        contact_phone="+15550002222",
        channel="voice",
        ai_enabled=True,
    )
    return Message(
        id=uuid.uuid4(),
        conversation=conversation,
        conversation_id=conversation.id,
        direction="inbound",
        channel="voice",
        body="",
        status=MessageStatus.ANSWERED,
        provider_message_id="caller-ccid-1",
        agent_id=agent.id,
        campaign_id=None,
        is_ai=True,
    )


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
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def execute(self, *_args: Any, **_kwargs: Any) -> _ExecuteResult:
        row = self._rows.pop(0) if self._rows else None
        return _ExecuteResult(row)

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def __aenter__(self) -> _SequencedSession:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


# --------------------------------------------------------------------------- #
# Tool exposure
# --------------------------------------------------------------------------- #


def test_transfer_tool_exposed_only_when_enabled() -> None:
    enabled = _make_agent()
    disabled = _make_agent(
        enabled_tools=["call_control"], tool_settings={"call_control": ["send_dtmf"]}
    )

    assert "transfer_call" in {t["name"] for t in get_tools_from_agent_config(enabled)}
    assert "transfer_call" not in {t["name"] for t in get_tools_from_agent_config(disabled)}


def test_is_transfer_enabled_direct_and_integration_patterns() -> None:
    direct = _make_agent(enabled_tools=["transfer_call"], tool_settings={})
    integration = _make_agent()
    off = _make_agent(enabled_tools=[], tool_settings={})

    assert is_transfer_enabled(direct) is True
    assert is_transfer_enabled(integration) is True
    assert is_transfer_enabled(off) is False


# --------------------------------------------------------------------------- #
# Config resolution + briefing
# --------------------------------------------------------------------------- #


def test_resolve_transfer_config_prefers_agent_over_workspace() -> None:
    agent = _make_agent(transfer_destination_number="+15551112222", transfer_mode="cold")
    res = resolve_transfer_config(agent, {"transfer_destination_number": "+19998887777"})
    assert res is not None
    assert res.destination_number == "+15551112222"
    assert res.mode == "cold"


def test_resolve_transfer_config_falls_back_to_workspace() -> None:
    agent = _make_agent(transfer_destination_number=None, transfer_mode=None)
    res = resolve_transfer_config(
        agent, {"transfer_destination_number": "+19998887777", "transfer_mode": "warm"}
    )
    assert res is not None
    assert res.destination_number == "+19998887777"
    assert res.mode == "warm"


def test_resolve_transfer_config_returns_none_without_destination() -> None:
    agent = _make_agent(transfer_destination_number=None)
    assert resolve_transfer_config(agent, {}) is None
    assert resolve_transfer_config(agent, None) is None


def test_build_briefing_template_and_default() -> None:
    templated = build_briefing(
        template="{caller_name} wants {intent}.",
        caller_name="Dana",
        intent="a quote",
        summary="ignored",
    )
    assert templated == "Dana wants a quote."

    default = build_briefing(
        template=None, caller_name="Sam", intent="pricing", summary="Has a budget."
    )
    assert "Sam" in default
    assert "pricing" in default
    assert "Has a budget." in default


def test_pending_transfer_json_roundtrip() -> None:
    pending = PendingTransfer(
        caller_call_control_id="caller",
        closer_call_control_id="closer",
        workspace_id="ws",
        agent_id="ag",
        mode="warm",
        briefing="brief the human",
        language="en-US",
        created_at="2026-06-05T00:00:00+00:00",
    )
    restored = PendingTransfer.from_json(pending.to_json())
    assert restored == pending


# --------------------------------------------------------------------------- #
# Execution: cold transfer
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_cold_transfer_issues_telnyx_transfer_and_audits() -> None:
    agent = _make_agent(transfer_mode="cold")
    call_message = _make_call_message(agent)
    workspace = Workspace(id=agent.workspace_id, name="WS", slug="ws", settings={})

    voice_service = AsyncMock()
    voice_service.transfer_call = AsyncMock(return_value=True)
    voice_service.close = AsyncMock()

    audit = AsyncMock()

    with (
        patch.object(
            db_session_module,
            "AsyncSessionLocal",
            side_effect=lambda: _SequencedSession([call_message, workspace]),
        ),
        patch(
            "app.services.telephony.telnyx_voice.TelnyxVoiceService",
            return_value=voice_service,
        ),
        patch("app.services.telephony.call_transfer.log_transfer_audit", audit),
        patch("app.core.config.settings.telnyx_api_key", "key-123"),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            contact_info={"name": "Jane Doe"},
            call_control_id="caller-ccid-1",
        ).execute("transfer_call", {"reason": "hot lead", "intent": "buy now"})

    assert result["success"] is True
    assert result["mode"] == "cold"
    voice_service.transfer_call.assert_awaited_once()
    kwargs = voice_service.transfer_call.await_args.kwargs
    assert kwargs["call_control_id"] == "caller-ccid-1"
    assert kwargs["to_number"] == "+15551234567"
    assert kwargs["from_number"] == "+15550001111"
    audit.assert_awaited()
    assert audit.await_args.kwargs["decision"] == "executed"
    voice_service.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cold_transfer_reports_failure_when_telnyx_rejects() -> None:
    agent = _make_agent(transfer_mode="cold")
    call_message = _make_call_message(agent)
    workspace = Workspace(id=agent.workspace_id, name="WS", slug="ws", settings={})

    voice_service = AsyncMock()
    voice_service.transfer_call = AsyncMock(return_value=False)
    voice_service.close = AsyncMock()

    with (
        patch.object(
            db_session_module,
            "AsyncSessionLocal",
            side_effect=lambda: _SequencedSession([call_message, workspace]),
        ),
        patch(
            "app.services.telephony.telnyx_voice.TelnyxVoiceService",
            return_value=voice_service,
        ),
        patch("app.services.telephony.call_transfer.log_transfer_audit", AsyncMock()),
        patch("app.core.config.settings.telnyx_api_key", "key-123"),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id="caller-ccid-1",
        ).execute("transfer_call", {"reason": "human please"})

    assert result["success"] is False
    assert "could not be started" in result["error"]


# --------------------------------------------------------------------------- #
# Execution: warm transfer
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_warm_transfer_dials_closer_and_stores_pending_state() -> None:
    agent = _make_agent(transfer_mode="warm")
    call_message = _make_call_message(agent)
    workspace = Workspace(id=agent.workspace_id, name="WS", slug="ws", settings={})

    voice_service = AsyncMock()
    voice_service.dial_transfer_leg = AsyncMock(return_value="closer-ccid-9")
    voice_service.get_call_control_application_id = AsyncMock(return_value="conn-1")
    voice_service.close = AsyncMock()

    store_pending = AsyncMock()

    with (
        patch.object(
            db_session_module,
            "AsyncSessionLocal",
            side_effect=lambda: _SequencedSession([call_message, workspace]),
        ),
        patch(
            "app.services.telephony.telnyx_voice.TelnyxVoiceService",
            return_value=voice_service,
        ),
        patch("app.services.telephony.call_transfer.store_pending_transfer", store_pending),
        patch("app.services.telephony.call_transfer.log_transfer_audit", AsyncMock()),
        patch("app.core.config.settings.telnyx_api_key", "key-123"),
        patch("app.core.config.settings.telnyx_connection_id", ""),
        patch("app.core.config.settings.api_base_url", "https://api.example.com"),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            contact_info={"name": "Jane Doe"},
            call_control_id="caller-ccid-1",
        ).execute(
            "transfer_call",
            {"reason": "hot lead", "intent": "wants premium", "summary": "Budget 5k."},
        )

    assert result["success"] is True
    assert result["mode"] == "warm"
    voice_service.dial_transfer_leg.assert_awaited_once()
    dial_kwargs = voice_service.dial_transfer_leg.await_args.kwargs
    assert dial_kwargs["to_number"] == "+15551234567"
    assert dial_kwargs["from_number"] == "+15550001111"
    assert dial_kwargs["webhook_url"] == "https://api.example.com/webhooks/telnyx/voice"

    store_pending.assert_awaited_once()
    pending = store_pending.await_args.args[0]
    assert pending.caller_call_control_id == "caller-ccid-1"
    assert pending.closer_call_control_id == "closer-ccid-9"
    assert "Jane Doe" in pending.briefing
    assert "wants premium" in pending.briefing


@pytest.mark.asyncio
async def test_warm_transfer_fails_gracefully_when_dial_fails() -> None:
    agent = _make_agent(transfer_mode="warm")
    call_message = _make_call_message(agent)
    workspace = Workspace(id=agent.workspace_id, name="WS", slug="ws", settings={})

    voice_service = AsyncMock()
    voice_service.dial_transfer_leg = AsyncMock(return_value=None)
    voice_service.get_call_control_application_id = AsyncMock(return_value="conn-1")
    voice_service.close = AsyncMock()

    with (
        patch.object(
            db_session_module,
            "AsyncSessionLocal",
            side_effect=lambda: _SequencedSession([call_message, workspace]),
        ),
        patch(
            "app.services.telephony.telnyx_voice.TelnyxVoiceService",
            return_value=voice_service,
        ),
        patch("app.services.telephony.call_transfer.store_pending_transfer", AsyncMock()),
        patch("app.services.telephony.call_transfer.log_transfer_audit", AsyncMock()),
        patch("app.core.config.settings.telnyx_api_key", "key-123"),
        patch("app.core.config.settings.telnyx_connection_id", "conn-1"),
        patch("app.core.config.settings.api_base_url", "https://api.example.com"),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id="caller-ccid-1",
        ).execute("transfer_call", {"reason": "hot lead"})

    assert result["success"] is False
    assert "Could not reach a team member" in result["error"]


# --------------------------------------------------------------------------- #
# Execution: no destination configured
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_transfer_without_destination_is_blocked_and_audited() -> None:
    agent = _make_agent(transfer_destination_number=None, transfer_mode="warm")
    call_message = _make_call_message(agent)
    workspace = Workspace(id=agent.workspace_id, name="WS", slug="ws", settings={})

    audit = AsyncMock()

    with (
        patch.object(
            db_session_module,
            "AsyncSessionLocal",
            side_effect=lambda: _SequencedSession([call_message, workspace]),
        ),
        patch("app.services.telephony.call_transfer.log_transfer_audit", audit),
        patch("app.core.config.settings.telnyx_api_key", "key-123"),
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id="caller-ccid-1",
        ).execute("transfer_call", {"reason": "human please"})

    assert result["success"] is False
    assert "No human transfer destination" in result["error"]
    audit.assert_awaited_once()
    assert audit.await_args.kwargs["decision"] == "blocked"
