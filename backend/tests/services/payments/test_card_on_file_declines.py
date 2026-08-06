"""Declines: the three outcomes that must never be conflated.

Real Postgres, fake Stripe — but the errors are constructed as **real**
``stripe.CardError`` objects with the ``json_body`` Stripe actually sends, so the
code that reads ``error.code`` / ``error.decline_code`` / ``error.payment_intent``
is exercised against the SDK's own error shape rather than a convenient stub.

What is being pinned:

* a hard decline records, notifies once, and schedules **no retry**;
* ``authentication_required`` is recoverable — it issues a recovery link instead
  of a failure notice, because the customer only has to finish 3-D Secure;
* the ``payment_intent.payment_failed`` webhook reconciles a failure the
  synchronous path never saw;
* a failed charge leaves the invoice completely unmutated.

Run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import stripe
from sqlalchemy import select

from app.models.card_charge_attempt import CardChargeAttempt
from app.models.contact_payment_method import ContactPaymentMethod
from app.models.invoice import Invoice
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.services.invoices import InvoiceService
from app.services.payments import card_on_file_service
from tests.services.payments.conftest import (
    FakeStripeClient,
    make_contact,
    make_workspace,
    session,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _key(label: str) -> str:
    """A per-run idempotency key (keys are globally unique; the DB is not reset)."""
    return f"{label}-{uuid.uuid4().hex}"


def _pi_id(label: str) -> str:
    """A per-run PaymentIntent id.

    The reconciler falls back to looking an attempt up *by PaymentIntent id* when
    the idempotency key misses, so a hard-coded id would let one run find the
    previous run's row and skip the work under test.
    """
    return f"pi_{label}_{uuid.uuid4().hex[:12]}"


def _card_error(
    *,
    code: str,
    decline_code: str | None = None,
    message: str = "Your card was declined.",
    payment_intent_id: str | None = "pi_failed",
) -> stripe.CardError:
    """Build the ``CardError`` Stripe raises for a failed off-session charge.

    Per Stripe, a failed off-session confirmation comes back as HTTP 402 with the
    PaymentIntent embedded in the error body — which is why an
    ``authentication_required`` failure is recoverable at all.
    """
    error: dict[str, object] = {
        "type": "card_error",
        "code": code,
        "message": message,
    }
    if decline_code:
        error["decline_code"] = decline_code
    if payment_intent_id:
        error["payment_intent"] = {
            "id": payment_intent_id,
            "client_secret": f"{payment_intent_id}_secret_live",
            "status": "requires_payment_method",
        }
    return stripe.CardError(
        message,
        param=None,
        code=code,
        json_body={"error": error},
        http_status=402,
    )


async def _save_card(db: object, *, workspace_id: uuid.UUID, contact_id: int) -> None:
    db.add(  # type: ignore[attr-defined]
        ContactPaymentMethod(
            workspace_id=workspace_id,
            contact_id=contact_id,
            stripe_payment_method_id=f"pm_{uuid.uuid4().hex[:16]}",
            stripe_customer_id="cus_declines",
            brand="visa",
            last4="0341",
            is_default=True,
            status="active",
            mandate_text_version=card_on_file_service.CARD_ON_FILE_MANDATE_VERSION,
        )
    )
    await db.commit()  # type: ignore[attr-defined]


async def test_hard_decline_records_notifies_once_and_never_retries(
    fake_stripe: FakeStripeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declined card is written down, reported once, and then left alone.

    The "no retry" property is the point: a worker that re-authorises a real
    person's card on a loop is how a business earns card-network penalties.
    """
    intent_id = _pi_id("insufficient")
    fake_stripe.payment_intents.responses["create"] = _card_error(
        code="card_declined",
        decline_code="insufficient_funds",
        message="Your card has insufficient funds.",
        payment_intent_id=intent_id,
    )
    notify = AsyncMock()
    monkeypatch.setattr(card_on_file_service, "notify_charge_declined", notify)

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        key = _key("hard-decline")
        result = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=240.0,
            currency="USD",
            description="Recurring visit",
            trigger="recurring_job",
            idempotency_key=key,
            automated=True,
        )

        assert result.status == "declined"
        assert result.decline_code == "insufficient_funds"
        assert result.recovery_url is None

        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.idempotency_key == key)
        )
        attempts = rows.scalars().all()
        assert len(attempts) == 1
        assert attempts[0].status == "declined"
        assert attempts[0].decline_code == "insufficient_funds"
        assert attempts[0].stripe_payment_intent_id == intent_id

        notify.assert_awaited_once()

        # Charging again with the same key is a no-op: the recorded decline is
        # returned as-is and Stripe is not asked a second time. Nothing in this
        # module schedules a retry.
        replay = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=240.0,
            currency="USD",
            description="Recurring visit",
            trigger="recurring_job",
            idempotency_key=key,
            automated=True,
        )
        assert replay.status == "declined"
        assert replay.attempt_id == attempts[0].id

    assert fake_stripe.actions().count("payment_intents.create") == 1
    assert notify.await_count == 1


