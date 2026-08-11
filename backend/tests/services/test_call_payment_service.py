"""Tests for the Stripe-backed in-call payment service helpers.

These pin the status-recording + operator-notification behavior shared by the
``check_payment_status`` voice tool and the Stripe billing webhook:

- ``handle_checkout_session_completed`` resolves a :class:`CallPayment` from the
  Stripe session metadata and marks it paid, notifying operators once.
- ``mark_call_payment_paid`` is idempotent (a second call is a no-op and does
  not re-notify).
- Minor-unit conversion respects zero-decimal currencies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.call_payment import CallPayment, CallPaymentStatus
from app.services.payments import call_payment_service


class _Session:
    """Minimal async session stub with get/commit and notify suppression."""

    def __init__(self, payment: CallPayment | None) -> None:
        self.payment = payment
        self.commits = 0

    async def get(self, _model: Any, ident: Any) -> Any:
        if self.payment is not None and self.payment.id == ident:
            return self.payment
        return None

    async def execute(self, *_a: Any, **_k: Any) -> Any:  # pragma: no cover - not hit here
        raise AssertionError("execute should not be called when metadata id resolves")

    async def commit(self) -> None:
        self.commits += 1


def _make_payment(**overrides: Any) -> CallPayment:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "amount": 75,
        "currency": "usd",
        "status": CallPaymentStatus.PENDING,
        "stripe_checkout_session_id": "cs_test_abc",
        "created_at": datetime(2026, 6, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return CallPayment(**values)


def test_to_minor_units_handles_zero_decimal_currencies() -> None:
    assert call_payment_service.to_minor_units(50, "usd") == 5000
    assert call_payment_service.to_minor_units(50.5, "usd") == 5050
    # JPY is zero-decimal: no *100 scaling.
    assert call_payment_service.to_minor_units(500, "jpy") == 500


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "expected"), [("open", True), ("complete", False)])
async def test_expire_checkout_session_only_expires_open_sessions(
    status: str, expected: bool
) -> None:
    client = MagicMock()
    client.checkout.sessions.retrieve.return_value = SimpleNamespace(status=status)

    with patch.object(call_payment_service, "_stripe_client", return_value=client):
        result = await call_payment_service.expire_checkout_session_if_open("cs_test_old")

    assert result is expected
    if expected:
        client.checkout.sessions.expire.assert_called_once_with("cs_test_old")
    else:
        client.checkout.sessions.expire.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_marks_payment_paid_and_notifies_once() -> None:
    payment = _make_payment()
    session = _Session(payment)
    notify = AsyncMock()

    event = {
        "id": "cs_test_abc",
        "mode": "payment",
        "payment_intent": "pi_test_xyz",
        "metadata": {"call_payment_id": str(payment.id)},
    }

    with patch.object(call_payment_service, "notify_payment_operators", notify):
        await call_payment_service.handle_checkout_session_completed(event, session)

    assert payment.status == CallPaymentStatus.PAID
    assert payment.paid_at is not None
    assert payment.stripe_payment_intent_id == "pi_test_xyz"
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_mark_paid_is_idempotent() -> None:
    payment = _make_payment(status=CallPaymentStatus.PAID, paid_at=datetime.now(UTC))
    session = _Session(payment)
    notify = AsyncMock()

    with patch.object(call_payment_service, "notify_payment_operators", notify):
        did_transition = await call_payment_service.mark_call_payment_paid(session, payment)

    assert did_transition is False
    notify.assert_not_awaited()
