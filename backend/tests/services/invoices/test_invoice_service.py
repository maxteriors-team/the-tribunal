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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.invoice import Invoice
from app.models.workspace import Workspace
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoiceUpdate,
)
from app.services.exceptions import ConflictError, ServiceUnavailableError
from app.services.invoices import InvoiceService
from app.services.invoices.invoice_service import handle_invoice_checkout_session_completed

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


async def test_payment_link_requires_stripe_configured() -> None:
    # Stripe is not configured in the test env, so the guard must fire (503 path)
    # rather than attempting a live Checkout Session call.
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
    import app.services.email as email_mod

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
        # Stripe is unconfigured in tests, so no pay link is attached.
        assert call["pay_url"] is None


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


async def test_mark_sent_email_failure_does_not_break_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.email as email_mod

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
