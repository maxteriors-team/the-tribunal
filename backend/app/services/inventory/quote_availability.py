"""Compare quote fulfillment requirements with current workspace inventory."""

from __future__ import annotations

import uuid
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem, InventoryStockLevel
from app.schemas.proposal_wizard import (
    FulfillmentPart,
    QuoteInventoryAvailability,
    QuoteInventoryAvailabilityItem,
)


class QuoteInventoryAvailabilityService:
    """Build an internal availability snapshot without reserving or consuming stock."""

    # simplification: quotes show current on-hand but do not reserve it; add a
    # reservation ledger when scheduling must guarantee stock across concurrent quotes.

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check(
        self,
        workspace_id: uuid.UUID,
        requirements: list[FulfillmentPart],
    ) -> QuoteInventoryAvailability:
        required_by_sku: dict[str, Decimal] = defaultdict(Decimal)
        descriptions: dict[str, str | None] = {}
        for requirement in requirements:
            sku = requirement.sku.strip()
            quantity = Decimal(str(requirement.qty))
            if not sku or quantity <= 0:
                continue
            required_by_sku[sku] += quantity
            descriptions.setdefault(sku, requirement.description)

        if not required_by_sku:
            return QuoteInventoryAvailability()

        stock = (
            select(
                InventoryStockLevel.item_id.label("item_id"),
                func.sum(InventoryStockLevel.quantity_on_hand).label("quantity_on_hand"),
                func.count(InventoryStockLevel.id).label("level_count"),
            )
            .where(InventoryStockLevel.workspace_id == workspace_id)
            .group_by(InventoryStockLevel.item_id)
            .subquery()
        )
        rows = (
            await self.db.execute(
                select(
                    InventoryItem,
                    stock.c.quantity_on_hand,
                    stock.c.level_count,
                )
                .outerjoin(stock, stock.c.item_id == InventoryItem.id)
                .where(
                    InventoryItem.workspace_id == workspace_id,
                    InventoryItem.is_active.is_(True),
                    InventoryItem.sku.in_(required_by_sku),
                )
            )
        ).all()
        tracked = {item.sku: (item, quantity, level_count) for item, quantity, level_count in rows}

        items: list[QuoteInventoryAvailabilityItem] = []
        for sku, required in sorted(required_by_sku.items()):
            match = tracked.get(sku)
            if match is None:
                items.append(
                    QuoteInventoryAvailabilityItem(
                        sku=sku,
                        description=descriptions[sku],
                        required_quantity=_quantity(required),
                        status="untracked",
                    )
                )
                continue

            item, quantity, level_count = match
            if not level_count:
                items.append(
                    QuoteInventoryAvailabilityItem(
                        sku=sku,
                        description=descriptions[sku],
                        required_quantity=_quantity(required),
                        inventory_item_id=item.id,
                        inventory_item_name=item.name,
                        unit_of_measure=item.unit_of_measure,
                        status="not_counted",
                    )
                )
                continue

            on_hand = Decimal(str(quantity or 0))
            shortfall = max(required - on_hand, Decimal("0"))
            items.append(
                QuoteInventoryAvailabilityItem(
                    sku=sku,
                    description=descriptions[sku],
                    required_quantity=_quantity(required),
                    inventory_item_id=item.id,
                    inventory_item_name=item.name,
                    unit_of_measure=item.unit_of_measure,
                    quantity_on_hand=_quantity(on_hand),
                    shortfall=_quantity(shortfall),
                    status="shortage" if shortfall > 0 else "in_stock",
                )
            )

        shortage_items = sum(item.status == "shortage" for item in items)
        not_counted_items = sum(item.status == "not_counted" for item in items)
        untracked_items = sum(item.status == "untracked" for item in items)
        return QuoteInventoryAvailability(
            items=items,
            has_requirements=True,
            has_shortages=shortage_items > 0,
            shortage_items=shortage_items,
            not_counted_items=not_counted_items,
            untracked_items=untracked_items,
        )


def _quantity(value: Decimal) -> float:
    return round(float(value), 4)
