"""Permanent proposal payments use immutable local truth at every Stripe boundary."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.models.quote import Quote
from app.models.workspace import Workspace
from app.services.payments import proposal_payment_service as payments
from app.services.payments.call_payment_service import CheckoutSessionResult


@pytest.fixture(autouse=True)
def _empty_operator_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "proposal_payment_pilot_workspace_ids", set())


def _quote(
    choice: payments.PaymentChoice = "fifty_percent_down", *, operator_enabled: bool = True
) -> Quote:
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Maxteriors Lighting",
        slug=f"payment-{uuid.uuid4().hex[:8]}",
        settings={"proposal_payments_enabled": True},
    )
    quote = Quote(
        id=uuid.uuid4(),
        workspace_id=workspace.id,
        number="QUO-PAYMENT",
        status="approved",
        currency="USD",
        public_token=f"proposal-{uuid.uuid4().hex}",
        proposal_document={"service": "permanent"},
        proposal_payment_choice=choice,
        proposal_payment_amount=Decimal("500.01")
        if choice == "fifty_percent_down"
        else Decimal("1000.01"),
    )
    quote.total = 1000.01
    quote.workspace = workspace
    if operator_enabled:
        settings.proposal_payment_pilot_workspace_ids.add(workspace.id)
    return quote


class _ScalarResult:
    def __init__(self, value: Quote) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Quote:
        return self.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operator_enabled", "workspace_enabled"),
    [(False, True), (True, False)],
)
async def test_checkout_requires_operator_and_workspace_enablement(
    monkeypatch: pytest.MonkeyPatch,
    operator_enabled: bool,
    workspace_enabled: bool,
) -> None:
    quote = _quote("pay_in_full", operator_enabled=operator_enabled)
    assert quote.workspace is not None
    if not workspace_enabled:
        quote.workspace.settings = {}
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(quote)),
        commit=AsyncMock(),
    )
    create = AsyncMock()
    monkeypatch.setattr(payments.call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(payments.call_payment_service, "create_payment_checkout_session", create)

    with pytest.raises(payments.ProposalPaymentError, match="not approved"):
        await payments.create_proposal_payment_checkout_session(
            cast(Any, db), quote.public_token or ""
        )

    create.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("choice", "expected_amount", "product_copy"),
    [
        ("fifty_percent_down", Decimal("500.01"), "50% payment for"),
        ("pay_in_full", Decimal("1000.01"), "Payment in full for"),
    ],
)
async def test_checkout_uses_persisted_amount_and_dedicated_metadata(
    monkeypatch: pytest.MonkeyPatch,
    choice: payments.PaymentChoice,
    expected_amount: Decimal,
    product_copy: str,
) -> None:
    quote = _quote(choice)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(quote)),
        commit=AsyncMock(),
    )
    captured: dict[str, Any] = {}

    async def fake_checkout(**kwargs: Any) -> CheckoutSessionResult:
        captured.update(kwargs)
        return CheckoutSessionResult(
            session_id=f"cs_{choice}",
            url=f"https://checkout.stripe.test/{choice}",
            payment_intent_id=None,
        )

    monkeypatch.setattr(payments.call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(
        payments.call_payment_service, "create_payment_checkout_session", fake_checkout
    )

    checkout = await payments.create_proposal_payment_checkout_session(
        cast(Any, db), quote.public_token or ""
    )

    assert captured["amount"] == expected_amount
    assert captured["currency"] == "USD"
    assert product_copy in captured["product_name"]
    assert captured["metadata"] == {
        "kind": payments.PROPOSAL_PAYMENT_KIND,
        "quote_id": str(quote.id),
        "workspace_id": str(quote.workspace_id),
        "proposal_payment_choice": choice,
    }
    assert captured["idempotency_key"] == str(
        payments.derive_outbound_key("proposal_payment_checkout", quote.id, choice, "initial")
    )
    assert checkout.amount == float(expected_amount)
    assert checkout.payment_choice == choice
    assert quote.proposal_payment_checkout_session_id == f"cs_{choice}"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["open", "complete"])
async def test_existing_checkout_is_reused_or_left_processing_without_duplicate_charge(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    quote = _quote()
    quote.proposal_payment_checkout_session_id = "cs_expected"
    db = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(quote)))
    details = payments.call_payment_service.CheckoutSessionDetails(
        payment_status="unpaid",
        status=status,
        payment_intent_id=None,
        mode="payment",
        metadata={
            "kind": payments.PROPOSAL_PAYMENT_KIND,
            "quote_id": str(quote.id),
            "workspace_id": str(quote.workspace_id),
            "proposal_payment_choice": "fifty_percent_down",
        },
        amount_total=50001,
        currency="usd",
        url="https://checkout.stripe.test/existing",
    )
    create_new = AsyncMock()
    monkeypatch.setattr(payments.call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(
        payments.call_payment_service,
        "retrieve_checkout_session_details",
        AsyncMock(return_value=details),
    )
    monkeypatch.setattr(
        payments.call_payment_service, "create_payment_checkout_session", create_new
    )

    if status == "complete":
        with pytest.raises(payments.ProposalPaymentError, match="still processing"):
            await payments.create_proposal_payment_checkout_session(
                cast(Any, db), quote.public_token or ""
            )
    else:
        checkout = await payments.create_proposal_payment_checkout_session(
            cast(Any, db), quote.public_token or ""
        )
        assert checkout.url == "https://checkout.stripe.test/existing"
    create_new.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("choice", "description"),
    [
        ("fifty_percent_down", "50% down payment on QUO-PAYMENT"),
        ("pay_in_full", "Payment in full on QUO-PAYMENT"),
    ],
)
async def test_operator_notification_names_the_selected_schedule(
    monkeypatch: pytest.MonkeyPatch,
    choice: payments.PaymentChoice,
    description: str,
) -> None:
    from app.services.payments import customer_payment_notifications

    quote = _quote(choice)
    db = SimpleNamespace(get=AsyncMock(return_value=None))
    notify = AsyncMock(return_value=True)
    monkeypatch.setattr(customer_payment_notifications, "notify_customer_payment", notify)

    await payments._notify_proposal_payment_paid(cast(Any, db), quote)

    assert notify.await_args.kwargs["description"] == description
    assert notify.await_args.kwargs["amount"] == quote.proposal_payment_amount


def _paid_event(quote: Quote) -> dict[str, Any]:
    return {
        "id": "cs_expected",
        "payment_status": "paid",
        "status": "complete",
        "payment_intent": "pi_expected",
        "mode": "payment",
        "amount_total": 50001,
        "currency": "usd",
        "metadata": {
            "kind": payments.PROPOSAL_PAYMENT_KIND,
            "quote_id": str(quote.id),
            "workspace_id": str(quote.workspace_id),
            "proposal_payment_choice": "fifty_percent_down",
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch",
    [
        "session_id",
        "payment_status",
        "status",
        "payment_intent",
        "mode",
        "amount",
        "currency",
        "kind",
        "quote_id",
        "workspace_id",
        "choice",
    ],
)
async def test_webhook_mismatch_never_marks_payment(
    monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    quote = _quote()
    quote.proposal_payment_checkout_session_id = "cs_expected"
    event = _paid_event(quote)
    if mismatch == "session_id":
        event["id"] = "cs_other"
    elif mismatch == "payment_status":
        event["payment_status"] = "unpaid"
    elif mismatch == "status":
        event["status"] = "open"
    elif mismatch == "payment_intent":
        event["payment_intent"] = None
    elif mismatch == "mode":
        event["mode"] = "subscription"
    elif mismatch == "amount":
        event["amount_total"] = 50000
    elif mismatch == "currency":
        event["currency"] = "cad"
    elif mismatch == "kind":
        event["metadata"]["kind"] = "quote_deposit"
    elif mismatch == "quote_id":
        event["metadata"]["quote_id"] = str(uuid.uuid4())
    elif mismatch == "workspace_id":
        event["metadata"]["workspace_id"] = str(uuid.uuid4())
    else:
        event["metadata"]["proposal_payment_choice"] = "pay_in_full"

    db = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(quote)))
    mark_paid = AsyncMock()
    monkeypatch.setattr(payments, "mark_proposal_payment_paid", mark_paid)

    await payments.handle_proposal_payment_checkout_session_completed(event, cast(Any, db))

    mark_paid.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_webhook_records_exact_session_and_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = _quote()
    quote.proposal_payment_checkout_session_id = "cs_expected"
    db = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(quote)))
    mark_paid = AsyncMock(return_value=True)
    monkeypatch.setattr(payments, "mark_proposal_payment_paid", mark_paid)

    await payments.handle_proposal_payment_checkout_session_completed(
        _paid_event(quote), cast(Any, db)
    )

    mark_paid.assert_awaited_once_with(
        cast(Any, db),
        quote,
        session_id="cs_expected",
        payment_intent_id="pi_expected",
    )