async def test_authentication_required_issues_a_recovery_link(
    fake_stripe: FakeStripeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Needs-authentication is not a lost sale, and must not read as a failure."""
    auth_intent_id = _pi_id("needs_auth")
    fake_stripe.payment_intents.responses["create"] = _card_error(
        code="authentication_required",
        decline_code="authentication_required",
        message="Your card was declined. This transaction requires authentication.",
        payment_intent_id=auth_intent_id,
    )
    notify = AsyncMock()
    monkeypatch.setattr(card_on_file_service, "notify_charge_declined", notify)

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Roof wash", unit_price=310.0)],
            ),
        )
        await svc.mark_sent(ws.id, created.id)

        key = _key("needs-auth")
        result = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=310.0,
            currency="USD",
            description=f"Invoice {created.number}",
            trigger="invoice",
            idempotency_key=key,
            automated=False,
            invoice_id=created.id,
        )

        assert result.status == "requires_action"
        # A page the customer can open — never a client secret in a URL.
        invoice_row = await db.get(Invoice, created.id)
        assert invoice_row is not None
        assert result.recovery_url is not None
        assert result.recovery_url.endswith(f"/p/invoices/{invoice_row.public_token}")
        assert "secret" not in result.recovery_url
        # The reusable secret exists in-process for this one call and is not
        # persisted anywhere.
        assert result.client_secret == f"{auth_intent_id}_secret_live"

        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.idempotency_key == key)
        )
        attempt = rows.scalar_one()
        assert attempt.status == "requires_action"
        assert attempt.stripe_payment_intent_id == auth_intent_id
        for column in CardChargeAttempt.__table__.columns:
            value = getattr(attempt, column.name)
            assert "secret" not in str(value), f"{column.name} holds a client secret"

        # This is a recoverable state, not a decline — the operator is not told
        # the card failed.
        notify.assert_not_awaited()


async def test_failed_charge_leaves_the_invoice_untouched(
    fake_stripe: FakeStripeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decline must not half-apply: no payment, no status change, no paid_at."""
    fake_stripe.payment_intents.responses["create"] = _card_error(
        code="card_declined", decline_code="do_not_honor"
    )
    monkeypatch.setattr(card_on_file_service, "notify_charge_declined", AsyncMock())

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Window clean", unit_price=95.0)],
            ),
        )
        await svc.mark_sent(ws.id, created.id)

        before = await svc.get_invoice(ws.id, created.id)

        result = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=95.0,
            currency="USD",
            description=f"Invoice {created.number}",
            trigger="invoice",
            idempotency_key=_key("invoice-declined"),
            automated=False,
            invoice_id=created.id,
        )
        assert result.status == "declined"

        after = await svc.get_invoice(ws.id, created.id)
        assert after.status == before.status == "sent"
        assert float(after.amount_paid) == 0.0
        assert after.paid_at is None

        # Read the row itself: a declined charge must not have claimed the
        # payment-intent slot ``record_payment`` keys its idempotency on.
        row = await db.get(Invoice, created.id)
        assert row is not None
        assert row.stripe_payment_intent_id is None


