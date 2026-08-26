"""Real-DB integration tests for :class:`InvoiceService`.

These hit Postgres (encrypted columns, the per-workspace number sequence, derived
status, and idempotent payment reconciliation all behave differently under a real
engine than under mocks), so they are marked ``integration`` and deselected by
default. Run with ``pytest -m integration``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_phone, hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.invoice import Invoice, InvoiceLineItem
from app.models.invoice_payment import InvoicePayment
from app.models.invoice_payment_receipt_outbox import (
    RECEIPT_PENDING,
    RECEIPT_TERMINAL,
    InvoicePaymentReceiptOutbox,
)
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoiceManualPaymentCreate,
    InvoiceUpdate,
)
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.services.invoices import InvoiceService
from app.services.invoices.invoice_service import handle_invoice_checkout_session_completed
from app.services.payments import call_payment_service

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


def _stripe_id(label: str) -> str:
    """Return a provider id unique across persistent local test runs."""
    return f"{label}_{uuid.uuid4().hex}"


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


async def _make_user(db: AsyncSession) -> User:
    email = f"operator-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name="Payment Recorder",
    )
    db.add(user)
    await db.flush()
    return user


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
        recorded = await svc.record_payment(
            invoice_row, 300.0, payment_intent_id=_stripe_id("pi_full")
        )
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

        partial_payment_id = _stripe_id("pi_part")
        final_payment_id = _stripe_id("pi_final")

        # Partial payment -> status partial, no paid_at.
        assert (
            await svc.record_payment(invoice_row, 50.0, payment_intent_id=partial_payment_id)
            is True
        )
        assert invoice_row.status == "partial"
        assert invoice_row.paid_at is None
        assert float(invoice_row.amount_paid) == 50.0

        # Remaining balance -> paid.
        assert (
            await svc.record_payment(invoice_row, 150.0, payment_intent_id=final_payment_id) is True
        )
        assert invoice_row.status == "paid"
        assert float(invoice_row.amount_paid) == 200.0

        # Webhook replay of the same final intent must be a no-op (idempotent).
        assert (
            await svc.record_payment(invoice_row, 150.0, payment_intent_id=final_payment_id)
            is False
        )
        assert float(invoice_row.amount_paid) == 200.0


async def test_full_payment_enqueues_one_branded_customer_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.email as email_mod

    receipt_calls: list[dict[str, object]] = []

    async def _fake_invoice_send(**kwargs: object) -> bool:
        return True

    async def _fake_receipt_send(**kwargs: object) -> bool:
        receipt_calls.append(kwargs)
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_invoice_send)
    monkeypatch.setattr(
        email_mod,
        "send_invoice_payment_receipt",
        _fake_receipt_send,
    )

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        ws.settings = {
            "proposal_template": {
                "business_name": "Patio Lights Co",
                "logo_url": "https://cdn.example.com/logo.png",
                "business_email": "office@example.com",
            }
        }
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=200.0)],
            ),
        )
        await svc.mark_sent(ws.id, inv.id)
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None

        partial_payment_id = _stripe_id("pi_part")
        final_payment_id = _stripe_id("pi_final")

        # A partial payment queues its own snapshot but never sends inline.
        assert (
            await svc.record_payment(invoice_row, 50.0, payment_intent_id=partial_payment_id)
            is True
        )
        assert receipt_calls == []

        # Crossing into paid commits a second snapshot; replay cannot add another.
        assert (
            await svc.record_payment(invoice_row, 150.0, payment_intent_id=final_payment_id) is True
        )
        assert (
            await svc.record_payment(invoice_row, 150.0, payment_intent_id=final_payment_id)
            is False
        )
        jobs = list(
            (
                await db.scalars(
                    select(InvoicePaymentReceiptOutbox).where(
                        InvoicePaymentReceiptOutbox.invoice_id == invoice_row.id
                    )
                )
            ).all()
        )
        assert len(jobs) == 2
        partial_job = next(job for job in jobs if job.payment_event_id == partial_payment_id)
        job = next(job for job in jobs if job.payment_event_id == final_payment_id)
        assert receipt_calls == []
        assert float(partial_job.payment_amount) == 50.0
        assert float(partial_job.balance_remaining or 0) == 150.0
        assert job.payment_event_id == final_payment_id
        assert job.recipient_email == "customer@example.com"
        assert job.customer_name == "Pat"
        assert job.service_summary == "Job"
        assert job.business_name == "Patio Lights Co"
        assert job.logo_url == "https://cdn.example.com/logo.png"
        assert job.support_email == "office@example.com"
        assert float(job.payment_amount) == 150.0
        assert float(job.invoice_total) == 200.0
        assert float(job.total_paid) == 200.0
        assert f"/p/invoices/{invoice_row.public_token}" in str(job.invoice_url)


async def test_receipt_retry_is_workspace_scoped() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other_ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        invoice = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
            amount_paid=100.0,
            payment_intent_id=_stripe_id("pi_scoped_receipt"),
        )

        with pytest.raises(NotFoundError):
            await svc.retry_payment_receipt(other_ws.id, invoice.id)

        jobs = (
            await db.scalars(
                select(InvoicePaymentReceiptOutbox).where(
                    InvoicePaymentReceiptOutbox.invoice_id == invoice.id
                )
            )
        ).all()
        assert len(jobs) == 1
        assert jobs[0].workspace_id == ws.id


async def test_receipt_retry_reopens_once_without_sending_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.email as email_mod

    send_calls = 0

    async def _fail_if_sent(**kwargs: object) -> bool:
        nonlocal send_calls
        send_calls += 1
        return True

    monkeypatch.setattr(email_mod, "send_invoice_payment_receipt", _fail_if_sent)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        invoice = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
            amount_paid=100.0,
            payment_intent_id=_stripe_id("pi_retry_receipt"),
        )
        job = await db.scalar(
            select(InvoicePaymentReceiptOutbox).where(
                InvoicePaymentReceiptOutbox.invoice_id == invoice.id
            )
        )
        assert job is not None
        job.status = RECEIPT_TERMINAL
        job.attempt_count = 5
        job.last_error = "provider secret detail that must never reach operators"
        job.terminal_at = datetime.now(UTC)
        await db.commit()

        failed = await svc.get_invoice(ws.id, invoice.id)
        assert failed.receipt_delivery.status == "needs_attention"
        assert failed.receipt_delivery.reason == (
            "Receipt delivery failed after multiple attempts. Retry the receipt."
        )
        assert "provider secret" not in (failed.receipt_delivery.reason or "")

        first = await svc.retry_payment_receipt(ws.id, invoice.id)
        first_next_attempt = job.next_attempt_at
        second = await svc.retry_payment_receipt(ws.id, invoice.id)

        await db.refresh(job)
        jobs = (
            await db.scalars(
                select(InvoicePaymentReceiptOutbox).where(
                    InvoicePaymentReceiptOutbox.invoice_id == invoice.id
                )
            )
        ).all()
        assert len(jobs) == 1
        assert job.status == RECEIPT_PENDING
        assert job.attempt_count == 0
        assert job.last_error is None
        assert job.next_attempt_at == first_next_attempt
        assert first.receipt_delivery.status == "pending"
        assert second.receipt_delivery.status == "pending"
        assert send_calls == 0


async def test_manual_check_payment_is_scoped_idempotent_and_queues_receipt() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        other_ws = await _make_workspace(db)
        operator = await _make_user(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Gutter cleaning", unit_price=175.0)],
            ),
        )
        request = InvoiceManualPaymentCreate(
            payment_method="check",
            amount=50,
            reference="check-1042",
            idempotency_key=uuid.uuid4(),
        )
        with pytest.raises(ValidationError, match="at least 0.01"):
            await svc.record_manual_payment(
                ws.id,
                created.id,
                InvoiceManualPaymentCreate(
                    payment_method="cash", amount=0.004, idempotency_key=uuid.uuid4()
                ),
                recorded_by_id=operator.id,
            )

        with pytest.raises(NotFoundError):
            await svc.record_manual_payment(
                other_ws.id, created.id, request, recorded_by_id=operator.id
            )

        first = await svc.record_manual_payment(
            ws.id, created.id, request, recorded_by_id=operator.id
        )
        second = await svc.record_manual_payment(
            ws.id, created.id, request, recorded_by_id=operator.id
        )
        other_invoice = await svc.create_invoice(
            other_ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Fence wash", unit_price=80.0)]),
        )
        other_result = await svc.record_manual_payment(
            other_ws.id, other_invoice.id, request, recorded_by_id=operator.id
        )
        final_request = InvoiceManualPaymentCreate(
            payment_method="cash",
            amount=125,
            reference="stale-check-reference",
            idempotency_key=uuid.uuid4(),
        )
        final = await svc.record_manual_payment(
            ws.id, created.id, final_request, recorded_by_id=operator.id
        )

        row = await db.get(Invoice, created.id)
        assert row is not None
        assert first.status == second.status == other_result.status == "partial"
        assert final.status == "paid"
        assert first.payment_method == "check"
        assert first.manual_payment_amount == 50.0
        assert first.manual_payment_reference == "check-1042"
        assert len(first.payments) == 1
        assert len(final.payments) == 2
        assert [payment.amount for payment in final.payments] == [50.0, 125.0]
        assert final.manual_payment_reference is None
        assert final.payments[1].reference is None
        assert row.payment_recorded_by_id == operator.id
        assert row.manual_payment_idempotency_key == final_request.idempotency_key
        assert row.public_token is not None
        jobs = (
            await db.scalars(
                select(InvoicePaymentReceiptOutbox).where(
                    InvoicePaymentReceiptOutbox.invoice_id == created.id
                )
            )
        ).all()
        assert len(jobs) == 2
        assert {job.payment_event_id for job in jobs} == {
            f"manual-payment:{request.idempotency_key}",
            f"manual-payment:{final_request.idempotency_key}",
        }
        assert sorted(float(job.payment_amount) for job in jobs) == [50.0, 125.0]
        assert sorted(float(job.balance_remaining or 0) for job in jobs) == [0.0, 125.0]
        ledger = (
            await db.scalars(select(InvoicePayment).where(InvoicePayment.invoice_id == created.id))
        ).all()
        assert len(ledger) == 2

        raw_reference = await db.scalar(
            text("SELECT reference FROM invoice_payments WHERE id = :payment_id"),
            {"payment_id": first.payments[0].id},
        )
        assert raw_reference is not None
        assert "check-1042" not in str(raw_reference)


async def test_manual_cash_payment_expires_open_card_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired: list[str] = []

    async def retrieve_status(_session_id: str) -> call_payment_service.SessionStatus:
        return call_payment_service.SessionStatus(
            payment_status="unpaid", status="open", payment_intent_id=None
        )

    async def expire(session_id: str) -> bool:
        expired.append(session_id)
        return True

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_session_status", retrieve_status)
    monkeypatch.setattr(call_payment_service, "expire_checkout_session_if_open", expire)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        operator = await _make_user(db)
        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Window wash", unit_price=90.0)]),
        )
        row = await db.get(Invoice, created.id)
        assert row is not None
        row.stripe_checkout_session_id = "cs_open_manual_invoice"
        await db.commit()

        result = await svc.record_manual_payment(
            ws.id,
            created.id,
            InvoiceManualPaymentCreate(
                payment_method="cash", amount=90, idempotency_key=uuid.uuid4()
            ),
            recorded_by_id=operator.id,
        )

        assert expired == ["cs_open_manual_invoice"]
        assert result.status == "paid"
        assert result.payment_method == "cash"
        assert row.stripe_checkout_session_id is None


async def test_paid_card_checkout_wins_over_manual_invoice_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_intent_id = _stripe_id("pi_card_wins")

    async def retrieve_status(_session_id: str) -> call_payment_service.SessionStatus:
        return call_payment_service.SessionStatus(
            payment_status="paid", status="complete", payment_intent_id=payment_intent_id
        )

    async def no_notification(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "retrieve_session_status", retrieve_status)
    monkeypatch.setattr(InvoiceService, "_notify_payment_received", no_notification)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        operator = await _make_user(db)
        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Roof wash", unit_price=250.0)]),
        )
        row = await db.get(Invoice, created.id)
        assert row is not None
        row.stripe_checkout_session_id = "cs_paid_before_manual"
        await db.commit()

        result = await svc.record_manual_payment(
            ws.id,
            created.id,
            InvoiceManualPaymentCreate(
                payment_method="check",
                amount=250,
                reference="check-too-late",
                idempotency_key=uuid.uuid4(),
            ),
            recorded_by_id=operator.id,
        )

        assert result.status == "paid"
        assert result.payment_method == "card"
        assert result.payment_recorded_by_id is None
        assert result.manual_payment_reference is None
        job = await db.scalar(
            select(InvoicePaymentReceiptOutbox).where(
                InvoicePaymentReceiptOutbox.invoice_id == created.id
            )
        )
        assert job is not None
        assert job.payment_event_id == payment_intent_id


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
        await svc.record_payment(invoice_row, 100.0, payment_intent_id=_stripe_id("pi_x"))
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


async def test_paid_invoice_rejects_checkout_affecting_changes() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        replacement_contact = await _make_contact(db, ws.id)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        await svc.record_payment(invoice_row, 100.0, payment_intent_id=_stripe_id("pi_t"))

        blocked_updates = [
            InvoiceUpdate(tax_amount=20.0),
            InvoiceUpdate(discount_amount=10.0),
            InvoiceUpdate(currency="EUR"),
            InvoiceUpdate(contact_id=replacement_contact.id),
            InvoiceUpdate(line_items=[InvoiceLineItemCreate(name="Changed", unit_price=100.0)]),
        ]
        for invoice_update in blocked_updates:
            with pytest.raises(ConflictError, match="paid invoice"):
                await svc.update_invoice(ws.id, inv.id, invoice_update)

        await db.refresh(invoice_row)
        assert float(invoice_row.total) == 100.0
        assert float(invoice_row.tax_amount) == 0.0
        assert float(invoice_row.discount_amount) == 0.0
        assert invoice_row.currency == "USD"
        assert invoice_row.contact_id == contact.id
        assert invoice_row.status == "paid"


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
    payment_intent_id = _stripe_id("pi_inv_1")
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id, InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=300.0)])
        )
        await svc.mark_sent(ws.id, inv.id)
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        invoice_row.stripe_checkout_session_id = "cs_test_inv"
        await db.commit()

        # Stripe sends amount in minor units; 30000 -> $300.00.
        session = {
            "id": "cs_test_inv",
            "mode": "payment",
            "payment_intent": payment_intent_id,
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
        jobs = list(
            (
                await db.scalars(
                    select(InvoicePaymentReceiptOutbox).where(
                        InvoicePaymentReceiptOutbox.invoice_id == inv.id
                    )
                )
            ).all()
        )
        assert len(jobs) == 1
        assert jobs[0].payment_event_id == payment_intent_id


async def test_receipt_survives_crash_after_payment_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing the webhook session after commit cannot lose its receipt job."""
    import app.workers.invoice_payment_receipt_worker as worker_mod

    async def _accepted(**kwargs: object) -> bool:
        return True

    monkeypatch.setattr(worker_mod, "BATCH_SIZE", 1)
    monkeypatch.setattr(worker_mod, "send_invoice_payment_receipt", _accepted)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="crash@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=125.0)],
            ),
        )
        invoice_row = await db.get(Invoice, inv.id)
        assert invoice_row is not None
        assert await svc.record_payment(
            invoice_row,
            125.0,
            payment_intent_id=_stripe_id("pi_crash_after_commit"),
        )
        invoice_id = invoice_row.id
        job = await db.scalar(
            select(InvoicePaymentReceiptOutbox).where(
                InvoicePaymentReceiptOutbox.invoice_id == invoice_id
            )
        )
        assert job is not None
        job.next_attempt_at = datetime(2000, 1, 1, tzinfo=UTC)
        job_id = job.id
        await db.commit()
    # Simulated process crash: the transaction-owning session is gone.

    async with AsyncSessionLocal() as db:
        paid_invoice = await db.get(Invoice, invoice_id)
        persisted_job = await db.get(InvoicePaymentReceiptOutbox, job_id)
        assert paid_invoice is not None and paid_invoice.status == "paid"
        assert persisted_job is not None and persisted_job.status == "pending"

    await worker_mod.InvoicePaymentReceiptWorker().process_once()

    async with AsyncSessionLocal() as db:
        delivered = await db.get(InvoicePaymentReceiptOutbox, job_id)
        assert delivered is not None
        assert delivered.status == "sent"
        assert delivered.sent_at is not None


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
            "payment_intent": _stripe_id("pi_fallback"),
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


