"""Integration tests for the stock posting engine.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: weighted-average math, the zero-quantity cost-retention guard, the
negative-stock refusal (and the opt-in that allows it), ledger↔cache
reconciliation over a random movement sequence, concurrent consumption of the
same bin, transfers, and cross-workspace 404s.
"""

from __future__ import annotations

import random
import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.db.session import AsyncSessionLocal, engine
from app.models.inventory import InventoryItem, InventoryLocation, InventoryStockLevel
from app.models.workspace import Workspace
from app.schemas.inventory import (
    AdjustStockRequest,
    ReceiveStockRequest,
    TransferStockRequest,
)
from app.services.exceptions import ConflictError, ValidationError
from app.services.inventory import StockService
from app.services.inventory.locations import DEFAULT_LOCATION_NAME, ensure_default_location

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db, *, allow_negative: bool = False) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        name="Stock",
        slug=f"stock-{uuid.uuid4().hex[:8]}",
        settings={"inventory": {"allow_negative_stock": allow_negative}} if allow_negative else {},
    )
    db.add(ws)
    await db.flush()
    return ws


async def _item(db, workspace_id: uuid.UUID, **kwargs) -> InventoryItem:
    item = InventoryItem(
        workspace_id=workspace_id,
        name=kwargs.pop("name", "Sodium hypochlorite"),
        unit_of_measure=kwargs.pop("unit_of_measure", "gallon"),
        **kwargs,
    )
    db.add(item)
    await db.flush()
    return item


async def _location(db, workspace_id: uuid.UUID, name: str, kind: str = "truck"):
    location = InventoryLocation(workspace_id=workspace_id, name=name, kind=kind)
    db.add(location)
    await db.flush()
    return location


async def _level(db, workspace_id: uuid.UUID, item_id: uuid.UUID, location_id: uuid.UUID):
    from sqlalchemy import select

    return (
        await db.execute(
            select(InventoryStockLevel).where(
                InventoryStockLevel.workspace_id == workspace_id,
                InventoryStockLevel.item_id == item_id,
                InventoryStockLevel.location_id == location_id,
            )
        )
    ).scalar_one()


async def test_receipt_creates_default_location_and_sets_average_cost() -> None:
    """A first receipt needs no setup: "Main" is created on the way in."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)

        entry = await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=4.00))

        location = await ensure_default_location(db, ws.id)
        assert location.name == DEFAULT_LOCATION_NAME
        assert entry.location_id == location.id
        assert Decimal(entry.quantity_after) == Decimal("10.0000")
        assert Decimal(entry.unit_cost_after) == Decimal("4.0000")
        assert Decimal(entry.value_after) == Decimal("40.00")


async def test_weighted_average_blends_two_receipts_and_values_consumption() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)

        await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=4.00))
        second = await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=6.00))
        # (10*4 + 10*6) / 20 = 5.00
        assert Decimal(second.unit_cost_after) == Decimal("5.0000")

        used = await svc.consume(ws.id, item.id, 4)
        # Outbound is valued at the server-side average, not at a client price.
        assert Decimal(used.unit_cost) == Decimal("5.0000")
        assert Decimal(used.value_delta) == Decimal("-20.00")
        assert Decimal(used.quantity_after) == Decimal("16.0000")
        assert Decimal(used.value_after) == Decimal("80.00")
        # The average survives an outbound move untouched.
        assert Decimal(used.unit_cost_after) == Decimal("5.0000")


async def test_emptying_a_bin_keeps_the_average_cost() -> None:
    """ERPNext #1473: a zeroed bin must not reset its cost to 0."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)

        await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=3, unit_cost=10.00))
        emptied = await svc.consume(ws.id, item.id, 3)
        assert Decimal(emptied.quantity_after) == Decimal("0.0000")
        assert Decimal(emptied.value_after) == Decimal("0.00")
        assert Decimal(emptied.unit_cost_after) == Decimal("10.0000")

        # The next receipt averages against the retained cost, not against 0.
        restocked = await svc.receive(
            ws.id, item.id, ReceiveStockRequest(quantity=1, unit_cost=20.00)
        )
        assert Decimal(restocked.unit_cost_after) == Decimal("20.0000")
        assert Decimal(restocked.value_after) == Decimal("20.00")


async def test_consuming_more_than_on_hand_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)
        await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=2, unit_cost=5.00))

        with pytest.raises(ConflictError) as excinfo:
            await svc.consume(ws.id, item.id, 3)
        assert excinfo.value.code == "insufficient_stock"


async def test_negative_stock_allowed_when_the_workspace_opts_in() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db, allow_negative=True)
        item = await _item(db, ws.id)
        svc = StockService(db)
        await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=1, unit_cost=5.00))

        entry = await svc.consume(ws.id, item.id, 3)
        assert Decimal(entry.quantity_after) == Decimal("-2.0000")
        # Costed at the last known average rather than at nothing.
        assert Decimal(entry.unit_cost) == Decimal("5.0000")


async def test_adjustment_posts_the_delta_from_an_absolute_count() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)
        await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=10, unit_cost=2.00))

        counted = await svc.adjust(ws.id, item.id, AdjustStockRequest(quantity_on_hand=7))
        assert Decimal(counted.quantity_delta) == Decimal("-3.0000")
        assert Decimal(counted.quantity_after) == Decimal("7.0000")
        assert counted.reason == "adjustment"

        # A count that changes nothing is a conflict, not a no-op ledger row.
        with pytest.raises(ConflictError):
            await svc.adjust(ws.id, item.id, AdjustStockRequest(quantity_on_hand=7))

        # Exactly one of count / write-off is required.
        with pytest.raises(ValidationError):
            await svc.adjust(ws.id, item.id, AdjustStockRequest())


