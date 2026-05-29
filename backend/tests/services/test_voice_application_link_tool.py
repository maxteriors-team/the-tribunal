"""Tests for the Prestyj voice application-link SMS tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import app.db.session as db_session_module
import app.services.telephony.text_provider as text_provider_module
from app.models.agent import Agent
from app.models.conversation import Conversation, Message, MessageStatus
from app.services.ai.tool_executor import (
    PRESTYJ_APPLICATION_SMS_BODY,
    PRESTYJ_APPLICATION_URL,
    VoiceToolExecutor,
)
from app.services.ai.voice_tools import get_tools_from_agent_config


class _ExecuteResult:
    def __init__(self, row: Any | None) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any | None:
        return self._row


class _FakeSession:
    def __init__(self, row: Any | None) -> None:
        self.execute = AsyncMock(return_value=_ExecuteResult(row))
        self.commit = AsyncMock()
        self.refresh = AsyncMock()

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_args: object) -> bool:
        return False


def _make_agent(**overrides: Any) -> Agent:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Prestyj Voice",
        "description": "Sends application links",
        "channel_mode": "both",
        "voice_provider": "openai",
        "voice_id": "cedar",
        "language": "en-US",
        "system_prompt": "Be concise.",
        "temperature": 0.7,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "calcom_event_type_id": None,
        "enabled_tools": ["twilio-sms"],
        "tool_settings": {"twilio-sms": ["send_application_link"]},
        "is_active": True,
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 1, tzinfo=UTC),
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
        direction="outbound",
        channel="voice",
        body="",
        status=MessageStatus.ANSWERED,
        provider_message_id="call-control-1",
        agent_id=agent.id,
        campaign_id=uuid.uuid4(),
        is_ai=True,
    )


def test_application_link_tool_only_exposed_when_explicitly_enabled() -> None:
    disabled_agent = _make_agent(tool_settings={"twilio-sms": ["twilio_send_sms"]})
    enabled_agent = _make_agent()

    disabled_tool_names = {tool["name"] for tool in get_tools_from_agent_config(disabled_agent)}
    enabled_tool_names = {tool["name"] for tool in get_tools_from_agent_config(enabled_agent)}

    assert "send_application_link" not in disabled_tool_names
    assert "send_application_link" in enabled_tool_names


@pytest.mark.asyncio
async def test_send_application_link_sends_fixed_sms_to_current_caller() -> None:
    agent = _make_agent()
    call_message = _make_call_message(agent)
    sent_message = Message(
        id=uuid.uuid4(),
        conversation_id=call_message.conversation_id,
        direction="outbound",
        channel="sms",
        body=PRESTYJ_APPLICATION_SMS_BODY,
        status=MessageStatus.SENT,
        agent_id=agent.id,
        campaign_id=call_message.campaign_id,
        is_ai=True,
    )
    provider = AsyncMock()
    provider.send_message = AsyncMock(return_value=sent_message)
    provider.close = AsyncMock()

    with (
        patch.object(
            db_session_module, "AsyncSessionLocal", return_value=_FakeSession(call_message)
        ),
        patch.object(
            text_provider_module, "get_text_message_provider", return_value=provider
        ) as factory,
    ):
        result = await VoiceToolExecutor(
            agent=agent,
            call_control_id="call-control-1",
        ).execute("send_application_link", {})

    assert result == {
        "success": True,
        "application_url": PRESTYJ_APPLICATION_URL,
        "message": "Application link sent by SMS.",
    }
    factory.assert_called_once_with("telnyx")
    provider.send_message.assert_awaited_once()
    kwargs = provider.send_message.await_args.kwargs
    assert kwargs["to_number"] == "+15550002222"
    assert kwargs["from_number"] == "+15550001111"
    assert kwargs["body"] == PRESTYJ_APPLICATION_SMS_BODY
    assert kwargs["workspace_id"] == agent.workspace_id
    assert kwargs["agent_id"] == agent.id
    assert kwargs["campaign_id"] == call_message.campaign_id
    assert isinstance(kwargs["idempotency_key"], uuid.UUID)
    provider.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_application_link_returns_failure_when_call_message_missing() -> None:
    agent = _make_agent()
    provider = AsyncMock()

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=_FakeSession(None)),
        patch.object(text_provider_module, "get_text_message_provider", return_value=provider),
    ):
        result = await VoiceToolExecutor(agent=agent, call_control_id="missing").execute(
            "send_application_link",
            {},
        )

    assert result["success"] is False
    assert "conversation" in result["error"]
    provider.send_message.assert_not_called()