async def test_public_optional_selection_reprices_and_charges_selected_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Required rows stay selected while optional choices drive server pricing."""
    from app.services.payments.call_payment_service import CheckoutSessionResult

    charged: list[float] = []

    async def _fake_session(**kwargs: object) -> CheckoutSessionResult:
        charged.append(float(kwargs["amount"]))  # type: ignore[arg-type]
        return CheckoutSessionResult(
            session_id="cs_selected",
            url="https://pay.example/cs_selected",
            payment_intent_id=None,
        )

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "create_payment_checkout_session", _fake_session)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        invoice = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                tax_amount=10.0,
                discount_amount=5.0,
                line_items=[
                    InvoiceLineItemCreate(name="Required", unit_price=100.0),
                    InvoiceLineItemCreate(name="Option A", unit_price=40.0, is_optional=True),
                    InvoiceLineItemCreate(name="Option B", unit_price=60.0, is_optional=True),
                ],
            ),
            amount_paid=20.0,
        )
        await svc.mark_sent(ws.id, invoice.id)
        stored = await db.get(Invoice, invoice.id)
        assert stored is not None
        assert stored.public_token is not None
        await db.refresh(stored, ["line_items"])
        required = next(item for item in stored.line_items if item.name == "Required")
        option_a = next(item for item in stored.line_items if item.name == "Option A")
        option_b = next(item for item in stored.line_items if item.name == "Option B")

        checkout = await svc.create_public_payment_checkout(stored.public_token, [option_b.id])

        # 100 required + 60 selected + 10 tax - 5 invoice discount - 20 paid.
        assert charged == [145.0]
        assert checkout.amount == 145.0
        assert float(stored.subtotal) == 160.0
        assert float(stored.total) == 165.0
        assert stored.status == "partial"
        assert required.is_selected is True
        assert option_a.is_selected is False
        assert option_b.is_selected is True


async def test_public_optional_selection_rejects_required_and_foreign_ids() -> None:
    """The public UUID list cannot remove required rows or cross invoice scope."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        invoice = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                line_items=[
                    InvoiceLineItemCreate(name="Required", unit_price=100.0),
                    InvoiceLineItemCreate(name="Optional", unit_price=25.0, is_optional=True),
                ]
            ),
        )
        foreign = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                line_items=[
                    InvoiceLineItemCreate(name="Foreign option", unit_price=50.0, is_optional=True)
                ]
            ),
        )
        await svc.mark_sent(ws.id, invoice.id)
        stored = await db.get(Invoice, invoice.id)
        foreign_stored = await db.get(Invoice, foreign.id)
        assert stored is not None
        assert stored.public_token is not None
        assert foreign_stored is not None
        await db.refresh(stored, ["line_items"])
        await db.refresh(foreign_stored, ["line_items"])
        required = next(item for item in stored.line_items if not item.is_optional)
        foreign_option = foreign_stored.line_items[0]

        with pytest.raises(ValidationError, match="must be optional items on this invoice"):
            await svc.create_public_payment_checkout(stored.public_token, [required.id])
        with pytest.raises(ValidationError, match="must be optional items on this invoice"):
            await svc.create_public_payment_checkout(stored.public_token, [foreign_option.id])

        assert required.is_selected is True
        assert float(stored.total) == 125.0


