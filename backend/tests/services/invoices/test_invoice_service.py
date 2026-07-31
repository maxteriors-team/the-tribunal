"""Real-DB integration tests for :class:`InvoiceService`.

These hit Postgres (encrypted columns, the per-workspace number sequence, derived
status, and idempotent payment reconciliation all behave differently under a real
engine than under mocks), so they are marked ``integration`` and deselected by
default. Run with ``pytest -m integration``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.workspace import Workspace
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoiceUpdate,
)
from app.services.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.services.invoices import InvoiceService
from app.services.invoices.invoice_service import handle_invoice_checkout_session_completed
from app.services.payments import call_payment_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    """Dispose the shared asyncpg pool around each test.

    pytest-asyncio gives each test a fresh event loop; without disposing, the
    engine's pool can hold connections bound to a closed loop and surface as
    ``Event loop is closed`` when integration tests run back-to-back.
    """
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_workspace(db: AsyncSession) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Invoices Co", slug=f"inv-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _make_contact(
    db: AsyncSession, workspace_id: uuid.UUID, *, email: str | None = None
) -> Contact:
    phone = f"+1555{uuid.uuid4().int % 10_000_000:07d}"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Pat",
        phone_number=phone,
        phone_hash=hash_phone(phone),
        email=email,
        email_hash=hash_value(email) if email else None,
    )
    db.add(contact)
    await db.flush()
    return contact


async def test_create_computes_totals_and_allocates_number() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        svc = InvoiceService(db)

        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                tax_amount=10.0,
                discount_amount=5.0,
                line_items=[
                    InvoiceLineItemCreate(name="Labor", quantity=2, unit_price=100.0),
                    InvoiceLineItemCreate(name="Parts", quantity=1, unit_price=50.0, discount=5.0),
                ],
            ),
            created_by_id=None,
        )

        # subtotal = (2*100) + (1*50 - 5) = 200 + 45 = 245; total = 245 + 10 - 5 = 250
        assert created.subtotal == 245.0
        assert created.total == 250.0
        assert created.amount_paid == 0.0
        assert created.status == "draft"
        assert created.contact_id == contact.id
        assert len(created.line_items) == 2

        # First invoice in the workspace gets sequence 1, zero-padded.
        assert created.number == "INV-000001"

        # Second invoice increments the per-workspace sequence.
        second = await svc.create_invoice(ws.id, InvoiceCreate(line_items=[]), created_by_id=None)
        assert second.number == "INV-000002"


async def test_number_sequence_is_per_workspace() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        svc = InvoiceService(db)

        a1 = await svc.create_invoice(ws_a.id, InvoiceCreate(line_items=[]))
        b1 = await svc.create_invoice(ws_b.id, InvoiceCreate(line_items=[]))

        # Each workspace numbers independently from 1.
        assert a1.number == "INV-000001"
        assert b1.number == "INV-000001"


async def test_line_item_edits_recompute_totals() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)

        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Base", unit_price=100.0)]),
        )
        assert inv.total == 100.0

        # Add a line item -> totals grow.
        inv = await svc.add_line_item(
            ws.id, inv.id, InvoiceLineItemCreate(name="Extra", quantity=3, unit_price=10.0)
        )
        assert inv.subtotal == 130.0
        assert inv.total == 130.0

        # Update the extra line -> recompute.
        extra = next(li for li in inv.line_items if li.name == "Extra")
        inv = await svc.update_line_item(ws.id, inv.id, extra.id, InvoiceLineItemUpdate(quantity=5))
        assert next(li for li in inv.line_items if li.name == "Extra").total == 50.0
        assert inv.total == 150.0

        # Remove the base line -> recompute.
        base = next(li for li in inv.line_items if li.name == "Base")
        inv = await svc.remove_line_item(ws.id, inv.id, base.id)
        assert len(inv.line_items) == 1
        assert inv.total == 50.0


async def test_send_then_full_payment_transitions_to_paid() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=300.0)]),
        )

        sent = await svc.mark_sent(ws.id, inv.id)
        assert sent.status == "sent"
        assert sent.sent_at is not None

        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        recorded = await svc.record_payment(invoice_row, 300.0, payment_intent_id="pi_full")
        assert recorded is True
        assert invoice_row.status == "paid"
        assert invoice_row.paid_at is not None
        assert float(invoice_row.amount_paid) == 300.0


async def test_partial_payment_then_idempotent_replay() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=200.0)]),
        )
        await svc.mark_sent(ws.id, inv.id)

        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None

        # Partial payment -> status partial, no paid_at.
        assert await svc.record_payment(invoice_row, 50.0, payment_intent_id="pi_part") is True
        assert invoice_row.status == "partial"
        assert invoice_row.paid_at is None
        assert float(invoice_row.amount_paid) == 50.0

        # Remaining balance -> paid.
        assert await svc.record_payment(invoice_row, 150.0, payment_intent_id="pi_final") is True
        assert invoice_row.status == "paid"
        assert float(invoice_row.amount_paid) == 200.0

        # Webhook replay of the same final intent must be a no-op (idempotent).
        assert await svc.record_payment(invoice_row, 150.0, payment_intent_id="pi_final") is False
        assert float(invoice_row.amount_paid) == 200.0


async def test_overdue_is_derived_from_due_date() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        yesterday = date.today() - timedelta(days=1)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                due_date=yesterday,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )

        # A draft past its due date is not overdue until it has been sent.
        assert inv.status == "draft"
        sent = await svc.mark_sent(ws.id, inv.id)
        assert sent.status == "overdue"


async def test_void_and_delete_rules() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)

        # A draft can be hard-deleted.
        draft = await svc.create_invoice(ws.id, InvoiceCreate(line_items=[]))
        await svc.delete_invoice(ws.id, draft.id)
        # get_or_404 raises FastAPI's HTTPException(404), the repo-wide convention.
        with pytest.raises(HTTPException):
            await svc.get_invoice(ws.id, draft.id)

        # A sent invoice cannot be deleted; it must be voided.
        issued = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=10.0)])
        )
        await svc.mark_sent(ws.id, issued.id)
        with pytest.raises(ConflictError):
            await svc.delete_invoice(ws.id, issued.id)

        voided = await svc.void_invoice(ws.id, issued.id)
        assert voided.status == "void"

        # Voided invoices reject line-item edits and header edits.
        with pytest.raises(ConflictError):
            await svc.add_line_item(
                ws.id, issued.id, InvoiceLineItemCreate(name="x", unit_price=1.0)
            )
        with pytest.raises(ConflictError):
            await svc.update_invoice(ws.id, issued.id, InvoiceUpdate(notes="late"))


async def test_paid_invoice_cannot_be_voided_or_edited() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)])
        )
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        await svc.record_payment(invoice_row, 100.0, payment_intent_id="pi_x")
        assert invoice_row.status == "paid"

        with pytest.raises(ConflictError):
            await svc.void_invoice(ws.id, inv.id)
        with pytest.raises(ConflictError):
            await svc.add_line_item(
                ws.id, inv.id, InvoiceLineItemCreate(name="late", unit_price=1.0)
            )


async def test_list_is_workspace_scoped_and_filterable() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        svc = InvoiceService(db)

        a1 = await svc.create_invoice(
            ws_a.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="J", unit_price=10.0)])
        )
        await svc.create_invoice(ws_a.id, InvoiceCreate(line_items=[]))
        await svc.create_invoice(ws_b.id, InvoiceCreate(line_items=[]))

        # Only workspace A's invoices are listed for workspace A.
        listed_a = await svc.list_invoices(ws_a.id)
        assert listed_a.total == 2
        assert {i.workspace_id for i in listed_a.items} == {ws_a.id}

        # Status filter narrows results.
        await svc.mark_sent(ws_a.id, a1.id)
        sent_only = await svc.list_invoices(ws_a.id, status="sent")
        assert sent_only.total == 1
        assert sent_only.items[0].id == a1.id

        # Cross-workspace fetch is a 404, never a leak.
        with pytest.raises(HTTPException):
            await svc.get_invoice(ws_b.id, a1.id)


async def test_updated_tax_rederives_paid_state() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)])
        )
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        await svc.record_payment(invoice_row, 100.0, payment_intent_id="pi_t")
        assert invoice_row.status == "paid"

        # Raising tax makes the balance outstanding again -> partial.
        updated = await svc.update_invoice(ws.id, inv.id, InvoiceUpdate(tax_amount=20.0))
        assert updated.total == 120.0
        assert updated.amount_paid == 100.0
        assert updated.status == "partial"


async def test_payment_link_requires_stripe_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With Stripe unconfigured the guard must fire (503) instead of calling out.

    Stripe state is pinned rather than inherited: a developer with a real
    ``STRIPE_SECRET_KEY`` in ``backend/.env`` would otherwise sail past the guard
    and have this test open a **live** Checkout Session against their account.
    Same convention as ``tests/services/quotes/test_quote_deposit.py``.
    """
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: False)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)])
        )
        with pytest.raises(ServiceUnavailableError):
            await svc.create_payment_link(ws.id, inv.id)


