"""Integration tests for :class:`app.services.reporting.ReportingService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: AR aging bucketing (current vs overdue ranges, paid/draft excluded,
partial balances) and the job P&L summary (revenue from distinct linked invoices
minus labor and expenses, with tenant isolation).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.invoice import Invoice
from app.models.job_costing import JobExpense, TimeEntry
from app.models.workspace import Workspace
from app.services.reporting import ReportingService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Reporting", slug=f"rep-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    email = f"ada-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Ada",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _invoice(
    db,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    total: float,
    status: str,
    due_date: date | None,
    amount_paid: float = 0.0,
    currency: str = "USD",
) -> Invoice:
    invoice = Invoice(
        workspace_id=workspace_id,
        contact_id=contact_id,
        number=f"INV-{uuid.uuid4().hex[:6]}",
        subtotal=total,
        total=total,
        amount_paid=amount_paid,
        status=status,
        due_date=due_date,
        currency=currency,
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def _job(db, workspace_id: uuid.UUID, contact_id: int, *, invoice_id=None, start=None) -> Job:
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact_id,
        title="Service",
        status=JobStatus.SCHEDULED,
        invoice_id=invoice_id,
        scheduled_start=start,
    )
    db.add(job)
    await db.flush()
    return job


# --------------------------------------------------------------------------- #
# AR aging
# --------------------------------------------------------------------------- #
async def test_ar_aging_buckets_by_overdue_age() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        as_of = date(2026, 7, 1)

        # Not yet due → Current.
        await _invoice(
            db, ws.id, contact.id, total=100, status="sent", due_date=as_of + timedelta(days=10)
        )
        # 15 days overdue → 1-30.
        await _invoice(
            db, ws.id, contact.id, total=200, status="overdue", due_date=as_of - timedelta(days=15)
        )
        # 45 days overdue → 31-60.
        await _invoice(
            db, ws.id, contact.id, total=300, status="sent", due_date=as_of - timedelta(days=45)
        )
        # 120 days overdue → 90+.
        await _invoice(
            db, ws.id, contact.id, total=400, status="sent", due_date=as_of - timedelta(days=120)
        )
        # Paid + draft → excluded entirely.
        await _invoice(
            db, ws.id, contact.id, total=999, status="paid", due_date=as_of - timedelta(days=5)
        )
        await _invoice(
            db, ws.id, contact.id, total=999, status="draft", due_date=as_of - timedelta(days=5)
        )

        report = await ReportingService(db).ar_aging(ws.id, as_of=as_of)
        assert report.total_invoices == 4
        assert report.total_outstanding == 1000.0
        by_label = {b.label: b for b in report.buckets}
        assert by_label["Current"].amount == 100.0
        assert by_label["1-30"].amount == 200.0
        assert by_label["31-60"].amount == 300.0
        assert by_label["61-90"].amount == 0.0
        assert by_label["90+"].amount == 400.0


async def test_ar_aging_uses_outstanding_balance_for_partial() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        as_of = date(2026, 7, 1)

        # $500 invoice, $200 already paid → $300 outstanding, 10 days overdue.
        await _invoice(
            db,
            ws.id,
            contact.id,
            total=500,
            amount_paid=200,
            status="partial",
            due_date=as_of - timedelta(days=10),
        )
        report = await ReportingService(db).ar_aging(ws.id, as_of=as_of)
        assert report.total_outstanding == 300.0
        by_label = {b.label: b for b in report.buckets}
        assert by_label["1-30"].amount == 300.0
        assert by_label["1-30"].count == 1


async def test_ar_aging_reflects_a_single_non_usd_currency() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _invoice(
            db, ws.id, contact.id, total=100, status="sent", due_date=None, currency="EUR"
        )
        report = await ReportingService(db).ar_aging(ws.id)
        assert report.currency == "EUR"
        assert report.total_outstanding == 100.0


async def test_ar_aging_refuses_to_sum_across_currencies() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        await _invoice(
            db, ws.id, contact.id, total=100, status="sent", due_date=None, currency="USD"
        )
        await _invoice(
            db, ws.id, contact.id, total=200, status="sent", due_date=None, currency="EUR"
        )
        # Summing USD + EUR would be silently wrong, so the report must refuse.
        with pytest.raises(HTTPException) as exc:
            await ReportingService(db).ar_aging(ws.id)
        assert exc.value.status_code == 422
        assert "EUR" in exc.value.detail and "USD" in exc.value.detail


# --------------------------------------------------------------------------- #
# Job P&L summary
# --------------------------------------------------------------------------- #
async def test_job_pnl_summary_aggregates_revenue_minus_costs() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)

        invoice = await _invoice(
            db, ws.id, contact.id, total=1000, status="sent", due_date=None
        )
        job = await _job(db, ws.id, contact.id, invoice_id=invoice.id, start=start)
        # 4h @ $90 = $360 labor.
        db.add(
            TimeEntry(
                workspace_id=ws.id,
                job_id=job.id,
                started_at=start,
                ended_at=start + timedelta(hours=4),
                rate=90,
            )
        )
        db.add(
            JobExpense(workspace_id=ws.id, job_id=job.id, description="Parts", amount=200)
        )
        # A second, non-billable job (no invoice) in range.
        await _job(db, ws.id, contact.id, start=start + timedelta(days=1))
        await db.flush()

        summary = await ReportingService(db).job_pnl_summary(ws.id)
        assert summary.job_count == 2
        assert summary.billable_job_count == 1
        assert summary.revenue == 1000.0
        assert summary.labor_cost == 360.0
        assert summary.expense_cost == 200.0
        assert summary.profit == 440.0
        assert summary.margin == 0.44
        assert summary.total_hours == 4.0


async def test_job_pnl_summary_does_not_double_count_shared_invoice() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)

        invoice = await _invoice(
            db, ws.id, contact.id, total=1000, status="sent", due_date=None
        )
        # Two jobs share one invoice → revenue counted once.
        await _job(db, ws.id, contact.id, invoice_id=invoice.id, start=start)
        await _job(db, ws.id, contact.id, invoice_id=invoice.id, start=start)

        summary = await ReportingService(db).job_pnl_summary(ws.id)
        assert summary.revenue == 1000.0
        assert summary.billable_job_count == 1
        assert summary.job_count == 2


async def test_job_pnl_summary_respects_date_window_and_tenancy() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        other_contact = await _contact(db, other.id)

        in_range = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        out_of_range = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        inv_in = await _invoice(db, ws.id, contact.id, total=500, status="sent", due_date=None)
        inv_out = await _invoice(db, ws.id, contact.id, total=700, status="sent", due_date=None)
        await _job(db, ws.id, contact.id, invoice_id=inv_in.id, start=in_range)
        await _job(db, ws.id, contact.id, invoice_id=inv_out.id, start=out_of_range)
        # Another workspace's billable job must never leak in.
        other_inv = await _invoice(
            db, other.id, other_contact.id, total=9999, status="sent", due_date=None
        )
        await _job(db, other.id, other_contact.id, invoice_id=other_inv.id, start=in_range)

        summary = await ReportingService(db).job_pnl_summary(
            ws.id,
            date_from=datetime(2026, 6, 1, tzinfo=UTC),
            date_to=datetime(2026, 6, 30, tzinfo=UTC),
        )
        assert summary.job_count == 1
        assert summary.revenue == 500.0


async def test_job_pnl_summary_refuses_to_sum_across_currencies() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        usd = await _invoice(
            db, ws.id, contact.id, total=500, status="sent", due_date=None, currency="USD"
        )
        eur = await _invoice(
            db, ws.id, contact.id, total=700, status="sent", due_date=None, currency="EUR"
        )
        await _job(db, ws.id, contact.id, invoice_id=usd.id, start=start)
        await _job(db, ws.id, contact.id, invoice_id=eur.id, start=start)
        with pytest.raises(HTTPException) as exc:
            await ReportingService(db).job_pnl_summary(ws.id)
        assert exc.value.status_code == 422
