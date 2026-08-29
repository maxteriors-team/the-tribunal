"""Regression tests for callback and frustration SMS intercepts."""

from __future__ import annotations

import types
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.ai import sms_conversation_intercepts as intercepts
from app.services.ai import text_agent
from app.services.ai.sms_conversation_intercepts import (
    classify_sms_intercept_intent,
    intercept_sms_conversation,
    parse_callback_due_at,
)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Call me and we can talk", "callback_request"),
        ("Please call me Monday at 10:00am", "callback_request"),
        ("Could someone call me?", "callback_request"),
        ("I will call Monday when I have time iam super busy", "customer_will_call"),
        ("I'll just call you when I am free", "customer_will_call"),
        ("Never mind", "disengaged"),
        ("No thank you have a good day", "disengaged"),
        ("Wow you make this way to much hassle", "frustrated"),
        ("Maybe I called the wrong business", "frustrated"),
        ("This much involved just to talk by phone is ridiculous", "frustrated"),
        ("I will let you know later busy right now", "busy"),
        ("Ok that's all I can talk later", "busy"),
    ],
)
def test_classifies_high_confidence_conversation_controls(body: str, expected: str) -> None:
    assert classify_sms_intercept_intent(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        "What do you call that fixture?",
        "Don't call me again",
        "Do not phone me",
        "No thanks, stop texting me",
        "I don't want any more messages",
        "What times are available for a design consultation?",
    ],
)
def test_does_not_misclassify_non_callback_or_opt_out_text(body: str) -> None:
    assert classify_sms_intercept_intent(body) is None


def test_parses_callback_time_into_workspace_timezone_without_calendar() -> None:
    now = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)  # Saturday, 8:00 AM EDT

    assert parse_callback_due_at(
        "Call me Monday at 10:00am",
        timezone="America/New_York",
        now=now,
    ) == datetime(2026, 8, 31, 14, 0, tzinfo=UTC)
    assert parse_callback_due_at(
        "Just call me Monday at 7pm that all",
        timezone="America/New_York",
        now=now,
    ) == datetime(2026, 8, 31, 23, 0, tzinfo=UTC)
    assert parse_callback_due_at(
        "I will call Monday when I have time",
        timezone="America/New_York",
        now=now,
    ) == datetime(2026, 8, 31, 13, 0, tzinfo=UTC)
    assert (
        parse_callback_due_at(
            "Call me and we can talk",
            timezone="America/New_York",
            now=now,
        )
        is None
    )


def _conversation() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        contact_id=uuid.uuid4(),
        contact_phone="+12485550199",
        workspace_phone="+12485551234",
    )


