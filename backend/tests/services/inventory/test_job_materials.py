"""Integration tests for job materials (the jobs ↔ inventory bridge).

Marked ``integration`` (run with ``-m integration``); each test opens an
``AsyncSessionLocal`` and never commits.

Coverage: the consume → list → profitability round trip, the guarantee that
consuming stock writes **no** ``JobExpense`` (so materials cannot double-count),
undo-as-compensating-entry, the duplicate-line guard, and cross-workspace 404s.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.inventory import InventoryItem
from app.models.job_costing import JobExpense
from app.models.workspace import Workspace
from app.schemas.inventory import JobMaterialCreate, ReceiveStockRequest
from app.services.exceptions import ConflictError
from app.services.inventory import StockService
from app.services.jobs import JobCostingService, JobMaterialsService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Materials", slug=f"mat-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _job(db, workspace_id: uuid.UUID) -> Job:
    email = f"mat-{uuid.uuid4().hex[:6]}@example.com"
    contact = Contact(
        workspace_id=workspace_id,
        first_name="Ada",
        email=email,
        email_hash=hash_value(email),
        phone_number=f"+1555{uuid.uuid4().int % 10_000_000:07d}",
    )
    db.add(contact)
    await db.flush()
    job = Job(
        workspace_id=workspace_id,
        contact_id=contact.id,
        title="Softwash siding",
        status=JobStatus.IN_PROGRESS,
    )
    db.add(job)
    await db.flush()
    return job


async def _stocked_item(db, workspace_id: uuid.UUID, quantity: float, cost: float):
    item = InventoryItem(workspace_id=workspace_id, name="Soap", unit_of_measure="gallon")
    db.add(item)
    await db.flush()
    await StockService(db).receive(
        workspace_id, item.id, ReceiveStockRequest(quantity=quantity, unit_cost=cost)
    )
    return item


async def test_consume_then_list_then_profitability() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        job = await _job(db, ws.id)
        item = await _stocked_item(db, ws.id, quantity=20, cost=6.00)
        svc = JobMaterialsService(db)

        posted = await svc.consume_for_job(
            job.id, ws.id, JobMaterialCreate(item_id=item.id, quantity=3)
        )
        assert posted.reason == "job_usage"
        assert posted.unit_cost == 6.0
        assert posted.value_delta == -18.0

        listed = await svc.list_for_job(job.id, ws.id)
        assert len(listed.items) == 1
        assert listed.total_material_cost == 18.0

        profitability = await JobCostingService(db).get_profitability(job.id, ws.id)
        assert profitability.material_cost == 18.0
        assert profitability.total_cost == 18.0


async def test_consuming_stock_writes_no_job_expense() -> None:
    """The single rule that keeps materials from being counted twice."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        job = await _job(db, ws.id)
        item = await _stocked_item(db, ws.id, quantity=10, cost=5.00)

        await JobMaterialsService(db).consume_for_job(
            job.id, ws.id, JobMaterialCreate(item_id=item.id, quantity=2)
        )

        expenses = (
            await db.execute(
                select(func.count(JobExpense.id)).where(
                    JobExpense.workspace_id == ws.id, JobExpense.job_id == job.id
                )
            )
        ).scalar_one()
        assert expenses == 0


async def test_costs_are_redacted_without_billing_read() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        job = await _job(db, ws.id)
        item = await _stocked_item(db, ws.id, quantity=10, cost=5.00)
        svc = JobMaterialsService(db)
        await svc.consume_for_job(job.id, ws.id, JobMaterialCreate(item_id=item.id, quantity=2))

        listed = await svc.list_for_job(job.id, ws.id, include_costs=False)
        # A field tech sees the quantity they burned, not what it cost.
        assert listed.items[0].quantity_delta == -2.0
        assert listed.items[0].unit_cost == 0.0
        assert listed.items[0].value_delta == 0.0
        assert listed.total_material_cost == 0.0


async def test_removing_a_material_returns_it_without_deleting_history() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        job = await _job(db, ws.id)
        item = await _stocked_item(db, ws.id, quantity=10, cost=5.00)
        svc = JobMaterialsService(db)

        posted = await svc.consume_for_job(
            job.id, ws.id, JobMaterialCreate(item_id=item.id, quantity=4)
        )
        returned = await svc.return_for_job(job.id, ws.id, posted.id)
        assert returned.reason == "return_to_stock"
        assert returned.quantity_delta == 4.0
        # Returned at the cost it left with, so the job nets to zero.
        assert returned.unit_cost == 5.0

        listed = await svc.list_for_job(job.id, ws.id)
        assert len(listed.items) == 2  # both the usage and its correction survive
        assert listed.total_material_cost == 0.0

        profitability = await JobCostingService(db).get_profitability(job.id, ws.id)
        assert profitability.material_cost == 0.0

        # A second undo has nothing left to return.
        with pytest.raises(ConflictError) as excinfo:
            await svc.return_for_job(job.id, ws.id, posted.id)
        assert excinfo.value.code == "material_already_returned"


async def test_duplicate_material_line_is_refused() -> None:
    """The retry guard: one job_usage row per (job, item), enforced in SQL too."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        job = await _job(db, ws.id)
        item = await _stocked_item(db, ws.id, quantity=10, cost=5.00)
        svc = JobMaterialsService(db)

        await svc.consume_for_job(job.id, ws.id, JobMaterialCreate(item_id=item.id, quantity=1))
        with pytest.raises(ConflictError) as excinfo:
            await svc.consume_for_job(job.id, ws.id, JobMaterialCreate(item_id=item.id, quantity=1))
        assert excinfo.value.code == "material_already_recorded"


async def test_cannot_consume_onto_another_workspaces_job() -> None:
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        their_job = await _job(db, theirs.id)
        my_item = await _stocked_item(db, mine.id, quantity=10, cost=5.00)

        with pytest.raises(HTTPException) as excinfo:
            await JobMaterialsService(db).consume_for_job(
                their_job.id, mine.id, JobMaterialCreate(item_id=my_item.id, quantity=1)
            )
        assert excinfo.value.status_code == 404