async def test_webhook_records_payment_and_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=300.0)])
        )
        await svc.mark_sent(ws.id, inv.id)

        # Stripe sends amount in minor units; 30000 -> $300.00.
        session = {
            "id": "cs_test_inv",
            "mode": "payment",
            "payment_intent": "pi_inv_1",
            "amount_total": 30000,
            "metadata": {"invoice_id": str(inv.id), "workspace_id": str(ws.id)},
        }
        await handle_invoice_checkout_session_completed(session, db)

        paid = await svc.get_invoice(ws.id, inv.id)
        assert paid.status == "paid"
        assert paid.amount_paid == 300.0
        assert paid.paid_at is not None

        # A Stripe retry of the same event must not double-count.
        await handle_invoice_checkout_session_completed(session, db)
        replayed = await svc.get_invoice(ws.id, inv.id)
        assert replayed.amount_paid == 300.0


async def test_webhook_matches_by_session_id_when_metadata_absent() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=80.0)])
        )
        # Simulate the link having been created: only the session id is stored.
        # Use a unique id per run so leftover rows from prior integration runs
        # (these tests commit against the shared dev DB) can't make the
        # session-id lookup match multiple invoices.
        session_id = f"cs_fallback_{uuid.uuid4().hex}"
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        invoice_row.stripe_checkout_session_id = session_id
        await db.commit()

        session = {
            "id": session_id,
            "mode": "payment",
            "payment_intent": "pi_fallback",
            "amount_total": 8000,
            "metadata": {},  # no invoice_id -> must resolve via session id
        }
        await handle_invoice_checkout_session_completed(session, db)

        paid = await svc.get_invoice(ws.id, inv.id)
        assert paid.status == "paid"
        assert paid.amount_paid == 80.0


