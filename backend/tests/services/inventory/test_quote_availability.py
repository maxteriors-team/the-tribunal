"""Quote-time inventory coverage is current, workspace-scoped, and non-mutating."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.inventory import InventoryItem, InventoryLocation, InventoryStockLevel
from app.models.workspace import Workspace
from app.schemas.proposal_wizard import FulfillmentPart
from app.services.inventory.quote_availability import QuoteInventoryAvailabilityService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def test_quote_availability_uses_only_current_workspace_stock() -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(), name="Quote stock", slug=f"quote-stock-{uuid.uuid4().hex[:8]}"
        )
        other_workspace = Workspace(
            id=uuid.uuid4(), name="Other stock", slug=f"other-stock-{uuid.uuid4().hex[:8]}"
        )
        db.add_all([workspace, other_workspace])
        await db.flush()

        warehouse = InventoryLocation(
            workspace_id=workspace.id,
            name="Main",
            kind="warehouse",
            is_default=True,
        )
        other_warehouse = InventoryLocation(
            workspace_id=other_workspace.id,
            name="Main",
            kind="warehouse",
            is_default=True,
        )
        db.add_all([warehouse, other_warehouse])
        await db.flush()

        short_item = InventoryItem(workspace_id=workspace.id, name="Path light", sku="PATH")
        counted_item = InventoryItem(workspace_id=workspace.id, name="Wire", sku="WIRE")
        uncounted_item = InventoryItem(workspace_id=workspace.id, name="Transformer", sku="XFMR")
        other_item = InventoryItem(
            workspace_id=other_workspace.id,
            name="Other path light",
            sku="PATH",
        )
        db.add_all([short_item, counted_item, uncounted_item, other_item])
        await db.flush()
        db.add_all(
            [
                InventoryStockLevel(
                    workspace_id=workspace.id,
                    item_id=short_item.id,
                    location_id=warehouse.id,
                    quantity_on_hand=Decimal("2"),
                ),
                InventoryStockLevel(
                    workspace_id=workspace.id,
                    item_id=counted_item.id,
                    location_id=warehouse.id,
                    quantity_on_hand=Decimal("10"),
                ),
                InventoryStockLevel(
                    workspace_id=other_workspace.id,
                    item_id=other_item.id,
                    location_id=other_warehouse.id,
                    quantity_on_hand=Decimal("999"),
                ),
            ]
        )
        await db.flush()

        result = await QuoteInventoryAvailabilityService(db).snapshot(
            workspace.id,
            [
                FulfillmentPart(sku="PATH", description="Path light", qty=2),
                FulfillmentPart(sku="PATH", description="Path light", qty=3),
                FulfillmentPart(sku="WIRE", description="Wire", qty=4),
                FulfillmentPart(sku="XFMR", description="Transformer", qty=1),
                FulfillmentPart(sku="MISSING", description="Unlinked part", qty=1),
            ],
        )

        by_sku = {item.sku: item for item in result.items}
        assert by_sku["PATH"].required_quantity == 5
        assert by_sku["PATH"].quantity_on_hand == 2
        assert by_sku["PATH"].shortfall == 3
        assert by_sku["PATH"].status == "shortage"
        assert by_sku["WIRE"].status == "in_stock"
        assert by_sku["XFMR"].status == "not_counted"
        assert by_sku["MISSING"].status == "untracked"
        assert result.has_requirements is True
        assert result.has_shortages is True
        assert result.shortage_items == 1
        assert result.not_counted_items == 1
        assert result.untracked_items == 1
