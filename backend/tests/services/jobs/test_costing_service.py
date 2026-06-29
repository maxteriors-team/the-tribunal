"""Integration tests for :class:`app.services.jobs.JobCostingService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: clock in/out (and the single-running-timer guard), manual time
entries, expenses, profitability math (revenue from the linked invoice minus
labor and expenses), and cross-workspace 404s.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus, Technician
from app.models.invoice import Invoice
from app.models.workspace import Workspace
from app.schemas.job_costing import (
    ClockInRequest,
    JobExpenseCreate,
    TimeEntryCreate,
)
from app.services.exceptions import ConflictError
from app.services.jobs import JobCostingService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db):
    ws = Workspace(id=uuid.uuid4(), name="Costing", slug=f"cost-{uuid.uuid4().hex[:8]}")
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


async def _job(db, workspace_id: uuid.UUID, contact_id: int, *, invoice_id=None) -> Job:
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact_id,
        title="Install lighting",
        status=JobStatus.SCHEDULED,
        invoice_id=invoice_id,
    )
    db.add(job)
    await db.flush()
    return job


async def _invoice(db, workspace_id: uuid.UUID, contact_id: int, total: float) -> Invoice:
    invoice = Invoice(
        workspace_id=workspace_id,
        contact_id=contact_id,
        number=f"INV-{uuid.uuid4().hex[:6]}",
        subtotal=total,
        total=total,
        status="sent",
        currency="USD",
    )
    db.add(invoice)
    await db.flush()
    return invoice


async def _technician(db, workspace_id: uuid.UUID) -> Technician:
    tech = Technician(workspace_id=workspace_id, name=f"Tech {uuid.uuid4().hex[:6]}")
    db.add(tech)
    await db.flush()
    return tech


async def test_clock_in_then_out_records_duration() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)
        svc = JobCostingService(db)

        entry = await svc.clock_in(job.id, ws.id, ClockInRequest(rate=100.0))
        assert entry.ended_at is None
        assert entry.duration_hours == 0.0

        # A second clock-in while one is running is rejected.
        with pytest.raises(ConflictError):
            await svc.clock_in(job.id, ws.id, ClockInRequest())

        closed = await svc.clock_out(job.id, ws.id)
        assert closed.id == entry.id
        assert closed.ended_at is not None
        # Clock-out with no running timer is rejected.
        with pytest.raises(ConflictError):
            await svc.clock_out(job.id, ws.id)


async def test_manual_time_entry_computes_labor_cost() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)
        tech = await _technician(db, ws.id)
        svc = JobCostingService(db)

        start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        entry = await svc.add_time_entry(
            job.id,
            ws.id,
            TimeEntryCreate(
                technician_id=tech.id,
                started_at=start,
                ended_at=start + timedelta(hours=3),
                rate=80.0,
            ),
        )
        assert entry.duration_hours == 3.0
        assert entry.labor_cost == 240.0

        # End before start is rejected.
        with pytest.raises(ConflictError):
            await svc.add_time_entry(
                job.id,
                ws.id,
                TimeEntryCreate(started_at=start, ended_at=start - timedelta(hours=1)),
            )


async def test_expense_crud_and_listing() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)
        svc = JobCostingService(db)

        e1 = await svc.add_expense(
            job.id,
            ws.id,
            JobExpenseCreate(description="Fixtures", amount=120.0, category="materials"),
        )
        await svc.add_expense(
            job.id, ws.id, JobExpenseCreate(description="Fuel", amount=30.0, category="fuel")
        )
        listed = await svc.list_expenses(job.id, ws.id)
        assert len(listed) == 2
        assert {e.description for e in listed} == {"Fixtures", "Fuel"}

        await svc.delete_expense(job.id, ws.id, e1.id)
        assert {e.description for e in await svc.list_expenses(job.id, ws.id)} == {"Fuel"}


async def test_profitability_revenue_minus_costs() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        invoice = await _invoice(db, ws.id, contact.id, total=1000.0)
        job = await _job(db, ws.id, contact.id, invoice_id=invoice.id)
        svc = JobCostingService(db)

        start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        # 4 hours @ $90 = $360 labor.
        await svc.add_time_entry(
            job.id,
            ws.id,
            TimeEntryCreate(started_at=start, ended_at=start + timedelta(hours=4), rate=90.0),
        )
        # $200 expenses.
        await svc.add_expense(job.id, ws.id, JobExpenseCreate(description="Parts", amount=200.0))

        pnl = await svc.get_profitability(job.id, ws.id)
        assert pnl.revenue == 1000.0
        assert pnl.labor_cost == 360.0
        assert pnl.expense_cost == 200.0
        assert pnl.total_cost == 560.0
        assert pnl.profit == 440.0
        assert pnl.margin == 0.44
        assert pnl.total_hours == 4.0
        assert pnl.open_timer is False


async def test_profitability_without_invoice_is_zero_revenue() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)  # no invoice link
        svc = JobCostingService(db)

        await svc.add_expense(job.id, ws.id, JobExpenseCreate(description="Parts", amount=50.0))
        pnl = await svc.get_profitability(job.id, ws.id)
        assert pnl.revenue == 0.0
        assert pnl.expense_cost == 50.0
        assert pnl.profit == -50.0
        assert pnl.margin is None


async def test_open_timer_flag_while_running() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)
        svc = JobCostingService(db)

        await svc.clock_in(job.id, ws.id, ClockInRequest(rate=50.0))
        pnl = await svc.get_profitability(job.id, ws.id)
        assert pnl.open_timer is True
        # A running entry contributes no labor cost yet.
        assert pnl.labor_cost == 0.0


async def test_cross_workspace_job_is_404() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        contact = await _contact(db, ws_a.id)
        job = await _job(db, ws_a.id, contact.id)
        svc = JobCostingService(db)

        with pytest.raises(HTTPException):
            await svc.get_profitability(job.id, ws_b.id)
        with pytest.raises(HTTPException):
            await svc.clock_in(job.id, ws_b.id, ClockInRequest())