async def test_replacing_public_checkout_expires_the_previous_open_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.payments.call_payment_service import CheckoutSessionResult

    events: list[str] = []

    async def _fake_expire(session_id: str) -> bool:
        events.append(f"expire:{session_id}")
        return True

    async def _fake_session(**kwargs: object) -> CheckoutSessionResult:
        events.append(f"create:{float(kwargs['amount'])}")  # type: ignore[arg-type]
        return CheckoutSessionResult(
            session_id="cs_new", url="https://pay.example/cs_new", payment_intent_id=None
        )

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: True)
    monkeypatch.setattr(call_payment_service, "expire_checkout_session_if_open", _fake_expire)
    monkeypatch.setattr(call_payment_service, "create_payment_checkout_session", _fake_session)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        invoice = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=80.0)]),
        )
        await svc.mark_sent(ws.id, invoice.id)
        stored = await db.get(Invoice, invoice.id)
        assert stored is not None
        assert stored.public_token is not None
        stored.stripe_checkout_session_id = "cs_old"
        await db.commit()

        await svc.create_public_payment_checkout(stored.public_token, [])

        assert events == ["expire:cs_old", "create:80.0"]
        assert stored.stripe_checkout_session_id == "cs_new"


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


# --------------------------------------------------------------------------- #
# Texting an invoice
# --------------------------------------------------------------------------- #
async def test_texting_an_invoice_sends_the_link_and_the_balance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A texted invoice carries the amount owed and the stable page link."""
    from app.core.config import settings

    sent: list[dict[str, object]] = []

    async def _fake_sms(db: object, workspace_id: object, **kwargs: object) -> None:
        sent.append(kwargs)

    monkeypatch.setattr("app.services.messaging.client_sms.send_client_link_sms", _fake_sms)
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        contact.first_name = "Dana"
        await db.commit()

        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Wash", unit_price=2000.0)],
            ),
            amount_paid=500.0,
        )

        result = await svc.deliver_invoice(ws.id, inv.id, channel="sms")

        assert result.ok is True
        assert result.channel == "sms"
        assert len(sent) == 1
        body = str(sent[0]["body"])
        # The remaining balance, not the full total -- the deposit is credited.
        assert "1,500.00 USD" in body
        assert "2,000.00" not in body
        assert "Hi Dana," in body

        stored = await db.get(Invoice, inv.id)
        assert stored is not None
        assert stored.public_token is not None
        assert f"{settings.frontend_url.rstrip('/')}/p/invoices/{stored.public_token}" in body
        # Texting transitions the invoice exactly like emailing does.
        assert stored.status == "partial"
        assert stored.sent_at is not None


async def test_texting_an_invoice_does_not_also_email_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Choosing SMS must not fire the email rail as a side effect."""
    import app.services.email as email_mod

    emails: list[dict[str, object]] = []

    async def _fake_email(**kwargs: object) -> bool:
        emails.append(kwargs)
        return True

    async def _fake_sms(db: object, workspace_id: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_email)
    monkeypatch.setattr("app.services.messaging.client_sms.send_client_link_sms", _fake_sms)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="customer@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )

        await svc.deliver_invoice(ws.id, inv.id, channel="sms")
        assert emails == []