async def test_webhook_no_match_is_noop() -> None:
    async with AsyncSessionLocal() as db:
        # Unknown invoice id and unknown session id: handler must log + return,
        # never raise (Stripe would otherwise retry forever).
        session = {
            "id": "cs_unknown",
            "mode": "payment",
            "payment_intent": "pi_unknown",
            "amount_total": 1000,
            "metadata": {"invoice_id": str(uuid.uuid4())},
        }
        await handle_invoice_checkout_session_completed(session, db)


async def test_mark_sent_emails_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    """A sent invoice emails the bill-to contact and reports the delivery."""
    import app.services.email as email_mod

    # Pinned, not inherited: with a real key in ``backend/.env`` this test would
    # otherwise open a live Stripe Checkout Session just to build the pay link.
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: False)

    sent_calls: list[dict[str, object]] = []

    async def _fake_send(**kwargs: object) -> bool:
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=200.0)],
            ),
        )
        sent = await svc.mark_sent(ws.id, inv.id)

        assert sent.status == "sent"
        assert len(sent_calls) == 1
        call = sent_calls[0]
        assert call["to_email"] == "customer@example.com"
        assert call["invoice_number"] == "INV-000001"
        assert call["amount_str"] == "200.00 USD"
        # The customer really was emailed, and the caller is told so.
        assert sent.delivery == "emailed"
        assert sent.delivered_to == "customer@example.com"
        # The link is the customer's own invoice page (asserted in detail by
        # ``test_sent_invoice_emails_a_stable_page_link_not_a_stripe_session``).
        assert "/p/invoices/" in str(call["pay_url"])


