"""Charging a card on file: success, idempotency, isolation, and opt-out.

Real Postgres (the unique ``idempotency_key`` is doing real work here), fake
Stripe. Run with ``pytest -m integration``.

The declined and needs-authentication paths live in
``test_card_on_file_declines.py``; this file is about the charges that are
*allowed to happen* and the ones that must not be attempted at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.card_charge_attempt import CardChargeAttempt
from app.models.contact_payment_method import ContactPaymentMethod
from app.models.tag import ContactTag, Tag
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.services.automations.opt_out import NO_AUTOMATION_TAG
from app.services.invoices import InvoiceService
from app.services.payments import card_on_file_service
from tests.services.payments.conftest import (
    FakeStripeClient,
    FakeStripeObject,
    make_contact,
    make_workspace,
    session,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _key(label: str) -> str:
    """A per-run idempotency key.

    Keys are globally unique by design and the local database is not reset
    between runs, so a hard-coded key would make the *second* run of a test read
    back the first run's attempt — which is the dedupe working, but not what the
    test means to assert.
    """
    return f"{label}-{uuid.uuid4().hex}"


def _succeeded_intent(intent_id: str = "pi_ok") -> FakeStripeObject:
    return FakeStripeObject(id=intent_id, status="succeeded", client_secret=f"{intent_id}_secret")


async def _save_card(
    db: object,
    *,
    workspace_id: uuid.UUID,
    contact_id: int,
    pm_id: str | None = None,
    customer_id: str = "cus_saved",
) -> ContactPaymentMethod:
    """Insert an already-saved active card, as the webhook would have.

    ``stripe_payment_method_id`` is globally unique (one Stripe handle, one row),
    so tests get a distinct id unless they need to name one.
    """
    method = ContactPaymentMethod(
        workspace_id=workspace_id,
        contact_id=contact_id,
        stripe_payment_method_id=pm_id or f"pm_{uuid.uuid4().hex[:16]}",
        stripe_customer_id=customer_id,
        brand="visa",
        last4="4242",
        exp_month=12,
        exp_year=2032,
        is_default=True,
        status="active",
        mandate_text_version=card_on_file_service.CARD_ON_FILE_MANDATE_VERSION,
    )
    db.add(method)  # type: ignore[attr-defined]
    await db.commit()  # type: ignore[attr-defined]
    return method


async def _tag_no_automation(db: object, workspace_id: uuid.UUID, contact_id: int) -> None:
    tag = Tag(workspace_id=workspace_id, name=NO_AUTOMATION_TAG)
    db.add(tag)  # type: ignore[attr-defined]
    await db.flush()  # type: ignore[attr-defined]
    db.add(ContactTag(contact_id=contact_id, tag_id=tag.id))  # type: ignore[attr-defined]
    await db.commit()  # type: ignore[attr-defined]


async def test_successful_charge_records_payment_through_invoice_service(
    fake_stripe: FakeStripeClient,
) -> None:
    """A successful charge lands on the invoice via the normal payment path.

    Deliberately routed through ``InvoiceService.record_payment`` rather than
    poking ``amount_paid``: that is what derives status, fires ``invoice.paid``,
    and dedupes on the payment-intent id.
    """
    fake_stripe.payment_intents.responses["create"] = _succeeded_intent("pi_invoice_paid")

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
                line_items=[InvoiceLineItemCreate(name="Gutter clean", unit_price=180.0)],
            ),
        )
        await svc.mark_sent(ws.id, created.id)

        key = _key("charge-invoice")
        result = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=180.0,
            currency="USD",
            description=f"Invoice {created.number}",
            trigger="invoice",
            idempotency_key=key,
            automated=False,
            invoice_id=created.id,
        )
        assert result.succeeded
        assert result.payment_intent_id == "pi_invoice_paid"

        from app.models.invoice import Invoice

        invoice = await db.get(Invoice, created.id)
        assert invoice is not None
        await svc.record_payment(invoice, result.amount, payment_intent_id=result.payment_intent_id)
        assert invoice.status == "paid"
        assert float(invoice.amount_paid) == 180.0
        assert invoice.paid_at is not None

        # The attempt row is the audit trail for the money that moved.
        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.contact_id == contact.id)
        )
        attempts = rows.scalars().all()
        assert len(attempts) == 1
        assert attempts[0].status == "succeeded"
        assert attempts[0].trigger == "invoice"
        assert attempts[0].invoice_id == created.id

    # Stripe was asked for exactly one PaymentIntent, off-session and confirmed.
    params = [c for name, c in fake_stripe.calls if name == "payment_intents.create"][0]
    assert params["kwargs"]["params"]["off_session"] is True
    assert params["kwargs"]["params"]["confirm"] is True
    assert params["kwargs"]["params"]["amount"] == 18000
    assert params["kwargs"]["options"]["idempotency_key"] == key


async def test_same_idempotency_key_charges_once(fake_stripe: FakeStripeClient) -> None:
    """A double-clicked button (or a retried tick) must charge exactly once."""
    fake_stripe.payment_intents.responses["create"] = _succeeded_intent("pi_dedupe")

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        key = _key("dedupe")
        kwargs = {
            "workspace_id": ws.id,
            "contact_id": contact.id,
            "amount": 75.0,
            "currency": "USD",
            "description": "Deposit",
            "trigger": "deposit",
            "idempotency_key": key,
            "automated": False,
        }
        first = await card_on_file_service.charge_saved_card(db, **kwargs)
        second = await card_on_file_service.charge_saved_card(db, **kwargs)

        assert first.succeeded and second.succeeded
        assert first.attempt_id == second.attempt_id

        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.idempotency_key == key)
        )
        assert len(rows.scalars().all()) == 1

    # The second call short-circuited before Stripe: one PaymentIntent, not two.
    assert fake_stripe.actions().count("payment_intents.create") == 1


async def test_no_card_on_file_returns_a_typed_result_not_an_exception(
    fake_stripe: FakeStripeClient,
) -> None:
    """A worker iterating customers must not have its loop broken by one gap."""
    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()

        result = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=50.0,
            currency="USD",
            description="Recurring visit",
            trigger="recurring_job",
            idempotency_key=_key("no-card"),
            automated=True,
        )

        assert result.status == "no_card_on_file"
        assert result.attempt_id is None
        assert fake_stripe.calls == []

        # Nothing was attempted, so nothing is recorded as an attempt.
        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.contact_id == contact.id)
        )
        assert rows.scalars().all() == []


async def test_workspace_a_cannot_charge_workspace_b_saved_card(
    fake_stripe: FakeStripeClient,
) -> None:
    """Cross-tenant isolation: another workspace's card is not even visible."""
    fake_stripe.payment_intents.responses["create"] = _succeeded_intent("pi_should_not_happen")

    async with session() as db:
        ws_a = await make_workspace(db, "Alpha")
        ws_b = await make_workspace(db, "Beta")
        contact_b = await make_contact(db, ws_b.id)
        await db.commit()
        card_b = await _save_card(db, workspace_id=ws_b.id, contact_id=contact_b.id)

        # By default card lookup: workspace A sees no card for B's contact.
        blind = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws_a.id,
            contact_id=contact_b.id,
            amount=99.0,
            currency="USD",
            description="Cross-tenant probe",
            trigger="manual",
            idempotency_key=_key("cross-tenant-default"),
            automated=False,
        )
        assert blind.status == "no_card_on_file"

        # Naming the card explicitly 404s rather than leaking its existence.
        from app.services.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await card_on_file_service.charge_saved_card(
                db,
                workspace_id=ws_a.id,
                contact_id=contact_b.id,
                amount=99.0,
                currency="USD",
                description="Cross-tenant probe",
                trigger="manual",
                idempotency_key=_key("cross-tenant-explicit"),
                automated=False,
                payment_method_id=card_b.id,
            )

    assert fake_stripe.calls == []


