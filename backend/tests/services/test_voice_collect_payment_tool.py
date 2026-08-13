"""Tests for the in-call payment/deposit collection voice tool.

The ``collect_payment`` tool never reads raw card numbers over the AI channel:
it creates a Stripe Checkout Session for the requested amount and texts the
secure hosted link to the caller, recording a :class:`CallPayment` (pending)
against the contact/opportunity. The companion ``check_payment_status`` tool
reconciles status from Stripe and, on first confirmation, records paid + notifies
operators. These tests pin:

- The tools are opt-in (only exposed when ``collect_payment`` is in enabled_tools).
- Amount guardrails reject invalid/too-small amounts without persisting.
- Happy path persists a pending CallPayment, creates a Stripe session, and texts
  the link (no card data), recording session id + url + sms message id.
- ``check_payment_status`` flips a pending payment to paid when Stripe reports
  ``paid`` and notifies operators.
- Missing call context returns a safe error.
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
from app.models.call_payment import CallPayment, CallPaymentStatus
from app.models.conversation import Conversation, Message, MessageStatus
from app.services.ai.tool_executor import VoiceToolExecutor
from app.services.ai.voice_tools import (
    CHECK_PAYMENT_STATUS_TOOL,
    COLLECT_PAYMENT_TOOL,
    get_tools_from_agent_config,
    is_collect_payment_enabled,
)
from app.services.payments import call_payment_service
from app.services.payments.call_payment_service import (
    CheckoutSessionResult,
    SessionStatus,
)

CALL_CONTROL_ID = "caller-ccid-collect-payment-1"


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

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


class _Session:
    """Async session stub routing queries by selected entity name."""

    def __init__(
        self,
        *,
        message: Message | None,
        payment: CallPayment | None = None,
        opportunities: list[Any] | None = None,
    ) -> None:
        self.message = message
        self.payment = payment
        self.opportunities = opportunities or []
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, stmt: Any, *_a: Any, **_k: Any) -> _Result:
        name = stmt.column_descriptions[0]["entity"].__name__
        if name == "Message":
            return _Result([self.message] if self.message is not None else [])
        if name == "Opportunity":
            return _Result(self.opportunities)
        if name == "CallPayment":
            return _Result([self.payment] if self.payment is not None else [])
        return _Result([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, CallPayment) and self.payment is None:
            self.payment = obj

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj: Any) -> None:
        return None

    async def get(self, _model: Any, _ident: Any) -> Any:
        return None

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False


class _FakeProvider:
    def __init__(self, status: str = "sent") -> None:
        self.status = status
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4(), status=self.status)

    async def close(self) -> None:
        return None


# --------------------------------------------------------------------------- #
# Builders
# --------------------------------------------------------------------------- #


def _make_agent(**overrides: Any) -> Agent:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "name": "Front Desk",
        "description": "Takes deposits",
        "channel_mode": "voice",
        "voice_provider": "openai",
        "voice_id": "cedar",
        "language": "en-US",
        "system_prompt": "Be concise.",
        "temperature": 0.7,
        "text_response_delay_ms": 30_000,
        "text_max_context_messages": 20,
        "enabled_tools": ["collect_payment"],
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


def test_collect_payment_tool_exposed_only_when_enabled() -> None:
    enabled = _make_agent()
    disabled = _make_agent(enabled_tools=["web_search"])

    assert is_collect_payment_enabled(enabled) is True
    assert is_collect_payment_enabled(disabled) is False
    assert COLLECT_PAYMENT_TOOL["name"] == "collect_payment"
    assert CHECK_PAYMENT_STATUS_TOOL["name"] == "check_payment_status"

    enabled_names = {t.get("name") for t in get_tools_from_agent_config(enabled)}
    disabled_names = {t.get("name") for t in get_tools_from_agent_config(disabled)}
    assert {"collect_payment", "check_payment_status"} <= enabled_names
    assert "collect_payment" not in disabled_names
    assert "check_payment_status" not in disabled_names


def test_collect_payment_tool_never_requests_card_fields() -> None:
    # Defense: the tool schema must not accept raw card data over the AI channel.
    # It only takes an amount/description/currency; the secure link is texted out.
    props = COLLECT_PAYMENT_TOOL["parameters"]["properties"]
    assert set(props) == {"amount", "description", "currency"}
    # And the description must explicitly instruct the model never to take card data.
    assert "never" in COLLECT_PAYMENT_TOOL["description"].lower()


# --------------------------------------------------------------------------- #
# Amount guardrails
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_collect_payment_rejects_invalid_amount_without_persist() -> None:
    agent = _make_agent()
    session = _Session(message=None)

    with patch.object(db_session_module, "AsyncSessionLocal", return_value=session):
        result = await VoiceToolExecutor(
            agent=agent, call_control_id=CALL_CONTROL_ID, workspace_id=agent.workspace_id
        ).execute("collect_payment", {"amount": 0})

    assert result["success"] is False
    assert session.added == []


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_collect_payment_creates_pending_payment_and_texts_link() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    conversation = _make_conversation(workspace_id, contact_id=42)
    message = _make_call_message(agent, conversation)
    session = _Session(message=message)

    provider = _FakeProvider(status="sent")
    checkout = CheckoutSessionResult(
        session_id="cs_test_123",
        url="https://checkout.stripe.test/pay/cs_test_123",
        payment_intent_id="pi_test_123",
    )

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=session),
        patch.object(call_payment_service, "is_payment_configured", return_value=True),
        patch.object(
            call_payment_service,
            "create_payment_checkout_session",
            AsyncMock(return_value=checkout),
        ) as create_mock,
        patch(
            "app.services.telephony.text_provider.get_text_message_provider",
            return_value=provider,
        ),
    ):
        result = await VoiceToolExecutor(
            agent=agent, call_control_id=CALL_CONTROL_ID, workspace_id=workspace_id
        ).execute(
            "collect_payment",
            {"amount": 50, "description": "Booking deposit", "currency": "USD"},
        )

    assert result["success"] is True
    assert result["amount"] == 50.0
    assert result["currency"] == "usd"

    # Persisted exactly one CallPayment, scoped to the call, with Stripe refs.
    payments = [o for o in session.added if isinstance(o, CallPayment)]
    assert len(payments) == 1
    pay = payments[0]
    assert pay.workspace_id == workspace_id
    assert pay.message_id == message.id
    assert pay.conversation_id == conversation.id
    assert pay.contact_id == 42
    assert pay.agent_id == agent.id
    assert float(pay.amount) == 50.0
    assert pay.currency == "usd"
    assert pay.description == "Booking deposit"
    assert pay.status == CallPaymentStatus.PENDING
    assert pay.stripe_checkout_session_id == "cs_test_123"
    assert pay.payment_link_url == checkout.url

    # Stripe session created in payment mode with secure metadata; amount in cents.
    create_mock.assert_awaited_once()
    kwargs = create_mock.await_args.kwargs
    assert kwargs["amount"] == 50.0
    assert kwargs["currency"] == "usd"
    assert kwargs["metadata"]["kind"] == call_payment_service.PAYMENT_KIND
    assert kwargs["metadata"]["contact_id"] == "42"

    # The link was texted to the caller and contains the Stripe URL (no card data).
    assert len(provider.sent) == 1
    sms = provider.sent[0]
    assert sms["to_number"] == "+15550002222"
    assert checkout.url in sms["body"]


# --------------------------------------------------------------------------- #
# Status confirmation
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_check_payment_status_marks_paid_and_notifies() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    conversation = _make_conversation(workspace_id, contact_id=42)
    message = _make_call_message(agent, conversation)
    payment = CallPayment(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        amount=50,
        currency="usd",
        status=CallPaymentStatus.PENDING,
        stripe_checkout_session_id="cs_test_123",
    )
    session = _Session(message=message, payment=payment)

    notify_mock = AsyncMock()
    paid_status = SessionStatus(
        payment_status="paid", status="complete", payment_intent_id="pi_test_123"
    )

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=session),
        patch.object(call_payment_service, "is_payment_configured", return_value=True),
        patch.object(
            call_payment_service,
            "retrieve_session_status",
            AsyncMock(return_value=paid_status),
        ),
        patch.object(call_payment_service, "notify_payment_operators", notify_mock),
    ):
        result = await VoiceToolExecutor(
            agent=agent, call_control_id=CALL_CONTROL_ID, workspace_id=workspace_id
        ).execute("check_payment_status", {})

    assert result["success"] is True
    assert result["paid"] is True
    assert result["status"] == "paid"
    assert payment.status == CallPaymentStatus.PAID
    assert payment.paid_at is not None
    assert payment.stripe_payment_intent_id == "pi_test_123"
    notify_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_payment_status_pending_when_stripe_unpaid() -> None:
    agent = _make_agent()
    workspace_id = agent.workspace_id
    conversation = _make_conversation(workspace_id, contact_id=42)
    message = _make_call_message(agent, conversation)
    payment = CallPayment(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        conversation_id=conversation.id,
        amount=50,
        currency="usd",
        status=CallPaymentStatus.PENDING,
        stripe_checkout_session_id="cs_test_123",
    )
    session = _Session(message=message, payment=payment)
    unpaid = SessionStatus(payment_status="unpaid", status="open", payment_intent_id=None)

    with (
        patch.object(db_session_module, "AsyncSessionLocal", return_value=session),
        patch.object(call_payment_service, "is_payment_configured", return_value=True),
        patch.object(
            call_payment_service,
            "retrieve_session_status",
            AsyncMock(return_value=unpaid),
        ),
    ):
        result = await VoiceToolExecutor(
            agent=agent, call_control_id=CALL_CONTROL_ID, workspace_id=workspace_id
        ).execute("check_payment_status", {})

    assert result["success"] is True
    assert result["paid"] is False
    assert result["status"] == "pending"
    assert payment.status == CallPaymentStatus.PENDING


# --------------------------------------------------------------------------- #
# Missing call context
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_collect_payment_without_call_control_id_errors() -> None:
    agent = _make_agent()

    with patch.object(call_payment_service, "is_payment_configured", return_value=True):
        result = await VoiceToolExecutor(agent=agent, call_control_id=None).execute(
            "collect_payment", {"amount": 25}
        )

    assert result["success"] is False
    assert "active call" in result["error"].lower()