async def test_public_pay_action_opens_a_checkout_for_the_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The billing path that matters: the customer's "Pay now" reaches Stripe.

    Checkout is created when the customer actually presses pay -- not at send
    time -- so the session cannot expire before they open the email. Stripe is
    faked (never called for real) so this stays hermetic.
    """
    import app.services.email as email_mod
    from app.services.payments.call_payment_service import CheckoutSessionResult

    charged: list[float] = []

    async def _fake_send(**kwargs: object) -> bool:
        return True

    async def _fake_session(**kwargs: object) -> CheckoutSessionResult:
        charged.append(float(kwargs["amount"]))  # type: ignore[arg-type]
        # ``payment_intent_id`` stays None: the service deliberately leaves the
        # intent unset until the webhook records the payment (pre-storing it
        # would make ``record_payment`` a no-op on the completion callback).
        return CheckoutSessionResult(
            session_id="cs_fake_123",
            url="https://pay.example/cs_fake",
            payment_intent_id=None,
        )

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "create_payment_checkout_session", _fake_session)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="payer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=200.0)],
            ),
            # A deposit already collected on the quote.
            amount_paid=50.0,
        )
        sent = await svc.mark_sent(ws.id, inv.id)
        assert sent.delivery == "emailed"

        stored = await db.get(Invoice, inv.id)
        assert stored is not None
        assert stored.public_token is not None
        # No Stripe session exists yet -- nothing was charged at send time.
        assert charged == []

        checkout = await svc.create_public_payment_checkout(stored.public_token)
        assert checkout.url == "https://pay.example/cs_fake"
        # Charged the *remaining* balance, not the full total.
        assert charged == [150.0]
        assert checkout.amount == 150.0

        # The checkout session id is persisted so the completion webhook can
        # resolve this invoice from Stripe's callback.
        await db.refresh(stored)
        assert stored.stripe_checkout_session_id == "cs_fake_123"


async def test_mark_sent_without_contact_email_skips_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.email as email_mod

    sent_calls: list[dict[str, object]] = []

    async def _fake_send(**kwargs: object) -> bool:
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email=None)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=50.0)],
            ),
        )
        sent = await svc.mark_sent(ws.id, inv.id)

        # Transition still succeeds; no email attempted without a recipient.
        assert sent.status == "sent"
        assert sent_calls == []
        # ...and the caller is told the customer got nothing, so the UI cannot
        # report a delivery that never happened.
        assert sent.delivery == "skipped_no_email"
        assert sent.delivered_to is None


async def test_mark_sent_email_failure_does_not_break_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.email as email_mod

    # Pinned off for the same reason as the sibling send tests: otherwise
    # building the pay link opens a live Stripe Checkout Session on any machine
    # with a real key in ``backend/.env``.
    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: False)

    async def _boom(**kwargs: object) -> bool:
        raise RuntimeError("resend down")

    monkeypatch.setattr(email_mod, "send_invoice_email", _boom)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=10.0)],
            ),
        )
        # A delivery failure must not undo the sent transition.
        sent = await svc.mark_sent(ws.id, inv.id)
        assert sent.status == "sent"
        # But it is reported rather than swallowed.
        assert sent.delivery == "failed"
        assert sent.delivered_to is None


async def test_mark_sent_reports_no_email_when_invoice_has_no_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression that made invoices vanish: no bill-to contact at all.

    An invoice created without a contact still transitions to ``sent`` but is
    delivered to nobody, so the send has to report ``skipped_no_email``.
    """
    import app.services.email as email_mod

    sent_calls: list[dict[str, object]] = []

    async def _fake_send(**kwargs: object) -> bool:
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=75.0)],
            ),
        )
        assert inv.contact_id is None

        sent = await svc.mark_sent(ws.id, inv.id)
        assert sent.status == "sent"
        assert sent_calls == []
        assert sent.delivery == "skipped_no_email"