async def test_write_off_is_shrinkage_not_consumption() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)
        await svc.receive(ws.id, item.id, ReceiveStockRequest(quantity=5, unit_cost=3.00))

        wasted = await svc.adjust(ws.id, item.id, AdjustStockRequest(write_off_quantity=2))
        assert wasted.reason == "shrinkage"
        assert Decimal(wasted.value_delta) == Decimal("-6.00")


async def test_transfer_moves_value_with_the_goods() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)
        warehouse = await ensure_default_location(db, ws.id)
        truck = await _location(db, ws.id, "Truck 1")

        await svc.receive(
            ws.id,
            item.id,
            ReceiveStockRequest(quantity=10, unit_cost=7.00, location_id=warehouse.id),
        )
        out_entry, in_entry = await svc.transfer(
            ws.id,
            TransferStockRequest(
                item_id=item.id,
                from_location_id=warehouse.id,
                to_location_id=truck.id,
                quantity=4,
            ),
        )
        assert out_entry.reason == "transfer_out"
        assert in_entry.reason == "transfer_in"
        # Cost rides along: the truck's average equals the warehouse's.
        assert Decimal(in_entry.unit_cost) == Decimal("7.0000")

        warehouse_level = await _level(db, ws.id, item.id, warehouse.id)
        truck_level = await _level(db, ws.id, item.id, truck.id)
        assert Decimal(warehouse_level.quantity_on_hand) == Decimal("6.0000")
        assert Decimal(truck_level.quantity_on_hand) == Decimal("4.0000")
        # Total workspace value is unchanged by a transfer.
        assert Decimal(warehouse_level.total_value) + Decimal(truck_level.total_value) == Decimal(
            "70.00"
        )

        with pytest.raises(ValidationError):
            await svc.transfer(
                ws.id,
                TransferStockRequest(
                    item_id=item.id,
                    from_location_id=truck.id,
                    to_location_id=truck.id,
                    quantity=1,
                ),
            )


async def test_random_movement_sequence_keeps_cache_equal_to_ledger() -> None:
    """The cache is derived state; replaying the ledger must reproduce it."""
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id)
        svc = StockService(db)
        location = await ensure_default_location(db, ws.id)
        rng = random.Random(20260803)

        await svc.receive(
            ws.id,
            item.id,
            ReceiveStockRequest(quantity=50, unit_cost=3.33, location_id=location.id),
        )
        for _ in range(25):
            level = await _level(db, ws.id, item.id, location.id)
            on_hand = Decimal(level.quantity_on_hand)
            move = rng.choice(("receive", "consume", "write_off"))
            if move == "receive":
                await svc.receive(
                    ws.id,
                    item.id,
                    ReceiveStockRequest(
                        quantity=round(rng.uniform(0.5, 12), 3),
                        unit_cost=round(rng.uniform(1, 9), 2),
                        location_id=location.id,
                    ),
                )
            elif on_hand > 1:
                quantity = round(float(on_hand) * rng.uniform(0.05, 0.6), 3)
                if move == "consume":
                    await svc.consume(ws.id, item.id, quantity, location_id=location.id)
                else:
                    await svc.write_off(ws.id, item.id, quantity, location_id=location.id)

        replayed_quantity, replayed_value = await svc.replay_level(ws.id, item.id, location.id)
        level = await _level(db, ws.id, item.id, location.id)
        assert Decimal(level.quantity_on_hand) == replayed_quantity
        assert Decimal(level.total_value) == replayed_value


async def test_concurrent_consumption_does_not_lose_an_update() -> None:
    """Two sessions taking from one bin must serialize on the row lock."""
    import asyncio

    async with AsyncSessionLocal() as setup:
        ws = await _workspace(setup)
        item = await _item(setup, ws.id)
        location = await ensure_default_location(setup, ws.id)
        await StockService(setup).receive(
            ws.id,
            item.id,
            ReceiveStockRequest(quantity=10, unit_cost=5.00, location_id=location.id),
        )
        await setup.commit()

    async def _consume(quantity: float) -> None:
        async with AsyncSessionLocal() as db:
            await StockService(db).consume(ws.id, item.id, quantity, location_id=location.id)
            await db.commit()

    try:
        await asyncio.gather(_consume(4), _consume(3))

        async with AsyncSessionLocal() as db:
            level = await _level(db, ws.id, item.id, location.id)
            # 10 - 4 - 3: neither read-modify-write clobbered the other.
            assert Decimal(level.quantity_on_hand) == Decimal("3.0000")
            assert Decimal(level.total_value) == Decimal("15.00")

            replayed_quantity, replayed_value = await StockService(db).replay_level(
                ws.id, item.id, location.id
            )
            assert Decimal(level.quantity_on_hand) == replayed_quantity
            assert Decimal(level.total_value) == replayed_value
    finally:
        async with AsyncSessionLocal() as cleanup:
            ws_row = await cleanup.get(Workspace, ws.id)
            if ws_row is not None:
                await cleanup.delete(ws_row)
                await cleanup.commit()


async def test_another_workspaces_item_is_not_found() -> None:
    async with AsyncSessionLocal() as db:
        mine = await _workspace(db)
        theirs = await _workspace(db)
        their_item = await _item(db, theirs.id)

        with pytest.raises(HTTPException) as excinfo:
            await StockService(db).receive(
                mine.id, their_item.id, ReceiveStockRequest(quantity=1, unit_cost=1)
            )
        # 404, never 403: existence must not leak across tenants.
        assert excinfo.value.status_code == 404


async def test_unimplemented_valuation_method_is_rejected() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        item = await _item(db, ws.id, valuation_method="fifo")

        with pytest.raises(ValidationError):
            await StockService(db).receive(
                ws.id, item.id, ReceiveStockRequest(quantity=1, unit_cost=1)
            )