async def test_texting_without_a_phone_number_names_the_fix() -> None:
    """A refusal an operator can act on, not a generic failure."""
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)]),
        )

        with pytest.raises(ValidationError, match="No phone number"):
            await svc.deliver_invoice(ws.id, inv.id, channel="sms")


async def test_accepted_override_is_encrypted_retained_and_used_for_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only provider-accepted invoice delivery changes future receipt routing."""
    import app.services.email as email_mod

    monkeypatch.setattr(call_payment_service, "is_payment_configured", lambda: False)
    sent: list[dict[str, object]] = []
    receipts: list[dict[str, object]] = []
    provider_accepts = True

    async def _fake_email(**kwargs: object) -> bool:
        sent.append(kwargs)
        return provider_accepts

    async def _fake_receipt(**kwargs: object) -> bool:
        receipts.append(kwargs)
        return True

    monkeypatch.setattr(email_mod, "send_invoice_email", _fake_email)
    monkeypatch.setattr(email_mod, "send_invoice_payment_receipt", _fake_receipt)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id, email="onfile@example.com")
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )

        result = await svc.deliver_invoice(
            ws.id, inv.id, channel="email", to="accounting@example.com"
        )
        assert result.to == "accounting@example.com"
        assert sent[0]["to_email"] == "accounting@example.com"

        stored = await db.get(Invoice, inv.id)
        assert stored is not None
        assert stored.last_emailed_to == "accounting@example.com"
        assert stored.last_emailed_at is not None
        accepted_at = stored.last_emailed_at
        encrypted_destination = await db.scalar(
            text("SELECT last_emailed_to FROM invoices WHERE id = :invoice_id"),
            {"invoice_id": inv.id},
        )
        assert encrypted_destination != "accounting@example.com"
        assert str(encrypted_destination).startswith("gAAAAA")

        provider_accepts = False
        with pytest.raises(ValidationError, match="could not be sent"):
            await svc.deliver_invoice(ws.id, inv.id, channel="email", to="rejected@example.com")
        await db.refresh(stored)
        assert stored.last_emailed_to == "accounting@example.com"
        assert stored.last_emailed_at == accepted_at

        contact.email = "changed@example.com"
        contact.email_hash = hash_value(contact.email)
        await db.commit()
        assert await svc.record_payment(
            stored, 100.0, payment_intent_id=_stripe_id("pi_snapshot_receipt")
        )
        receipt_job = await db.scalar(
            select(InvoicePaymentReceiptOutbox).where(
                InvoicePaymentReceiptOutbox.invoice_id == stored.id
            )
        )
        assert receipt_job is not None
        assert receipts == []
        assert receipt_job.recipient_email == "accounting@example.com"


# --------------------------------------------------------------------------- #
# Telling the company money arrived
# --------------------------------------------------------------------------- #
async def test_a_customer_payment_notifies_the_company(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Money landing must reach a human, not just the database.

    Self-serve payments used to notify nobody: the row updated and the only way
    to find out was to open the dashboard and look.
    """
    import app.services.payments.customer_payment_notifications as notif

    calls: list[dict[str, object]] = []

    async def _fake_notify(db: object, **kwargs: object) -> int:
        calls.append(kwargs)
        return 1

    monkeypatch.setattr(notif, "notify_customer_payment", _fake_notify)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=500.0)]),
        )
        invoice = await db.get(Invoice, inv.id)
        assert invoice is not None

        applied = await svc.record_payment(
            invoice, 500.0, payment_intent_id=_stripe_id("pi_notify_1")
        )

        assert applied is True
        assert len(calls) == 1
        assert calls[0]["amount"] == 500.0
        assert "INV-" in str(calls[0]["description"])


