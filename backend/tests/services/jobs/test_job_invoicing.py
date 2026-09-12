"""Billing a completed job: :meth:`JobService.create_invoice_from_job`.

Hits the real database (marked ``integration``; run with ``-m integration``).
Each test opens an ``AsyncSessionLocal`` and never commits, so the transaction
rolls back on close and the dev database stays clean.

The guards matter more than the happy path here: an invoice is a customer-facing
money document, so billing work that never happened, or billing the same job
twice, is worse than refusing to create anything.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobLineItem, JobStatus
from app.models.workspace import Workspace
from app.services.exceptions import ConflictError
from app.services.jobs import JobService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the asyncpg pool around each test to avoid closed-loop reuse."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Billing", slug=f"bill-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _contact(db, workspace_id: uuid.UUID) -> Contact:
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Grace",
        last_name="Hopper",
        email=f"grace-{uuid.uuid4().hex[:6]}@example.com",
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    return contact


async def _job(
    db,
    workspace_id: uuid.UUID,
    contact_id: int,
    *,
    status: JobStatus = JobStatus.COMPLETED,
    tax_rate: Decimal = Decimal("0.00"),
    priced: bool = True,
) -> Job:
    start = datetime.now(UTC) - timedelta(days=1)
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact_id,
        title="Gutter clean",
        description="Rear elevation",
        status=status,
        scheduled_start=start,
        scheduled_end=start + timedelta(hours=2),
        tax_rate=tax_rate,
    )
    db.add(job)
    await db.flush()

    if priced:
        db.add_all(
            [
                JobLineItem(
                    job_id=job.id,
                    name="Gutter clearing",
                    description="Two storey",
                    quantity=Decimal("2.00"),
                    unit_price=Decimal("150.00"),
                    taxable=True,
                    position=0,
                ),
                JobLineItem(
                    job_id=job.id,
                    name="Callout",
                    quantity=Decimal("1.00"),
                    unit_price=Decimal("50.00"),
                    taxable=False,
                    position=1,
                ),
            ]
        )
        await db.flush()
    return job


async def test_bills_a_completed_job_from_its_priced_scope() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id, tax_rate=Decimal("10.00"))

        invoice = await JobService(db).create_invoice_from_job(job.id, ws.id)

        assert invoice.contact_id == contact.id
        assert invoice.status == "draft"
        assert {item.name for item in invoice.line_items} == {"Gutter clearing", "Callout"}
        # 2 x 150 + 1 x 50 = 350 subtotal; only the 300 is taxable, so tax is 30.
        assert invoice.subtotal == 350.0
        assert invoice.tax_amount == 30.0
        assert invoice.total == 380.0
        # The link is what makes a second invoice impossible.
        assert job.invoice_id == invoice.id


async def test_passes_through_the_due_date() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)
        due = date.today() + timedelta(days=14)

        invoice = await JobService(db).create_invoice_from_job(job.id, ws.id, due_date=due)

        assert invoice.due_date == due


@pytest.mark.parametrize(
    "status",
    [JobStatus.SCHEDULED, JobStatus.IN_PROGRESS, JobStatus.UNSCHEDULED, JobStatus.CANCELLED],
)
async def test_refuses_to_bill_work_that_is_not_finished(status: JobStatus) -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id, status=status)

        with pytest.raises(ConflictError, match="completed"):
            await JobService(db).create_invoice_from_job(job.id, ws.id)

        assert job.invoice_id is None


async def test_refuses_to_bill_the_same_job_twice() -> None:
    """The guard against a double-click, or two operators on the same job."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)
        service = JobService(db)

        first = await service.create_invoice_from_job(job.id, ws.id)

        with pytest.raises(ConflictError, match="already linked"):
            await service.create_invoice_from_job(job.id, ws.id)

        assert job.invoice_id == first.id


async def test_refuses_a_job_with_no_priced_scope() -> None:
    """A zero-total invoice reads as already paid, so refuse rather than send one."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id, priced=False)

        with pytest.raises(ConflictError, match="priced line items"):
            await JobService(db).create_invoice_from_job(job.id, ws.id)

        assert job.invoice_id is None


async def test_cannot_bill_a_job_from_another_workspace() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        other = await _workspace(db)
        contact = await _contact(db, ws.id)
        job = await _job(db, ws.id, contact.id)

        with pytest.raises(Exception) as excinfo:
            await JobService(db).create_invoice_from_job(job.id, other.id)

        assert getattr(excinfo.value, "status_code", None) == 404
        assert job.invoice_id is None
