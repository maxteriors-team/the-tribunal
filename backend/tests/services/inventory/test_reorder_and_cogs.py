"""Integration tests for reorder flagging and COGS reporting.

Marked ``integration`` (run with ``-m integration``); each test opens an
``AsyncSessionLocal`` and never commits, so the dev database stays clean.

Coverage: low-stock aggregation across locations, the "unmanaged items never
alert" rule, the reorder-point suggestion formula, COGS grouping, the shrinkage
split, ending inventory value, and per-job material cost net of returns.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import update

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.catalog import CatalogItem
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus
from app.models.inventory import InventoryItem, InventoryLedgerEntry, InventoryLocation
from app.models.workspace import Workspace
from app.schemas.inventory import ReceiveStockRequest
from app.services.inventory import COGSService, ReorderService, StockService
from app.services.inventory.locations import ensure_default_location

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Reorder", slug=f"reorder-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _item(db, workspace_id: uuid.UUID, name: str, **kwargs) -> InventoryItem:
    item = InventoryItem(workspace_id=workspace_id, name=name, **kwargs)
    db.add(item)
    await db.flush()
    return item


async def _job(db, workspace_id: uuid.UUID, title: str = "Wash driveway") -> Job:
    email = f"job-{uuid.uuid4().hex[:6]}@example.com"
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
        title=title,
        status=JobStatus.COMPLETED,
    )
    db.add(job)
    await db.flush()
    return job


async def _backdate_usage(db, workspace_id: uuid.UUID, days: int) -> None:
    """Age every consumption row so a trailing-window average has a denominator."""
    moment = datetime.now(UTC) - timedelta(days=days)
    await db.execute(
        update(InventoryLedgerEntry)
        .where(
            InventoryLedgerEntry.workspace_id == workspace_id,
            InventoryLedgerEntry.reason == "job_usage",
        )
        .values(created_at=moment, occurred_at=moment)
    )


async def test_low_stock_aggregates_across_locations() -> None:
    """A truck being empty is not a reorder signal while the warehouse is full."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id, "Gutter guard", reorder_point=10, unit_of_measure="ft")
        stock = StockService(db)
        warehouse = await ensure_default_location(db, ws.id)
        truck = InventoryLocation(workspace_id=ws.id, name="Truck 2", kind="truck")
        db.add(truck)
        await db.flush()

        await stock.receive(
            ws.id,
            item.id,
            ReceiveStockRequest(quantity=40, unit_cost=1.00, location_id=warehouse.id),
        )
        # Truck holds nothing; workspace total is 40 and well above the trigger.
        report = await ReorderService(db).low_stock(ws.id)
        assert report.total == 0

        await stock.consume(ws.id, item.id, 35, location_id=warehouse.id)
        await stock.receive(
            ws.id, item.id, ReceiveStockRequest(quantity=1, unit_cost=1.00, location_id=truck.id)
        )
        report = await ReorderService(db).low_stock(ws.id)
        assert report.total == 1
        row = report.items[0]
        assert row.item_id == item.id
        assert row.quantity_on_hand == 6.0
        assert row.shortfall == 4.0


async def test_items_without_a_reorder_point_never_alert() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        unmanaged = await _item(db, ws.id, "Shop rags")
        await StockService(db).receive(
            ws.id, unmanaged.id, ReceiveStockRequest(quantity=0.5, unit_cost=1.00)
        )

        report = await ReorderService(db).low_stock(ws.id)
        assert report.total == 0


async def test_suggested_reorder_point_uses_usage_times_lead_time() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(
            db,
            ws.id,
            "Sodium hypochlorite",
            unit_of_measure="gallon",
            lead_time_days=7,
            safety_stock=5,
        )
        stock = StockService(db)
        await stock.receive(ws.id, item.id, ReceiveStockRequest(quantity=200, unit_cost=4.00))
        # 90 gallons over a 90-day window = 1/day.
        await stock.consume(ws.id, item.id, 90)
        await _backdate_usage(db, ws.id, days=1)

        suggestion = await ReorderService(db).suggest_reorder_point(ws.id, item.id)
        assert suggestion.avg_daily_usage == pytest.approx(1.0)
        # 1/day x 7-day lead time + 5 safety stock.
        assert suggestion.suggested_reorder_point == pytest.approx(12.0)
        assert suggestion.stored_reorder_point is None