async def test_a_webhook_replay_does_not_re_notify(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stripe retries the same event; the company must not be told twice."""
    import app.services.payments.customer_payment_notifications as notif

    calls: list[dict[str, object]] = []

    async def _fake_notify(db: object, **kwargs: object) -> int:
        calls.append(kwargs)
        return 1

    monkeypatch.setattr(notif, "notify_customer_payment", _fake_notify)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=500.0)]),
        )
        invoice = await db.get(Invoice, inv.id)
        assert invoice is not None

        payment_intent_id = _stripe_id("pi_replay")
        await svc.record_payment(invoice, 500.0, payment_intent_id=payment_intent_id)
        # Same intent id arrives again (Stripe retry).
        applied_again = await svc.record_payment(
            invoice, 500.0, payment_intent_id=payment_intent_id
        )

        assert applied_again is False
        assert len(calls) == 1


async def test_a_notification_outage_never_undoes_a_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The money is banked and Stripe wants a 2xx; mail failure must not raise."""
    import app.services.payments.customer_payment_notifications as notif

    async def _boom(db: object, **kwargs: object) -> int:
        raise RuntimeError("resend down")

    monkeypatch.setattr(notif, "notify_customer_payment", _boom)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        inv = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=500.0)]),
        )
        invoice = await db.get(Invoice, inv.id)
        assert invoice is not None

        applied = await svc.record_payment(invoice, 500.0, payment_intent_id=_stripe_id("pi_boom"))

        assert applied is True
        await db.refresh(invoice)
        assert invoice.status == "paid"
        assert float(invoice.amount_paid) == 500.0


