"""Operator-level nudge: tracked stock has hit its reorder point.

Workspace-level (``contact_id=None``) and deduped per item per day, the same
shape as :mod:`app.services.nudges.strategies.approvals_waiting`. It rides the
existing hourly ``nudge_worker`` rather than adding a poll loop of its own —
every loop in this codebase is duplicated by each backend replica, so a new
worker is a real cost for something an hourly scan already covers.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.human_nudge import HumanNudge
from app.models.inventory import InventoryItem, InventoryStockLevel
from app.services.nudges.strategies.base import (
    NudgeContext,
    NudgeStrategy,
    dedup_exists,
)

# Cap on how many items one run will nudge about. A workspace that lets fifty
# SKUs run dry needs one conversation, not fifty notifications.
MAX_ITEMS_PER_RUN = 5


class InventoryLowStockNudgeStrategy(NudgeStrategy):
    """Nudge the operator when a managed item is at or below its reorder point.

    Only items with a ``reorder_point`` set are considered: a null reorder point
    means the operator has not asked us to manage that item, and inventing a
    threshold would train them to ignore the alert.
    """

    nudge_type = "inventory_low_stock"

    async def generate(self, db: AsyncSession, context: NudgeContext) -> int:
        on_hand = (
            select(
                InventoryStockLevel.item_id.label("item_id"),
                func.coalesce(func.sum(InventoryStockLevel.quantity_on_hand), 0).label("quantity"),
            )
            .where(InventoryStockLevel.workspace_id == context.workspace_id)
            .group_by(InventoryStockLevel.item_id)
            .subquery()
        )
        rows = (
            await db.execute(
                select(InventoryItem, func.coalesce(on_hand.c.quantity, 0))
                .outerjoin(on_hand, on_hand.c.item_id == InventoryItem.id)
                .where(
                    InventoryItem.workspace_id == context.workspace_id,
                    InventoryItem.is_active.is_(True),
                    InventoryItem.reorder_point.isnot(None),
                    # Aggregated across locations: an empty truck is not a
                    # reorder signal while the warehouse is full.
                    func.coalesce(on_hand.c.quantity, 0) <= InventoryItem.reorder_point,
                )
                .order_by(InventoryItem.name.asc())
                .limit(MAX_ITEMS_PER_RUN)
            )
        ).all()

        created = 0
        for item, quantity in rows:
            dedup_key = (
                f"{context.workspace_id}:inventory_low_stock:{item.id}:{context.today.isoformat()}"
            )
            if await dedup_exists(db, dedup_key):
                continue

            on_hand_qty = float(quantity or 0)
            reorder_point = float(item.reorder_point or 0)
            supplier = f" from {item.supplier_name}" if item.supplier_name else ""
            reorder_qty = (
                f" Reorder {float(item.reorder_quantity):g} {item.unit_of_measure}{supplier}."
                if item.reorder_quantity is not None
                else f" Time to restock{supplier}."
            )
            db.add(
                HumanNudge(
                    workspace_id=context.workspace_id,
                    contact_id=None,
                    assigned_to_user_id=context.workspace_owner_user_id,
                    nudge_type=self.nudge_type,
                    title=f"\U0001f4e6 Low stock: {item.name}",
                    message=(
                        f"\U0001f4e6 {item.name} is down to {on_hand_qty:g} "
                        f"{item.unit_of_measure} (reorder point {reorder_point:g})."
                        f"{reorder_qty}"
                    ),
                    suggested_action=None,
                    priority="high",
                    due_date=context.now,
                    source_date_field=None,
                    status="pending",
                    dedup_key=dedup_key,
                )
            )
            created += 1

        return created