async def test_create_invoice_opening_credit_is_clamped_to_total() -> None:
    """A deposit larger than the invoice can never bank a negative balance."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
            amount_paid=250.0,
        )
        assert float(inv.total) == 100.0
        assert float(inv.amount_paid) == 100.0
        assert inv.status == "paid"


# --------------------------------------------------------------------------- #
# Public customer invoice page
# --------------------------------------------------------------------------- #
async def test_public_invoice_is_unreachable_until_the_invoice_is_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A draft has no token, so a customer link cannot resolve to work-in-progress."""
    import app.services.email as email_mod

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: False)

    async def _fake_send(**kwargs: object) -> bool:
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=400.0)],
            ),
        )
        # Draft: no token allocated at all.
        draft = await db.get(Invoice, inv.id)
        assert draft is not None
        assert draft.public_token is None

        await svc.mark_sent(ws.id, inv.id)
        await db.refresh(draft)
        token = draft.public_token
        assert token

        public = await svc.get_public_invoice(token)
        assert public.number == inv.number
        assert public.total == 400.0

        with pytest.raises(NotFoundError):
            await svc.get_public_invoice("not-a-real-token")


async def test_public_invoice_shows_the_deposit_credit_and_remaining_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole chain, from the customer's side.

    Quote deposit -> converted invoice -> what the customer actually sees. The
    page must show the full total, the deposit already credited, and only the
    remainder as due -- otherwise the customer is asked to pay twice.
    """
    import app.services.email as email_mod

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: False)

    async def _fake_send(**kwargs: object) -> bool:
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Wash", unit_price=2000.0)],
            ),
            # As convert_quote does when a deposit was already collected.
            amount_paid=500.0,
        )
        await svc.mark_sent(ws.id, inv.id)
        stored = await db.get(Invoice, inv.id)
        assert stored is not None
        assert stored.public_token is not None

        public = await svc.get_public_invoice(stored.public_token)
        assert public.total == 2000.0
        assert public.amount_paid == 500.0
        assert public.balance_due == 1500.0
        assert public.is_paid is False
        # Stripe is off in this test, so nothing offers a dead "Pay" button.
        assert public.is_payable is False


async def test_public_invoice_never_exposes_internal_fields() -> None:
    """The public projection is an allowlist, not a filtered model dump."""
    from app.schemas.invoice import PublicInvoice

    leaky = {
        "workspace_id",
        "contact_id",
        "opportunity_id",
        "created_by_id",
        "stripe_checkout_session_id",
        "stripe_payment_intent_id",
        "external_source",
        "external_id",
    }
    assert leaky.isdisjoint(PublicInvoice.model_fields.keys())


async def test_sent_invoice_emails_a_stable_page_link_not_a_stripe_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The emailed link must survive re-sends and Stripe session expiry."""
    import app.services.email as email_mod
    from app.core.config import settings

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)

    sent_calls: list[dict[str, object]] = []

    async def _fake_send(**kwargs: object) -> bool:
        sent_calls.append(kwargs)
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_send)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=300.0)],
            ),
        )
        await svc.mark_sent(ws.id, inv.id)
        stored = await db.get(Invoice, inv.id)
        assert stored is not None
        token = stored.public_token
        assert token

        pay_url = sent_calls[0]["pay_url"]
        assert pay_url == f"{settings.frontend_url}/p/invoices/{token}"
        # Emphatically not a Stripe Checkout URL: those expire.
        assert "checkout.stripe.com" not in str(pay_url)

        # Re-sending a reminder keeps the same link alive.
        await svc.mark_sent(ws.id, inv.id)
        await db.refresh(stored)
        assert stored.public_token == token
        assert sent_calls[1]["pay_url"] == pay_url