async def test_list_names_the_bill_to_contact() -> None:
    """A list row says whose invoice it is, not just its number.

    An invoice with no bill-to contact is a legitimate state (an unattached
    draft), so its name is ``None`` rather than a placeholder -- the UI decides
    how to render the gap.
    """
    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        contact.last_name = "Reyes"
        await db.flush()
        svc = InvoiceService(db)

        named = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Gutter clean", unit_price=180.0)],
            ),
        )
        unattached = await svc.create_invoice(ws.id, InvoiceCreate(line_items=[]))

        listed = await svc.list_invoices(ws.id)
        by_id = {item.id: item for item in listed.items}

        # First and last name are joined for display; neither is encrypted.
        assert by_id[named.id].contact_name == "Pat Reyes"
        assert by_id[named.id].contact_id == contact.id
        # No bill-to contact means no name, not an empty string or a crash.
        assert by_id[unattached.id].contact_name is None

        # The single-invoice read carries the same label, so a detail view and a
        # list row never disagree about who is being billed.
        assert (await svc.get_invoice(ws.id, named.id)).contact_name == "Pat Reyes"


async def test_contact_name_is_not_leaked_across_workspaces() -> None:
    """Listing one workspace never surfaces another tenant's contact name."""
    async with AsyncSessionLocal() as db:
        ws_a = await _make_workspace(db)
        ws_b = await _make_workspace(db)
        contact_a = await _make_contact(db, ws_a.id)
        contact_a.last_name = "Private"
        await db.flush()
        svc = InvoiceService(db)

        await svc.create_invoice(ws_a.id, InvoiceCreate(contact_id=contact_a.id, line_items=[]))
        await svc.create_invoice(ws_b.id, InvoiceCreate(line_items=[]))

        listed_b = await svc.list_invoices(ws_b.id)
        assert listed_b.total == 1
        assert all(item.contact_name != "Pat Private" for item in listed_b.items)
        assert listed_b.items[0].contact_name is None


