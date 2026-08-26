"""Integration coverage for Bistro reservation, consumption, and reusable deployment."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.inventory import (
    InventoryItem,
    InventoryJobAllocation,
    InventoryLedgerEntry,
)
from app.models.workspace import Workspace
from app.schemas.inventory import (
    CompleteJobInventoryRequest,
    InventoryAllocationActual,
    ReceiveStockRequest,
)
from app.schemas.proposal_wizard import FulfillmentPart
from app.services.exceptions import ConflictError
from app.services.inventory import (
    InventoryService,
    JobAllocationService,
    QuoteInventoryAvailabilityService,
    ReorderService,
    StockService,
)
from app.services.jobs import JobService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db, name: str = "Bistro") -> Workspace:
    workspace = Workspace(id=uuid.uuid4(), name=name, slug=f"bistro-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    await db.flush()
    return workspace


async def _job(db, workspace_id: uuid.UUID) -> Job:
    email = f"bistro-{uuid.uuid4().hex[:6]}@example.com"
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
        title="Install Bistro lighting",
        status=JobStatus.IN_PROGRESS,
    )
    db.add(job)
    await db.flush()
    return job


async def _stocked_item(
    db,
    workspace_id: uuid.UUID,
    *,
    sku: str,
    name: str,
    unit: str,
    quantity: float,
    cost: float,
) -> InventoryItem:
    item = InventoryItem(
        workspace_id=workspace_id,
        sku=sku,
        name=name,
        unit_of_measure=unit,
    )
    db.add(item)
    await db.flush()
    await StockService(db).receive(
        workspace_id,
        item.id,
        ReceiveStockRequest(quantity=quantity, unit_cost=cost),
    )
    return item


def _completion(plan, actuals: dict[str, float]) -> CompleteJobInventoryRequest:
    return CompleteJobInventoryRequest(
        allocations=[
            InventoryAllocationActual(
                allocation_id=line.id,
                actual_quantity=actuals[line.sku],
            )
            for line in plan.allocations
        ]
    )


async def test_permanent_actual_usage_posts_weighted_cogs_once() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db)
        job = await _job(db, workspace.id)
        await _stocked_item(
            db,
            workspace.id,
            sku="BISTRO-PERM-FT",
            name="Permanent Bistro footage",
            unit="ft",
            quantity=200,
            cost=3,
        )
        await _stocked_item(
            db,
            workspace.id,
            sku="BISTRO-PERM-POLE",
            name="Permanent Bistro pole",
            unit="each",
            quantity=10,
            cost=20,
        )
        service = JobAllocationService(db)
        await service.reserve(
            workspace.id,
            job.id,
            [
                FulfillmentPart(sku="BISTRO-PERM-FT", qty=180),
                FulfillmentPart(sku="BISTRO-PERM-POLE", qty=4),
            ],
        )
        planned = await service.get_plan(workspace.id, job.id)
        by_sku = {line.sku: line for line in planned.allocations}
        assert by_sku["BISTRO-PERM-FT"].quantity_reserved == 180
        assert by_sku["BISTRO-PERM-FT"].available_to_promise == 20

        payload = _completion(
            planned,
            {"BISTRO-PERM-FT": 165, "BISTRO-PERM-POLE": 4},
        )
        completed = await service.complete(workspace.id, job.id, payload)
        completed_by_sku = {line.sku: line for line in completed.allocations}
        assert completed.job_status == "completed"
        assert completed_by_sku["BISTRO-PERM-FT"].status == "consumed"
        assert completed_by_sku["BISTRO-PERM-FT"].quantity_on_hand == 35
        assert completed_by_sku["BISTRO-PERM-FT"].quantity_reserved == 0
        assert completed_by_sku["BISTRO-PERM-POLE"].quantity_on_hand == 6

        job_usage = list(
            (
                await db.execute(
                    select(InventoryLedgerEntry).where(
                        InventoryLedgerEntry.workspace_id == workspace.id,
                        InventoryLedgerEntry.reference_id == job.id,
                        InventoryLedgerEntry.reason == "job_usage",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(job_usage) == 2
        assert sum(float(row.value_delta) for row in job_usage) == -575

        retried = await service.complete(workspace.id, job.id, payload)
        assert retried.job_status == "completed"
        usage_count = await db.scalar(
            select(func.count(InventoryLedgerEntry.id)).where(
                InventoryLedgerEntry.workspace_id == workspace.id,
                InventoryLedgerEntry.reference_id == job.id,
                InventoryLedgerEntry.reason == "job_usage",
            )
        )
        assert usage_count == 2
        with pytest.raises(ConflictError) as excinfo:
            await service.complete(
                workspace.id,
                job.id,
                _completion(
                    planned,
                    {"BISTRO-PERM-FT": 166, "BISTRO-PERM-POLE": 4},
                ),
            )
        assert excinfo.value.code == "inventory_completion_conflict"


async def test_temporary_equipment_deploys_and_returns_without_cogs() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db)
        job = await _job(db, workspace.id)
        await _stocked_item(
            db,
            workspace.id,
            sku="BISTRO-TEMP-200FT",
            name="Temporary Bistro set",
            unit="set",
            quantity=3,
            cost=725,
        )
        await _stocked_item(
            db,
            workspace.id,
            sku="BISTRO-TEMP-POLE",
            name="Temporary Bistro pole",
            unit="each",
            quantity=10,
            cost=80,
        )
        service = JobAllocationService(db)
        await service.reserve(
            workspace.id,
            job.id,
            [
                FulfillmentPart(sku="BISTRO-TEMP-200FT", qty=2, inventory_behavior="reusable"),
                FulfillmentPart(sku="BISTRO-TEMP-POLE", qty=4, inventory_behavior="reusable"),
            ],
        )
        planned = await service.get_plan(workspace.id, job.id)
        completed = await service.complete(
            workspace.id,
            job.id,
            _completion(planned, {"BISTRO-TEMP-200FT": 2, "BISTRO-TEMP-POLE": 4}),
        )
        by_sku = {line.sku: line for line in completed.allocations}
        assert by_sku["BISTRO-TEMP-200FT"].status == "deployed"
        assert by_sku["BISTRO-TEMP-200FT"].quantity_on_hand == 3
        assert by_sku["BISTRO-TEMP-200FT"].quantity_deployed == 2
        assert by_sku["BISTRO-TEMP-200FT"].available_to_promise == 1
        assert not await db.scalar(
            select(InventoryLedgerEntry.id).where(
                InventoryLedgerEntry.reference_id == job.id,
                InventoryLedgerEntry.reason == "job_usage",
            )
        )

        for line in completed.allocations:
            returned = await service.return_reusable(workspace.id, job.id, line.id)
            assert returned.status == "returned"
            again = await service.return_reusable(workspace.id, job.id, line.id)
            assert again.status == "returned"
        returned_plan = await service.get_plan(workspace.id, job.id)
        returned_by_sku = {line.sku: line for line in returned_plan.allocations}
        assert returned_by_sku["BISTRO-TEMP-200FT"].quantity_on_hand == 3
        assert returned_by_sku["BISTRO-TEMP-200FT"].quantity_deployed == 0
        assert returned_by_sku["BISTRO-TEMP-200FT"].available_to_promise == 3


async def test_shortage_blocks_every_consumption_and_cross_workspace_reads() -> None:
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db, "Mine")
        theirs = await _workspace(db, "Theirs")
        job = await _job(db, mine.id)
        await _stocked_item(
            db,
            mine.id,
            sku="BISTRO-PERM-FT",
            name="Permanent Bistro footage",
            unit="ft",
            quantity=10,
            cost=3,
        )
        await _stocked_item(
            db,
            mine.id,
            sku="BISTRO-PERM-POLE",
            name="Permanent Bistro pole",
            unit="each",
            quantity=1,
            cost=20,
        )
        service = JobAllocationService(db)
        await service.reserve(
            mine.id,
            job.id,
            [
                FulfillmentPart(sku="BISTRO-PERM-FT", qty=10),
                FulfillmentPart(sku="BISTRO-PERM-POLE", qty=1),
            ],
        )
        plan = await service.get_plan(mine.id, job.id)
        with pytest.raises(ConflictError) as excinfo:
            await service.complete(
                mine.id,
                job.id,
                _completion(plan, {"BISTRO-PERM-FT": 10, "BISTRO-PERM-POLE": 2}),
            )
        assert excinfo.value.code == "insufficient_inventory"
        assert not await db.scalar(
            select(InventoryLedgerEntry.id).where(
                InventoryLedgerEntry.reference_id == job.id,
                InventoryLedgerEntry.reason == "job_usage",
            )
        )
        after_shortage = await service.get_plan(mine.id, job.id)
        assert all(line.status == "reserved" for line in after_shortage.allocations)

        with pytest.raises(HTTPException) as excinfo:
            await service.get_plan(theirs.id, job.id)
        assert excinfo.value.status_code == 404


async def test_cancellation_releases_reservations_and_consumed_history_blocks_delete() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db)
        reserved_job = await _job(db, workspace.id)
        await _stocked_item(
            db,
            workspace.id,
            sku="BISTRO-PERM-FT",
            name="Permanent Bistro footage",
            unit="ft",
            quantity=20,
            cost=3,
        )
        service = JobAllocationService(db)
        await service.reserve(
            workspace.id,
            reserved_job.id,
            [FulfillmentPart(sku="BISTRO-PERM-FT", qty=10)],
        )
        with pytest.raises(ConflictError) as excinfo:
            await JobService(db).update(
                reserved_job.id, workspace.id, {"status": JobStatus.COMPLETED}
            )
        assert excinfo.value.code == "inventory_confirmation_required"

        await JobService(db).update(reserved_job.id, workspace.id, {"status": JobStatus.CANCELLED})
        released = await service.get_plan(workspace.id, reserved_job.id)
        assert released.allocations[0].status == "released"
        assert released.allocations[0].available_to_promise == 20

        consumed_job = await _job(db, workspace.id)
        await service.reserve(
            workspace.id,
            consumed_job.id,
            [FulfillmentPart(sku="BISTRO-PERM-FT", qty=5)],
        )
        plan = await service.get_plan(workspace.id, consumed_job.id)
        await service.complete(
            workspace.id,
            consumed_job.id,
            _completion(plan, {"BISTRO-PERM-FT": 5}),
        )
        with pytest.raises(ConflictError) as excinfo:
            await service.assert_job_deletable(workspace.id, consumed_job.id)
        assert excinfo.value.code == "job_inventory_history"


async def test_inventory_reads_reorder_and_quotes_use_available_to_promise() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db)
        job = await _job(db, workspace.id)
        item = await _stocked_item(
            db,
            workspace.id,
            sku="BISTRO-PERM-FT",
            name="Permanent Bistro footage",
            unit="ft",
            quantity=10,
            cost=3,
        )
        item.reorder_point = 7
        await db.flush()
        await JobAllocationService(db).reserve(
            workspace.id,
            job.id,
            [FulfillmentPart(sku="BISTRO-PERM-FT", qty=4)],
        )

        item_response = await InventoryService(db).get_item(workspace.id, item.id)
        assert item_response.quantity_on_hand == 10
        assert item_response.quantity_reserved == 4
        assert item_response.available_to_promise == 6
        assert item_response.is_low_stock is True

        report = await ReorderService(db).low_stock(workspace.id)
        assert report.total == 1
        assert report.items[0].quantity_on_hand == 10
        assert report.items[0].quantity_reserved == 4
        assert report.items[0].available_to_promise == 6
        assert report.items[0].shortfall == 1

        availability = await QuoteInventoryAvailabilityService(db).check(
            workspace.id,
            [FulfillmentPart(sku="BISTRO-PERM-FT", qty=7)],
        )
        assert availability.connected is True
        assert availability.is_available is False
        assert availability.items[0].quantity_on_hand == 10
        assert availability.items[0].quantity_reserved == 4
        assert availability.items[0].available_to_promise == 6
        assert availability.items[0].shortage_quantity == 1


async def test_concurrent_reservations_cannot_overpromise_stock() -> None:
    async with AsyncSessionLocal() as setup_db:
        workspace = await _workspace(setup_db, "Concurrent Bistro")
        first_job = await _job(setup_db, workspace.id)
        second_job = await _job(setup_db, workspace.id)
        item = await _stocked_item(
            setup_db,
            workspace.id,
            sku="BISTRO-TEMP-200FT",
            name="Temporary Bistro set",
            unit="set",
            quantity=5,
            cost=725,
        )
        workspace_id = workspace.id
        job_ids = (first_job.id, second_job.id)
        item_id = item.id
        await setup_db.commit()

    async def reserve(job_id: uuid.UUID) -> str:
        async with AsyncSessionLocal() as db:
            try:
                await JobAllocationService(db).reserve(
                    workspace_id,
                    job_id,
                    [
                        FulfillmentPart(
                            sku="BISTRO-TEMP-200FT",
                            qty=4,
                            inventory_behavior="reusable",
                        )
                    ],
                )
                await db.commit()
                return "reserved"
            except ConflictError:
                await db.rollback()
                return "shortage"

    outcomes = await asyncio.gather(*(reserve(job_id) for job_id in job_ids))
    assert sorted(outcomes) == ["reserved", "shortage"]

    async with AsyncSessionLocal() as verify_db:
        allocations = await verify_db.scalar(
            select(func.count())
            .select_from(InventoryJobAllocation)
            .where(
                InventoryJobAllocation.workspace_id == workspace_id,
                InventoryJobAllocation.item_id == item_id,
                InventoryJobAllocation.status == "reserved",
            )
        )
        assert allocations == 1
        workspace = await verify_db.get(Workspace, workspace_id)
        assert workspace is not None
        await verify_db.delete(workspace)
        await verify_db.commit()
