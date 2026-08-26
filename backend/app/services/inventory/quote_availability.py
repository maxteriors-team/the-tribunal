"""Private quote fulfillment availability using available-to-promise stock."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import InventoryItem, InventoryJobAllocation, InventoryStockLevel
from app.schemas.inventory import (
    InventoryAvailabilityLine,
    QuoteInventoryAvailabilityResponse,
)
from app.schemas.proposal_wizard import (
    FulfillmentPart,
    QuoteInventoryAvailability,
    QuoteInventoryAvailabilityItem,
)
from app.services.exceptions import ConflictError, ValidationError


class QuoteInventoryAvailabilityService:
    """Compare internal fulfillment SKUs with unpromised workspace stock."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _requirements(
        fulfillment: Sequence[FulfillmentPart | dict[str, object]],
    ) -> dict[str, FulfillmentPart]:
        requirements: dict[str, FulfillmentPart] = {}
        for raw in fulfillment:
            try:
                part = (
                    raw if isinstance(raw, FulfillmentPart) else FulfillmentPart.model_validate(raw)
                )
            except ValueError as exc:
                raise ValidationError("Quote fulfillment data is invalid") from exc
            sku = part.sku.strip()
            quantity = Decimal(str(part.qty))
            if not sku or quantity <= 0:
                continue
            existing = requirements.get(sku)
            if existing is not None:
                if existing.inventory_behavior != part.inventory_behavior:
                    raise ConflictError(
                        f"Inventory SKU {sku} has conflicting fulfillment behaviors",
                        code="inventory_behavior_conflict",
                    )
                requirements[sku] = existing.model_copy(
                    update={"qty": float(Decimal(str(existing.qty)) + quantity)}
                )
            else:
                requirements[sku] = part.model_copy(update={"sku": sku})
        return requirements

    async def check(
        self,
        workspace_id: uuid.UUID,
        fulfillment: Sequence[FulfillmentPart | dict[str, object]],
    ) -> QuoteInventoryAvailabilityResponse:
        """Return the private ATP response used by the estimator."""
        requirements = self._requirements(fulfillment)
        if not requirements:
            return QuoteInventoryAvailabilityResponse(connected=False, is_available=False)

        items = list(
            (
                await self.db.execute(
                    select(InventoryItem).where(
                        InventoryItem.workspace_id == workspace_id,
                        InventoryItem.is_active.is_(True),
                        InventoryItem.sku.in_(requirements),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_sku = {item.sku: item for item in items if item.sku}
        item_ids = [item.id for item in items]
        stock = {
            item_id: (Decimal(quantity or 0), int(level_count or 0))
            for item_id, quantity, level_count in (
                await self.db.execute(
                    select(
                        InventoryStockLevel.item_id,
                        func.sum(InventoryStockLevel.quantity_on_hand),
                        func.count(InventoryStockLevel.id),
                    )
                    .where(
                        InventoryStockLevel.workspace_id == workspace_id,
                        InventoryStockLevel.item_id.in_(item_ids),
                    )
                    .group_by(InventoryStockLevel.item_id)
                )
            ).all()
        }
        reserved: dict[uuid.UUID, Decimal] = {}
        deployed: dict[uuid.UUID, Decimal] = {}
        allocation_rows = (
            await self.db.execute(
                select(
                    InventoryJobAllocation.item_id,
                    InventoryJobAllocation.status,
                    InventoryJobAllocation.planned_quantity,
                    InventoryJobAllocation.actual_quantity,
                ).where(
                    InventoryJobAllocation.workspace_id == workspace_id,
                    InventoryJobAllocation.item_id.in_(item_ids),
                    InventoryJobAllocation.status.in_({"reserved", "deployed"}),
                )
            )
        ).all()
        for item_id, allocation_status, planned, actual in allocation_rows:
            target = reserved if allocation_status == "reserved" else deployed
            target[item_id] = target.get(item_id, Decimal(0)) + Decimal(
                planned if allocation_status == "reserved" else actual or 0
            )

        lines: list[InventoryAvailabilityLine] = []
        for sku, part in sorted(requirements.items()):
            item = by_sku.get(sku)
            required = Decimal(str(part.qty))
            owned, level_count = stock.get(item.id, (Decimal(0), 0)) if item else (Decimal(0), 0)
            promised = reserved.get(item.id, Decimal(0)) if item else Decimal(0)
            out = deployed.get(item.id, Decimal(0)) if item else Decimal(0)
            available = owned - promised - out
            shortage = max(Decimal(0), required - max(Decimal(0), available))
            counted = level_count > 0
            lines.append(
                InventoryAvailabilityLine(
                    sku=sku,
                    description=part.description,
                    inventory_behavior=part.inventory_behavior,
                    required_quantity=float(required),
                    item_id=item.id if item else None,
                    item_name=item.name if item else None,
                    unit_of_measure=item.unit_of_measure if item else None,
                    tracked=item is not None,
                    is_counted=counted,
                    quantity_on_hand=float(owned),
                    quantity_reserved=float(promised),
                    quantity_deployed=float(out),
                    available_to_promise=float(available),
                    shortage_quantity=float(shortage),
                    is_available=item is not None and counted and shortage == 0,
                )
            )
        connected = len(by_sku) == len(requirements)
        return QuoteInventoryAvailabilityResponse(
            connected=connected,
            is_available=connected and all(line.is_available for line in lines),
            items=lines,
        )

    async def snapshot(
        self,
        workspace_id: uuid.UUID,
        fulfillment: Sequence[FulfillmentPart | dict[str, object]],
    ) -> QuoteInventoryAvailability:
        """Map ATP details into the stored staff-only proposal snapshot."""
        availability = await self.check(workspace_id, fulfillment)
        items: list[QuoteInventoryAvailabilityItem] = []
        for line in availability.items:
            status: Literal["in_stock", "shortage", "not_counted", "untracked"]
            if not line.tracked:
                status = "untracked"
            elif not line.is_counted:
                status = "not_counted"
            elif line.shortage_quantity > 0:
                status = "shortage"
            else:
                status = "in_stock"
            items.append(
                QuoteInventoryAvailabilityItem(
                    sku=line.sku,
                    description=line.description,
                    required_quantity=line.required_quantity,
                    inventory_item_id=line.item_id,
                    inventory_item_name=line.item_name,
                    unit_of_measure=line.unit_of_measure,
                    quantity_on_hand=line.quantity_on_hand if line.is_counted else None,
                    shortfall=line.shortage_quantity if line.is_counted else None,
                    status=status,
                )
            )

        shortage_items = sum(item.status == "shortage" for item in items)
        not_counted_items = sum(item.status == "not_counted" for item in items)
        untracked_items = sum(item.status == "untracked" for item in items)
        return QuoteInventoryAvailability(
            items=items,
            has_requirements=bool(items),
            has_shortages=shortage_items > 0,
            shortage_items=shortage_items,
            not_counted_items=not_counted_items,
            untracked_items=untracked_items,
        )