async def test_sent_checkout_affecting_edits_expire_only_the_price_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_sessions: list[str] = []

    async def _fake_expire(session_id: str) -> bool:
        expired_sessions.append(session_id)
        return True

    monkeypatch.setattr(call_payment_service, "expire_checkout_session_if_open", _fake_expire)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        contact = await _make_contact(db, ws.id)
        replacement_contact = await _make_contact(db, ws.id)
        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(
                contact_id=contact.id,
                line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)],
            ),
        )
        await svc.mark_sent(ws.id, created.id)
        stored = await db.get(Invoice, created.id)
        assert stored is not None
        public_token = stored.public_token
        assert public_token is not None

        header_updates = [
            InvoiceUpdate(tax_amount=10.0),
            InvoiceUpdate(discount_amount=5.0),
            InvoiceUpdate(currency="EUR"),
            InvoiceUpdate(contact_id=replacement_contact.id),
        ]
        for index, invoice_update in enumerate(header_updates):
            stored = await db.get(Invoice, created.id)
            assert stored is not None
            stored.stripe_checkout_session_id = f"cs_header_{index}"
            stored.stripe_payment_intent_id = "pi_existing_payment"
            await db.commit()

            await svc.update_invoice(ws.id, created.id, invoice_update)
            persisted = await db.get(Invoice, created.id)
            assert persisted is not None
            assert persisted.stripe_checkout_session_id is None
            assert persisted.stripe_payment_intent_id == "pi_existing_payment"
            assert persisted.public_token == public_token

        stored = await db.get(Invoice, created.id)
        assert stored is not None
        await db.refresh(stored, ["line_items"])
        stored.stripe_checkout_session_id = "cs_line_item"
        await db.commit()
        line_item = stored.line_items[0]
        updated = await svc.update_line_item(
            ws.id, created.id, line_item.id, InvoiceLineItemUpdate(unit_price=120.0)
        )
        assert updated.total == 125.0
        persisted = await db.get(Invoice, created.id)
        assert persisted is not None
        assert persisted.stripe_checkout_session_id is None
        assert persisted.public_token == public_token

        stored = await db.get(Invoice, created.id)
        assert stored is not None
        stored.stripe_checkout_session_id = "cs_void"
        await db.commit()
        voided = await svc.void_invoice(ws.id, created.id)
        assert voided.status == "void"
        persisted = await db.get(Invoice, created.id)
        assert persisted is not None
        assert persisted.stripe_checkout_session_id is None
        assert persisted.public_token == public_token

    assert expired_sessions == [
        "cs_header_0",
        "cs_header_1",
        "cs_header_2",
        "cs_header_3",
        "cs_line_item",
        "cs_void",
    ]


async def test_checkout_expiration_failure_rolls_back_the_entire_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _cannot_expire(session_id: str) -> bool:
        return False

    monkeypatch.setattr(call_payment_service, "expire_checkout_session_if_open", _cannot_expire)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)]),
        )
        await svc.mark_sent(ws.id, created.id)
        stored = await db.get(Invoice, created.id)
        assert stored is not None
        stored.stripe_checkout_session_id = "cs_cannot_expire"
        original_token = stored.public_token
        await db.commit()

        with pytest.raises(ConflictError, match="could not be invalidated"):
            await svc.update_invoice(ws.id, created.id, InvoiceUpdate(tax_amount=25.0))

        persisted = await db.get(Invoice, created.id)
        assert persisted is not None
        assert float(persisted.tax_amount) == 0.0
        assert float(persisted.total) == 100.0
        assert persisted.stripe_checkout_session_id == "cs_cannot_expire"
        assert persisted.public_token == original_token


async def test_partial_edit_rejects_underpayment_and_equality_uses_paid_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.invoices.invoice_service as invoice_service_module

    paid_events: list[dict[str, object]] = []

    async def _fake_emit(db: object, **kwargs: object) -> None:
        paid_events.append(kwargs)

    async def _fake_notify(self: InvoiceService, invoice: Invoice, amount: float) -> None:
        return None

    monkeypatch.setattr(invoice_service_module, "emit_automation_event", _fake_emit)
    monkeypatch.setattr(InvoiceService, "_notify_payment_received", _fake_notify)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        created = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)]),
        )
        await svc.mark_sent(ws.id, created.id)
        workspace_id = ws.id
        paid_events.clear()
        stored = await db.get(Invoice, created.id)
        assert stored is not None
        payment_intent_id = _stripe_id("pi_partial_edit")
        assert await svc.record_payment(stored, 40.0, payment_intent_id=payment_intent_id)
        assert stored.status == "partial"

        with pytest.raises(ConflictError, match="less than the amount already paid"):
            await svc.update_invoice(workspace_id, created.id, InvoiceUpdate(discount_amount=70.0))

        paid = await svc.update_invoice(
            workspace_id, created.id, InvoiceUpdate(discount_amount=60.0)
        )
        assert paid.total == 40.0
        assert paid.amount_paid == 40.0
        assert paid.status == "paid"
        assert paid.paid_at is not None
        assert len(paid_events) == 1
        receipt_jobs = list(
            (
                await db.scalars(
                    select(InvoicePaymentReceiptOutbox).where(
                        InvoicePaymentReceiptOutbox.invoice_id == created.id
                    )
                )
            ).all()
        )
        assert len(receipt_jobs) == 1
        assert float(receipt_jobs[0].payment_amount) == 40.0
        assert float(receipt_jobs[0].balance_remaining or 0) == 60.0
        assert receipt_jobs[0].payment_event_id == payment_intent_id

        annotated = await svc.update_invoice(
            workspace_id,
            created.id,
            InvoiceUpdate(
                notes="Paid on site",
                terms="Thank you",
                due_date=date.today() + timedelta(days=30),
            ),
        )
        assert annotated.notes == "Paid on site"
        assert annotated.terms == "Thank you"
        assert len(paid_events) == 1
        assert (
            len(
                list(
                    (
                        await db.scalars(
                            select(InvoicePaymentReceiptOutbox).where(
                                InvoicePaymentReceiptOutbox.invoice_id == created.id
                            )
                        )
                    ).all()
                )
            )
            == 1
        )