async def test_no_automation_tag_blocks_automated_charges_only(
    fake_stripe: FakeStripeClient,
) -> None:
    """The tag mutes automation, not the operator.

    A background job must not silently charge a customer flagged for human-only
    handling; an operator pressing the button is still allowed, which is exactly
    what the tag's documented meaning says.
    """
    fake_stripe.payment_intents.responses["create"] = _succeeded_intent("pi_manual_allowed")

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)
        await _tag_no_automation(db, ws.id, contact.id)

        automated = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=120.0,
            currency="USD",
            description="Recurring visit",
            trigger="recurring_job",
            idempotency_key=_key("no-automation-auto"),
            automated=True,
        )
        assert automated.status == "skipped_no_automation"
        assert fake_stripe.calls == []

        manual = await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=120.0,
            currency="USD",
            description="Balance owed",
            trigger="manual",
            idempotency_key=_key("no-automation-manual"),
            automated=False,
        )
        assert manual.succeeded

        rows = await db.execute(
            select(CardChargeAttempt).where(CardChargeAttempt.contact_id == contact.id)
        )
        attempts = rows.scalars().all()
        # Only the manual charge was ever attempted.
        assert len(attempts) == 1
        assert attempts[0].trigger == "manual"


async def test_zero_decimal_currency_is_not_multiplied(fake_stripe: FakeStripeClient) -> None:
    """JPY has no minor unit; scaling it by 100 would be a 100x overcharge."""
    fake_stripe.payment_intents.responses["create"] = _succeeded_intent("pi_jpy")

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        await _save_card(db, workspace_id=ws.id, contact_id=contact.id)

        await card_on_file_service.charge_saved_card(
            db,
            workspace_id=ws.id,
            contact_id=contact.id,
            amount=5000,
            currency="JPY",
            description="Zero-decimal charge",
            trigger="manual",
            idempotency_key=_key("jpy"),
            automated=False,
        )

    params = [c for name, c in fake_stripe.calls if name == "payment_intents.create"][0]
    assert params["kwargs"]["params"]["amount"] == 5000


async def test_removing_the_default_card_promotes_the_next_one(
    fake_stripe: FakeStripeClient,
) -> None:
    """Removing a default must not leave a contact showing cards it cannot charge."""
    fake_stripe.payment_methods.responses["detach"] = FakeStripeObject(id="pm_detached")

    async with session() as db:
        ws = await make_workspace(db)
        contact = await make_contact(db, ws.id)
        await db.commit()
        first = await _save_card(
            db, workspace_id=ws.id, contact_id=contact.id, pm_id=f"pm_one_{uuid.uuid4().hex[:12]}"
        )

        second = ContactPaymentMethod(
            workspace_id=ws.id,
            contact_id=contact.id,
            stripe_payment_method_id=f"pm_two_{uuid.uuid4().hex[:12]}",
            stripe_customer_id="cus_saved",
            brand="mastercard",
            last4="4444",
            is_default=False,
            status="active",
            mandate_text_version=card_on_file_service.CARD_ON_FILE_MANDATE_VERSION,
        )
        db.add(second)
        await db.commit()

        await card_on_file_service.remove_payment_method(
            db, workspace_id=ws.id, contact_id=contact.id, payment_method_id=first.id
        )

        remaining = await card_on_file_service.list_payment_methods(
            db, workspace_id=ws.id, contact_id=contact.id
        )
        assert [m.id for m in remaining] == [second.id]
        assert remaining[0].is_default is True

        default = await card_on_file_service.get_default_payment_method(
            db, workspace_id=ws.id, contact_id=contact.id
        )
        assert default is not None and default.id == second.id