async def test_suggestion_is_none_without_a_lead_time() -> None:
    """No lead time means no honest answer — a guess would be a wrong number."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id, "Mystery part")
        await StockService(db).receive(
            ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=1.00)
        )
        await StockService(db).consume(ws.id, item.id, 5)

        suggestion = await ReorderService(db).suggest_reorder_point(ws.id, item.id)
        assert suggestion.suggested_reorder_point is None


async def test_cogs_splits_shrinkage_and_groups_by_item() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        soap = await _item(db, ws.id, "Soap", unit_of_measure="gallon")
        sealant = await _item(db, ws.id, "Sealant", unit_of_measure="gallon")
        stock = StockService(db)

        await stock.receive(ws.id, soap.id, ReceiveStockRequest(quantity=10, unit_cost=5.00))
        await stock.receive(ws.id, sealant.id, ReceiveStockRequest(quantity=10, unit_cost=20.00))
        await stock.consume(ws.id, soap.id, 4)  # 20.00
        await stock.consume(ws.id, sealant.id, 2)  # 40.00
        await stock.write_off(ws.id, soap.id, 1)  # 5.00 shrinkage

        today = date.today()
        report = await COGSService(db).cogs(ws.id, date_from=today, date_to=today)
        assert report.total_cogs == 60.0
        # Waste is reported on its own line, never inside gross margin.
        assert report.shrinkage_cost == 5.0
        # 10-4-1 soap at 5 + 10-2 sealant at 20 = 25 + 160.
        assert report.ending_inventory_value == 185.0

        by_item = {row.label: row.cogs for row in report.breakdown}
        assert by_item == {"Sealant": 40.0, "Soap": 20.0}
        # Largest slice first so the UI does not have to re-sort.
        assert report.breakdown[0].label == "Sealant"


async def test_cogs_groups_by_service_category_and_job() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        catalog_item = CatalogItem(
            workspace_id=ws.id, name="Roof wash", unit_price=100, service_category="roof"
        )
        db.add(catalog_item)
        await db.flush()

        tracked = await _item(
            db,
            ws.id,
            "Roof mix",
            catalog_item_id=catalog_item.id,
        )
        uncategorized = await _item(db, ws.id, "Generic mix")
        direct = await _item(db, ws.id, "Soft-wash mix", service_category="Exterior Cleaning")
        job = await _job(db, ws.id, title="Roof wash on Elm")
        stock = StockService(db)

        await stock.receive(ws.id, tracked.id, ReceiveStockRequest(quantity=10, unit_cost=3.00))
        await stock.receive(
            ws.id, uncategorized.id, ReceiveStockRequest(quantity=10, unit_cost=2.00)
        )
        await stock.receive(ws.id, direct.id, ReceiveStockRequest(quantity=2, unit_cost=4.00))
        await stock.consume(
            ws.id, tracked.id, 5, reference_type="job", reference_id=job.id
        )  # 15.00
        await stock.consume(ws.id, uncategorized.id, 5)  # 10.00
        await stock.consume(ws.id, direct.id, 2)  # 8.00

        today = date.today()
        svc = COGSService(db)

        by_category = await svc.cogs(
            ws.id, date_from=today, date_to=today, group_by="service_category"
        )
        slices = {row.label: row.cogs for row in by_category.breakdown}
        assert slices == {
            "roof": 15.0,
            "Uncategorized": 10.0,
            "Exterior Cleaning": 8.0,
        }

        by_job = await svc.cogs(ws.id, date_from=today, date_to=today, group_by="job")
        # Only the job-referenced consumption appears in a job breakdown.
        assert [(row.label, row.cogs) for row in by_job.breakdown] == [("Roof wash on Elm", 15.0)]


async def test_material_cost_by_job_is_net_of_returns() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id, "Sealant")
        job = await _job(db, ws.id)
        stock = StockService(db)

        await stock.receive(ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=10.00))
        used = await stock.consume(ws.id, item.id, 3, reference_type="job", reference_id=job.id)
        costs = await COGSService(db).material_cost_by_job(ws.id, [job.id])
        assert costs[job.id] == 30.0

        await stock.return_to_stock(
            ws.id,
            item.id,
            3,
            unit_cost=float(used.unit_cost),
            location_id=used.location_id,
            reference_type="job",
            reference_id=job.id,
        )
        costs = await COGSService(db).material_cost_by_job(ws.id, [job.id])
        # Undo returns the job to zero material cost, without deleting history.
        assert costs[job.id] == 0.0


async def test_cogs_ignores_other_workspaces() -> None:
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        their_item = await _item(db, theirs.id, "Their soap")
        stock = StockService(db)
        await stock.receive(
            theirs.id, their_item.id, ReceiveStockRequest(quantity=10, unit_cost=5.00)
        )
        await stock.consume(theirs.id, their_item.id, 5)

        today = date.today()
        report = await COGSService(db).cogs(mine.id, date_from=today, date_to=today)
        assert report.total_cogs == 0.0
        assert report.ending_inventory_value == 0.0
        assert report.breakdown == []