async def test_duplicate_webhook_race_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_intent_id = _stripe_id("pi_duplicate_race")
    import app.services.invoices.invoice_service as invoice_service_module

    paid_events: list[dict[str, object]] = []
    notifications: list[float] = []

    async def _fake_emit(db: object, **kwargs: object) -> None:
        paid_events.append(kwargs)

    async def _fake_notify(self: InvoiceService, invoice: Invoice, amount: float) -> None:
        notifications.append(amount)

    monkeypatch.setattr(invoice_service_module, "emit_automation_event", _fake_emit)
    monkeypatch.setattr(InvoiceService, "_notify_payment_received", _fake_notify)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        duplicate = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=90.0)]),
        )
        await svc.mark_sent(ws.id, duplicate.id)
        paid_events.clear()
        stored = await db.get(Invoice, duplicate.id)
        assert stored is not None
        stored.stripe_checkout_session_id = "cs_duplicate_race"
        await db.commit()
        duplicate_id = duplicate.id

    duplicate_session = {
        "id": "cs_duplicate_race",
        "mode": "payment",
        "payment_intent": payment_intent_id,
        "amount_total": 9000,
        "metadata": {"invoice_id": str(duplicate_id)},
    }

    async def _deliver_duplicate() -> None:
        async with AsyncSessionLocal() as webhook_db:
            await handle_invoice_checkout_session_completed(duplicate_session, webhook_db)

    await asyncio.gather(_deliver_duplicate(), _deliver_duplicate())

    async with AsyncSessionLocal() as db:
        persisted = await db.get(Invoice, duplicate_id)
        assert persisted is not None
        assert float(persisted.amount_paid) == 90.0
        assert persisted.status == "paid"
        assert persisted.paid_at is not None
        jobs = list(
            (
                await db.scalars(
                    select(InvoicePaymentReceiptOutbox).where(
                        InvoicePaymentReceiptOutbox.invoice_id == duplicate_id
                    )
                )
            ).all()
        )
        assert len(jobs) == 1
        assert jobs[0].payment_event_id == payment_intent_id

    assert len(paid_events) == 1
    assert notifications == [90.0]


async def test_stale_checkout_webhook_race_cannot_apply_the_old_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expire_started = asyncio.Event()
    payment_started = asyncio.Event()
    allow_expire = asyncio.Event()
    original_record_payment = InvoiceService.record_payment

    async def _fake_expire(session_id: str) -> bool:
        expire_started.set()
        await allow_expire.wait()
        return True

    async def _record_after_signal(
        self: InvoiceService,
        invoice: Invoice,
        amount: float,
        *,
        payment_intent_id: str | None = None,
        checkout_session_id: str | None = None,
    ) -> bool:
        payment_started.set()
        return await original_record_payment(
            self,
            invoice,
            amount,
            payment_intent_id=payment_intent_id,
            checkout_session_id=checkout_session_id,
        )

    monkeypatch.setattr(call_payment_service, "expire_checkout_session_if_open", _fake_expire)
    monkeypatch.setattr(InvoiceService, "record_payment", _record_after_signal)

    async with AsyncSessionLocal() as db:
        ws = await _make_workspace(db)
        svc = InvoiceService(db)
        stale = await svc.create_invoice(
            ws.id,
            InvoiceCreate(line_items=[InvoiceLineItemCreate(name="Job", unit_price=100.0)]),
        )
        await svc.mark_sent(ws.id, stale.id)
        stored = await db.get(Invoice, stale.id)
        assert stored is not None
        stored.stripe_checkout_session_id = "cs_stale_race"
        stale_token = stored.public_token
        await db.commit()
        stale_workspace_id = ws.id
        stale_id = stale.id

    stale_session = {
        "id": "cs_stale_race",
        "mode": "payment",
        "payment_intent": "pi_stale_race",
        "amount_total": 10000,
        "metadata": {"invoice_id": str(stale_id)},
    }

    async def _edit_price() -> None:
        async with AsyncSessionLocal() as edit_db:
            await InvoiceService(edit_db).update_invoice(
                stale_workspace_id, stale_id, InvoiceUpdate(tax_amount=10.0)
            )

    async def _deliver_stale() -> None:
        async with AsyncSessionLocal() as webhook_db:
            await handle_invoice_checkout_session_completed(stale_session, webhook_db)

    edit_task = asyncio.create_task(_edit_price())
    await expire_started.wait()
    webhook_task = asyncio.create_task(_deliver_stale())
    await payment_started.wait()
    allow_expire.set()
    await asyncio.gather(edit_task, webhook_task)

    async with AsyncSessionLocal() as db:
        persisted = await db.get(Invoice, stale_id)
        assert persisted is not None
        assert float(persisted.total) == 110.0
        assert float(persisted.amount_paid) == 0.0
        assert persisted.status == "sent"
        assert persisted.stripe_checkout_session_id is None
        assert persisted.public_token == stale_token