def _inbound(body: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(id=uuid.uuid4(), body=body)


async def test_callback_bypasses_calendar_and_alerts_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_nudge = AsyncMock(return_value=42)
    notify_operator = AsyncMock()
    monkeypatch.setattr(intercepts, "_upsert_operator_nudge", upsert_nudge)
    monkeypatch.setattr(intercepts, "_notify_operator", notify_operator)
    conversation = _conversation()
    inbound = _inbound("Call me Monday at 10:00am")

    result = await intercept_sms_conversation(
        AsyncMock(),
        conversation=conversation,
        inbound_message=inbound,
    )

    assert result is not None
    assert result.intent == "callback_request"
    assert "asked our team to call" in result.response_text.lower()
    assert "email" not in result.response_text.lower()
    assert "video" not in result.response_text.lower()
    assert "invite" not in result.response_text.lower()
    assert result.pause_ai_after_reply is True
    assert result.disable_followups_after_reply is True
    upsert_nudge.assert_awaited_once()
    notify_operator.assert_awaited_once()
    assert notify_operator.await_args.kwargs["assigned_to_user_id"] == 42


async def test_customer_will_call_gets_number_and_creates_team_nudge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_nudge = AsyncMock(return_value=42)
    notify_operator = AsyncMock()
    monkeypatch.setattr(intercepts, "_upsert_operator_nudge", upsert_nudge)
    monkeypatch.setattr(intercepts, "_notify_operator", notify_operator)

    result = await intercept_sms_conversation(
        AsyncMock(),
        conversation=_conversation(),
        inbound_message=_inbound("I will call Monday when I have time"),
    )

    assert result is not None
    assert result.intent == "customer_will_call"
    assert "(248) 555-1234" in result.response_text
    assert "what day" not in result.response_text.lower()
    assert "video" not in result.response_text.lower()
    assert result.pause_ai_after_reply is True
    upsert_nudge.assert_awaited_once()
    assert upsert_nudge.await_args.kwargs["nudge_type"] == "customer_will_call"
    notify_operator.assert_awaited_once()
    assert notify_operator.await_args.kwargs["assigned_to_user_id"] == 42


async def test_busy_customer_ends_cleanly_without_disabling_future_inbound_ai() -> None:
    result = await intercept_sms_conversation(
        AsyncMock(),
        conversation=_conversation(),
        inbound_message=_inbound("I will let you know later busy right now"),
    )

    assert result is not None
    assert result.intent == "busy"
    assert "stop here" in result.response_text
    assert "?" not in result.response_text
    assert result.pause_ai_after_reply is False
    assert result.disable_followups_after_reply is True


async def test_frustration_stops_questions_and_hands_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_nudge = AsyncMock(return_value=42)
    notify_operator = AsyncMock()
    monkeypatch.setattr(intercepts, "_upsert_operator_nudge", upsert_nudge)
    monkeypatch.setattr(intercepts, "_notify_operator", notify_operator)

    result = await intercept_sms_conversation(
        AsyncMock(),
        conversation=_conversation(),
        inbound_message=_inbound("Maybe I called the wrong business"),
    )

    assert result is not None
    assert result.intent == "frustrated"
    assert "stopped the automated questions" in result.response_text
    assert "?" not in result.response_text
    assert result.pause_ai_after_reply is True
    assert result.disable_followups_after_reply is True
    upsert_nudge.assert_awaited_once()
    notify_operator.assert_awaited_once()


class _Result:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


async def test_text_agent_intercept_bypasses_llm_and_calendar_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    conversation = types.SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        contact_id=uuid.uuid4(),
        contact_phone="+12485550199",
        workspace_phone="+12485551234",
        source_provider="telnyx",
        ai_enabled=True,
        ai_paused=False,
        ai_paused_until=None,
        assigned_agent_id=agent_id,
        followup_enabled=True,
        next_followup_at=object(),
    )
    agent = types.SimpleNamespace(
        id=agent_id,
        workspace_id=workspace_id,
        is_active=True,
        text_response_delay_ms=0,
    )
    inbound = _inbound("Call me Monday at 10:00am")
    db = types.SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(conversation), _Result(agent), _Result(inbound)]),
        commit=AsyncMock(),
    )
    result = intercepts.SmsInterceptResult(
        intent="callback_request",
        response_text="We will call this number.",
        pause_ai_after_reply=True,
        disable_followups_after_reply=True,
    )
    deterministic_intercept = AsyncMock(return_value=result)
    deliver = AsyncMock()
    credential_resolver = Mock(side_effect=AssertionError("LLM credential must not be resolved"))
    generation = AsyncMock(side_effect=AssertionError("LLM must not run"))
    monkeypatch.setattr(text_agent, "intercept_sms_conversation", deterministic_intercept)
    monkeypatch.setattr(text_agent, "_deliver_ai_response", deliver)
    monkeypatch.setattr(text_agent, "resolve_openai_credentials", credential_resolver)
    monkeypatch.setattr(text_agent, "generate_text_response", generation)

    await text_agent.process_inbound_with_ai(
        conversation.id,
        workspace_id,
        db,
        response_started_at=0.0,
    )

    deterministic_intercept.assert_awaited_once()
    deliver.assert_awaited_once()
    credential_resolver.assert_not_called()
    generation.assert_not_awaited()
    assert conversation.ai_paused is True
    assert conversation.ai_paused_until is None
    assert conversation.followup_enabled is False
    assert conversation.next_followup_at is None
    db.commit.assert_awaited_once()