# --------------------------------------------------------------------------- #
# Editing an existing invoice
# --------------------------------------------------------------------------- #
async def test_update_replaces_line_items_atomically_and_rederives_totals() -> None:
    """A whole-set line-item edit lands in one transaction.

    The operator corrects a mis-billed invoice: one line edited, one dropped, one
    added. The totals must reflect exactly the submitted set -- no leftovers from
    the previous version.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                line_items=[
                    InvoiceLineItemCreate(name="Wash", quantity=1, unit_price=100.0),
                    InvoiceLineItemCreate(name="Typo line", quantity=1, unit_price=999.0),
                ],
            ),
        )
        assert float(inv.total) == 1099.0

        updated = await svc.update_invoice(
            ws.id,
            inv.id,
            InvoiceUpdate(
                line_items=[
                    InvoiceLineItemCreate(name="Wash", quantity=2, unit_price=100.0),
                    InvoiceLineItemCreate(name="Gutter clear", quantity=1, unit_price=50.0),
                ],
            ),
        )

        assert len(updated.line_items) == 2
        assert {li.name for li in updated.line_items} == {"Wash", "Gutter clear"}
        assert float(updated.total) == 250.0
        # The dropped row is really gone, not orphaned.
        remaining = (
            (await db.execute(select(InvoiceLineItem).where(InvoiceLineItem.invoice_id == inv.id)))
            .scalars()
            .all()
        )
        assert len(remaining) == 2


async def test_editing_a_sent_invoice_keeps_the_customers_link_working() -> None:
    """A change order must not orphan the link the customer already has.

    Editing re-prices the invoice; the token stays the same so the email the
    customer received still opens the (now corrected) invoice.
    """
    import app.services.email as email_mod

    async def _fake_send(**kwargs: object) -> bool:
        return True

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        original_send = email_mod.send_invoice_email
        email_mod.send_invoice_email = _fake_send  # type: ignore[assignment]
        try:
            inv = await svc.create_invoice(
                ws.id,
                InvoiceCreate(
                    contact_id=contact.id,
                    line_items=[InvoiceLineItemCreate(name="Wash", unit_price=100.0)],
                ),
            )
            await svc.mark_sent(ws.id, inv.id)
        finally:
            email_mod.send_invoice_email = original_send  # type: ignore[assignment]

        stored = await db.get(Invoice, inv.id)
        assert stored is not None
        token = stored.public_token
        assert token

        # Change order: the crew also cleared the gutters.
        await svc.update_invoice(
            ws.id,
            inv.id,
            InvoiceUpdate(
                line_items=[
                    InvoiceLineItemCreate(name="Wash", unit_price=100.0),
                    InvoiceLineItemCreate(name="Gutter clear", unit_price=50.0),
                ],
            ),
        )

        await db.refresh(stored)
        assert stored.public_token == token
        public = await svc.get_public_invoice(token)
        assert public.total == 150.0
        assert public.balance_due == 150.0


async def test_a_settled_invoice_is_history_not_a_draft() -> None:
    """Paid invoices reject line-item edits through the bulk path too.

    The per-item endpoints already guard this; the bulk replace has to enforce
    the same rule or it becomes a way around it.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)]),
            amount_paid=100.0,
        )
        assert inv.status == "paid"

        with pytest.raises(ConflictError):
            await svc.update_invoice(
                ws.id,
                inv.id,
                InvoiceUpdate(line_items=[InvoiceLineItemCreate(name="Sneaky", unit_price=5000.0)]),
            )

        # Header fields stay editable, so a note can still be added.
        updated = await svc.update_invoice(
            ws.id, inv.id, InvoiceUpdate(notes="Paid in cash on site.")
        )
        assert updated.notes == "Paid in cash on site."
        assert float(updated.total) == 100.0