async def test_webhook_reconciles_a_failure_the_sync_path_missed(
    fake_stripe: FakeStripeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The network dropped mid-charge: only the webhook knows it failed.

    Without this the money never moved and *nothing* recorded that we tried —
    the exact silent failure the attempts table exists to prevent.
    """
    notify = AsyncMock()
    monkeypatch.setattr(card_on_file_service, "notify_charge_declined", notify)

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        key = _key("dropped-mid-charge")
        intent_id = _pi_id("dropped")
        event = {
            "id": intent_id,
            "amount": 12500,
            "currency": "usd",
            "last_payment_error": {
                "code": "card_declined",
                "decline_code": "lost_card",
                "message": "Your card was declined.",
            },
            "metadata": {
                "kind": "card_on_file",
                "trigger": "invoice",
                "contact_id": str(contact.id),
                "workspace_id": str(ws.id),
                "idempotency_key": key,
            },
        }

        attempt = await card_on_file_service.reconcile_failed_payment_intent(db, event)
        assert attempt is not None
        assert attempt.status == "declined"
        assert attempt.decline_code == "lost_card"
        assert attempt.amount == 125.00
        assert attempt.stripe_payment_intent_id == intent_id
        assert attempt.trigger == "invoice"
        notify.assert_awaited_once()

        # Stripe retries events; a second delivery must not duplicate the row or
        # send a second notification.
        again = await card_on_file_service.reconcile_failed_payment_intent(db, event)
        assert again is not None and again.id == attempt.id
        assert notify.await_count == 1

        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.idempotency_key == key)
        )
        assert len(rows.scalars().all()) == 1

    assert fake_stripe.calls == []


async def test_webhook_upgrades_an_error_attempt_to_declined(
    fake_stripe: FakeStripeClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``error`` row (we never learned the answer) is corrected by the webhook."""
    fake_stripe.payment_intents.responses["create"] = stripe.APIConnectionError(
        "Connection dropped"
    )
    notify = AsyncMock()
    monkeypatch.setattr(card_on_file_service, "notify_charge_declined", notify)

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        key = _key("error-then-webhook")
        result = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=60.0,
            currency="USD",
            description="Deposit",
            trigger="deposit",
            idempotency_key=key,
            automated=False,
        )
        assert result.status == "error"

        late_intent_id = _pi_id("late")
        reconciled = await card_on_file_service.reconcile_failed_payment_intent(
            db,
            {
                "id": late_intent_id,
                "amount": 6000,
                "currency": "usd",
                "last_payment_error": {"code": "card_declined", "decline_code": "generic_decline"},
                "metadata": {
                    "kind": "card_on_file",
                    "contact_id": str(contact.id),
                    "idempotency_key": key,
                },
            },
        )
        assert reconciled is not None
        assert reconciled.id == result.attempt_id
        assert reconciled.status == "declined"
        assert reconciled.decline_code == "generic_decline"
        assert reconciled.stripe_payment_intent_id == late_intent_id
        notify.assert_awaited_once()


async def test_webhook_ignores_payment_intents_that_are_not_card_on_file(
    fake_stripe: FakeStripeClient,
) -> None:
    """A failed Checkout payment is somebody else's event; it writes nothing here."""
    async with session() as db:
        before = await db.execute(select(CardChargeAttempt))
        count_before = len(before.scalars().all())

        result = await card_on_file_service.reconcile_failed_payment_intent(
            db,
            {
                "id": _pi_id("someone_else"),
                "amount": 1000,
                "currency": "usd",
                "metadata": {"invoice_id": str(uuid.uuid4())},
            },
        )
        assert result is None

        after = await db.execute(select(CardChargeAttempt))
        assert len(after.scalars().all()) == count_before
