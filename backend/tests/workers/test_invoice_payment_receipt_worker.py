"""Real-Postgres integration tests for the invoice receipt outbox worker."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.invoice import Invoice
from app.models.invoice_payment_receipt_outbox import InvoicePaymentReceiptOutbox
from app.models.workspace import Workspace
from app.workers import invoice_payment_receipt_worker as worker_mod

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_job(
    db: AsyncSession,
    *,
    recipient_email: str | None = "customer@example.com",
    status: str = "pending",
    attempt_count: int = 0,
    claimed_at: datetime | None = None,
) -> InvoicePaymentReceiptOutbox:
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Receipt Worker Co",
        slug=f"receipt-worker-{uuid.uuid4().hex[:8]}",
    )
    db.add(workspace)
    await db.flush()
    invoice = Invoice(
        workspace_id=workspace.id,
        number=f"INV-WORKER-{uuid.uuid4().hex[:10]}",
        currency="USD",
        subtotal=100,
        tax_amount=0,
        discount_amount=0,
        total=100,
        amount_paid=100,
        status="paid",
        paid_at=datetime.now(UTC),
    )
    db.add(invoice)
    await db.flush()
    job = InvoicePaymentReceiptOutbox(
        workspace_id=workspace.id,
        invoice_id=invoice.id,
        payment_event_id=f"pi_{uuid.uuid4().hex}",
        recipient_email=recipient_email,
        customer_name="Pat Customer",
        service_summary="Gutter cleaning × 2",
        business_name=workspace.name,
        invoice_number=invoice.number,
        payment_amount=100,
        invoice_total=100,
        total_paid=100,
        balance_remaining=0,
        currency="USD",
        paid_at=invoice.paid_at,
        invoice_url="https://example.com/p/invoices/test",
        idempotency_key=uuid.uuid4(),
        status=status,
        attempt_count=attempt_count,
        claimed_at=claimed_at,
        next_attempt_at=datetime(2000, 1, 1, tzinfo=UTC),
    )
    db.add(job)
    await db.commit()
    return job


async def _reload(job_id: uuid.UUID) -> InvoicePaymentReceiptOutbox:
    async with AsyncSessionLocal() as db:
        job = await db.get(InvoicePaymentReceiptOutbox, job_id)
        assert job is not None
        return job


async def test_worker_restart_recovers_stale_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def _accepted(**kwargs: object) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(worker_mod, "BATCH_SIZE", 1)
    monkeypatch.setattr(worker_mod, "send_invoice_payment_receipt", _accepted)
    async with AsyncSessionLocal() as db:
        job = await _make_job(
            db,
            status="processing",
            attempt_count=1,
            claimed_at=datetime.now(UTC) - worker_mod.CLAIM_TTL - timedelta(seconds=1),
        )
        job_id = job.id

    await worker_mod.InvoicePaymentReceiptWorker().process_once()

    reloaded = await _reload(job_id)
    assert reloaded.status == "sent"
    assert reloaded.attempt_count == 2
    assert len(calls) == 1
    assert calls[0]["idempotency_key"] == reloaded.idempotency_key
    assert calls[0]["service_summary"] == "Gutter cleaning × 2"
    assert calls[0]["balance_remaining"] == 0


async def test_missing_recipient_is_terminal_without_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def _unexpected_send(**kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(worker_mod, "BATCH_SIZE", 1)
    monkeypatch.setattr(worker_mod, "send_invoice_payment_receipt", _unexpected_send)
    async with AsyncSessionLocal() as db:
        job = await _make_job(db, recipient_email=None)
        job_id = job.id

    await worker_mod.InvoicePaymentReceiptWorker().process_once()

    reloaded = await _reload(job_id)
    assert reloaded.status == "terminal"
    assert reloaded.terminal_at is not None
    assert reloaded.last_error == "Missing receipt recipient"
    assert calls == 0


async def test_transient_provider_or_configuration_failure_retries_then_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = iter([False, True])

    async def _send(**kwargs: object) -> bool:
        return next(outcomes)

    monkeypatch.setattr(worker_mod, "BATCH_SIZE", 1)
    monkeypatch.setattr(worker_mod, "send_invoice_payment_receipt", _send)
    async with AsyncSessionLocal() as db:
        job = await _make_job(db)
        job_id = job.id

    worker = worker_mod.InvoicePaymentReceiptWorker()
    await worker.process_once()
    failed = await _reload(job_id)
    assert failed.status == "pending"
    assert failed.attempt_count == 1
    assert failed.next_attempt_at > datetime.now(UTC)
    assert "did not accept" in (failed.last_error or "")

    async with AsyncSessionLocal() as db:
        retry = await db.get(InvoicePaymentReceiptOutbox, job_id)
        assert retry is not None
        retry.next_attempt_at = datetime(2000, 1, 1, tzinfo=UTC)
        await db.commit()

    await worker.process_once()
    sent = await _reload(job_id)
    assert sent.status == "sent"
    assert sent.attempt_count == 2
    assert sent.sent_at is not None
    assert sent.last_error is None


async def test_max_attempt_failure_becomes_terminal_and_bounds_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fail(**kwargs: object) -> bool:
        raise RuntimeError("provider exploded " + ("x" * 2000))

    monkeypatch.setattr(worker_mod, "BATCH_SIZE", 1)
    monkeypatch.setattr(worker_mod, "send_invoice_payment_receipt", _fail)
    async with AsyncSessionLocal() as db:
        job = await _make_job(db, attempt_count=worker_mod.MAX_ATTEMPTS - 1)
        job_id = job.id

    await worker_mod.InvoicePaymentReceiptWorker().process_once()

    reloaded = await _reload(job_id)
    assert reloaded.status == "terminal"
    assert reloaded.attempt_count == worker_mod.MAX_ATTEMPTS
    assert reloaded.terminal_at is not None
    assert reloaded.sent_at is None
    assert reloaded.last_error is not None
    assert len(reloaded.last_error) == worker_mod.MAX_ERROR_LENGTH
    async with AsyncSessionLocal() as db:
        paid_invoice = await db.get(Invoice, reloaded.invoice_id)
        assert paid_invoice is not None
        assert paid_invoice.status == "paid"
        assert float(paid_invoice.amount_paid) == 100.0
