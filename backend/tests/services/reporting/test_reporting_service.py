"""Integration tests for :class:`app.services.reporting.ReportingService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: AR aging bucketing, issued invoice revenue counted once per invoice,
independent linked-job counts, all job costs, and currency/workspace isolation.
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
from app.models.inventory import InventoryItem
from app.models.invoice import INVOICE_STATUSES, Invoice
from app.models.job_costing import JobExpense, TimeEntry
from app.models.lead_source import LeadSource, LeadSourceType
from app.models.workspace import Workspace
from app.schemas.inventory import ReceiveStockRequest
from app.services.inventory import StockService
from app.services.reporting import ReportingService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    assert engine.url.host in {"localhost", "127.0.0.1", "::1"}, "Use a local test database"
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
        number=f"INV-{uuid.uuid4().hex}",
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


@pytest.mark.parametrize(
    ("invoice_status", "amount_paid", "expected_revenue"),
    [
        ("draft", 0, 0),
        ("void", 0, 0),
        ("void", 1000, 0),
        ("sent", 0, 1000),
        ("partial", 250, 1000),
        ("paid", 1000, 1000),
        ("overdue", 250, 1000),
    ],
)
@pytest.mark.parametrize("currency", ["USD", "EUR"])
@pytest.mark.parametrize("linked", [False, True])
async def test_job_pnl_summary_recognizes_only_issued_invoice_totals(
    invoice_status: str, amount_paid: float, expected_revenue: float, currency: str, linked: bool
) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        invoice = await _invoice(
            db,
            ws.id,
            contact.id,
            total=1000,
            status=invoice_status,
            due_date=None,
            amount_paid=amount_paid,
            currency=currency,
        )
        await _job(db, ws.id, contact.id, invoice_id=invoice.id if linked else None)
        # An unlinked invoice affects neither revenue nor the currency guard.
        await _invoice(
            db, ws.id, contact.id, total=9999, status="paid", due_date=None, currency="CAD"
        )

        summary = await ReportingService(db).job_pnl_summary(ws.id)
        recognized_revenue = expected_revenue if linked else 0.0
        assert summary.job_count == 1
        assert summary.billable_job_count == int(linked)
        assert summary.revenue == recognized_revenue
        assert summary.profit == recognized_revenue
        assert summary.currency == (currency if linked else "USD")
        assert summary.margin == (1.0 if recognized_revenue else None)


@pytest.mark.parametrize("invoice_status", [None, "draft", "void"])
async def test_job_pnl_summary_keeps_all_costs_without_invoice_revenue(
    invoice_status: str | None,
) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        invoice_id = None
        if invoice_status:
            invoice = await _invoice(
                db, ws.id, contact.id, total=1000, status=invoice_status, due_date=None
            )
            invoice_id = invoice.id
        job = await _job(db, ws.id, contact.id, invoice_id=invoice_id)
        start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        db.add_all(
            [
                TimeEntry(
                    workspace_id=ws.id,
                    job_id=job.id,
                    started_at=start,
                    ended_at=start + timedelta(hours=2),
                    rate=50,
                ),
                # Open timers have no cost/hours; unpriced closed time still counts hours.
                TimeEntry(workspace_id=ws.id, job_id=job.id, started_at=start, rate=999),
                TimeEntry(
                    workspace_id=ws.id,
                    job_id=job.id,
                    started_at=start,
                    ended_at=start + timedelta(hours=1),
                ),
                JobExpense(
                    workspace_id=ws.id,
                    job_id=job.id,
                    description="Purchased materials",
                    category="materials",
                    amount=50,
                ),
            ]
        )
        item = InventoryItem(workspace_id=ws.id, name="Reporting materials")
        db.add(item)
        await db.flush()
        stock = StockService(db)
        await stock.receive(ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=10))
        consumed = await stock.consume(ws.id, item.id, 4, reference_type="job", reference_id=job.id)
        await stock.return_to_stock(
            ws.id,
            item.id,
            1,
            unit_cost=float(consumed.unit_cost),
            location_id=consumed.location_id,
            reference_type="job",
            reference_id=job.id,
        )

        summary = await ReportingService(db).job_pnl_summary(ws.id)
        assert summary.job_count == 1
        assert summary.billable_job_count == (1 if invoice_status else 0)
        assert summary.revenue == 0.0
        assert summary.total_hours == 3.0
        assert summary.labor_cost == 100.0
        assert summary.expense_cost == 50.0
        assert summary.material_cost == 30.0
        assert summary.total_cost == 180.0
        assert summary.profit == -180.0
        assert summary.margin is None


async def test_job_pnl_summary_ignores_cross_workspace_invoice_and_cost_links() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        other_contact = await _contact(db, other.id)
        mine = await _invoice(db, ws.id, contact.id, total=1000, status="paid", due_date=None)
        foreign = await _invoice(
            db, other.id, other_contact.id, total=9999, status="paid", due_date=None, currency="EUR"
        )
        job = await _job(db, ws.id, contact.id, invoice_id=mine.id)
        # Corrupt links must not reveal another workspace's counts or money.
        await _job(db, ws.id, contact.id, invoice_id=foreign.id)
        await _job(db, other.id, other_contact.id, invoice_id=foreign.id)
        start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        db.add_all(
            [
                TimeEntry(
                    workspace_id=other.id,
                    job_id=job.id,
                    started_at=start,
                    ended_at=start + timedelta(hours=1),
                    rate=999,
                ),
                JobExpense(
                    workspace_id=other.id,
                    job_id=job.id,
                    description="Other workspace's expense",
                    category="materials",
                    amount=999,
                ),
            ]
        )
        foreign_item = InventoryItem(workspace_id=other.id, name="Other workspace's stock")
        db.add(foreign_item)
        await db.flush()
        stock = StockService(db)
        await stock.receive(
            other.id, foreign_item.id, ReceiveStockRequest(quantity=1, unit_cost=999)
        )
        await stock.consume(other.id, foreign_item.id, 1, reference_type="job", reference_id=job.id)

        summary = await ReportingService(db).job_pnl_summary(ws.id)
        assert summary.job_count == 2
        assert summary.billable_job_count == 1
        assert summary.revenue == 1000.0
        assert summary.currency == "USD"
        assert summary.total_hours == 0.0
        assert summary.total_cost == 0.0
        assert summary.profit == 1000.0


# --------------------------------------------------------------------------- #
# Attribution coverage
# --------------------------------------------------------------------------- #
async def test_attribution_gap_counts_missing_sources_in_range_and_workspace() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        source = LeadSource(
            workspace_id=ws.id,
            name="Referral",
            allowed_domains=[],
            source_type=LeadSourceType.REFERRAL_PARTNER,
        )
        db.add(source)
        await db.flush()

        created_in_range = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
        attributed = await _contact(db, ws.id)
        attributed.created_at = created_in_range
        attributed.first_touch_lead_source_id = source.id

        missing_one = await _contact(db, ws.id)
        missing_one.created_at = created_in_range
        missing_two = await _contact(db, ws.id)
        missing_two.created_at = datetime(2026, 7, 31, 23, 59, tzinfo=UTC)

        outside = await _contact(db, ws.id)
        outside.created_at = datetime(2026, 6, 30, 23, 59, tzinfo=UTC)
        other_workspace = await _contact(db, other.id)
        other_workspace.created_at = created_in_range
        await db.flush()

        report = await ReportingService(db).attribution_gap(
            ws.id,
            date_from=date(2026, 7, 1),
            date_to=date(2026, 7, 31),
        )

        assert report.total_contacts == 3
        assert report.unattributed_contacts == 2
        assert report.attributed_contacts == 1
        assert report.gap_rate == 0.6667


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

        invoice = await _invoice(db, ws.id, contact.id, total=1000, status="sent", due_date=None)
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
        db.add(JobExpense(workspace_id=ws.id, job_id=job.id, description="Parts", amount=200))
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

        invoice = await _invoice(db, ws.id, contact.id, total=1000, status="sent", due_date=None)
        # Two jobs share one invoice → revenue counted once.
        await _job(db, ws.id, contact.id, invoice_id=invoice.id, start=start)
        await _job(db, ws.id, contact.id, invoice_id=invoice.id, start=start)

        summary = await ReportingService(db).job_pnl_summary(ws.id)
        assert summary.revenue == 1000.0
        assert summary.billable_job_count == 2
        assert summary.job_count == 2

        invoice.status = "void"
        await db.flush()
        voided = await ReportingService(db).job_pnl_summary(ws.id)
        assert voided.revenue == 0.0
        assert voided.billable_job_count == 2
        assert voided.job_count == 2


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


@pytest.mark.parametrize("invoice_status", INVOICE_STATUSES)
async def test_job_pnl_summary_refuses_to_sum_across_currencies(invoice_status: str) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        start = datetime(2026, 6, 15, 9, 0, tzinfo=UTC)
        usd = await _invoice(
            db, ws.id, contact.id, total=500, status="sent", due_date=None, currency="USD"
        )
        eur = await _invoice(
            db, ws.id, contact.id, total=700, status=invoice_status, due_date=None, currency="EUR"
        )
        await _job(db, ws.id, contact.id, invoice_id=usd.id, start=start)
        await _job(db, ws.id, contact.id, invoice_id=eur.id, start=start)
        with pytest.raises(HTTPException) as exc:
            await ReportingService(db).job_pnl_summary(ws.id)
        assert exc.value.status_code == 422
