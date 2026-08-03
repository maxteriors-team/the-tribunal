"""Low-stock flagging and reorder-point suggestion.

Two deliberate rules:

- **Aggregate across locations.** An empty truck is not a reorder signal while
  the warehouse is full; the operator restocks the truck from the shelf.
- **Never overwrite the operator's number.** ``suggest_reorder_point`` returns a
  computed value alongside the stored one. Applying it is an explicit action —
  a system that silently retunes a threshold teaches operators to distrust it.

The formula is the industry-standard one (NetSuite / MRPeasy / Fishbowl all
publish the same shape)::

    reorder point = average daily usage x lead time days + safety stock

``average daily usage`` comes from ``job_usage`` + ``sale`` ledger rows over a
trailing window (90 days by default), which is why the ledger keeps the reason
on every row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned
from app.models.inventory import InventoryItem, InventoryLedgerEntry, InventoryStockLevel
from app.schemas.inventory import ReorderReport, ReorderRow, ReorderSuggestion

# Trailing window for the usage average. Long enough to survive a quiet week,
# short enough to follow a season change in the trades this serves.
DEFAULT_LOOKBACK_DAYS = 90

# Ledger reasons that represent real demand (what customers consumed), as
# opposed to shrinkage, transfers, or count corrections.
_CONSUMPTION_REASONS = ("job_usage", "sale")


class ReorderService:
    """Which items need buying, and what their trigger point should be."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _usage_by_item(
        self,
        workspace_id: uuid.UUID,
        *,
        lookback_days: int,
        item_ids: list[uuid.UUID] | None = None,
    ) -> dict[uuid.UUID, Decimal]:
        """Total quantity consumed per item over the trailing window (positive)."""
        since = datetime.now(UTC) - timedelta(days=lookback_days)
        query = (
            select(
                InventoryLedgerEntry.item_id,
                func.sum(InventoryLedgerEntry.quantity_delta),
            )
            .where(
                InventoryLedgerEntry.workspace_id == workspace_id,
                InventoryLedgerEntry.reason.in_(_CONSUMPTION_REASONS),
                InventoryLedgerEntry.created_at >= since,
            )
            .group_by(InventoryLedgerEntry.item_id)
        )
        if item_ids is not None:
            if not item_ids:
                return {}
            query = query.where(InventoryLedgerEntry.item_id.in_(item_ids))

        rows = (await self.db.execute(query)).all()
        # Consumption is stored as a negative delta; demand is its magnitude.
        return {item_id: -Decimal(total or 0) for item_id, total in rows}

    @staticmethod
    def _avg_daily_usage(consumed: Decimal, lookback_days: int) -> float | None:
        """Demand per day, or ``None`` when nothing was consumed.

        ``None`` rather than ``0`` on purpose: no history means the gauge is
        unreadable, and a 0 would make ``days_of_cover`` look infinite.
        """
        if consumed <= 0 or lookback_days <= 0:
            return None
        return float(consumed) / lookback_days

    async def low_stock(
        self,
        workspace_id: uuid.UUID,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> ReorderReport:
        """Active managed items whose total on-hand is at or below their trigger.

        Ordered by urgency: fewest days of cover first, then largest shortfall,
        so the item that runs out on Tuesday outranks the one that runs out in
        three weeks.
        """
        on_hand = (
            select(
                InventoryStockLevel.item_id.label("item_id"),
                func.coalesce(func.sum(InventoryStockLevel.quantity_on_hand), 0).label("quantity"),
                func.max(InventoryStockLevel.last_movement_at).label("last_movement_at"),
            )
            .where(InventoryStockLevel.workspace_id == workspace_id)
            .group_by(InventoryStockLevel.item_id)
            .subquery()
        )

        rows = (
            await self.db.execute(
                select(InventoryItem, func.coalesce(on_hand.c.quantity, 0))
                .outerjoin(on_hand, on_hand.c.item_id == InventoryItem.id)
                .where(
                    InventoryItem.workspace_id == workspace_id,
                    InventoryItem.is_active.is_(True),
                    InventoryItem.reorder_point.isnot(None),
                    func.coalesce(on_hand.c.quantity, 0) <= InventoryItem.reorder_point,
                )
            )
        ).all()

        usage = await self._usage_by_item(
            workspace_id,
            lookback_days=lookback_days,
            item_ids=[item.id for item, _ in rows],
        )

        report_rows: list[ReorderRow] = []
        for item, quantity in rows:
            quantity_on_hand = float(quantity or 0)
            reorder_point = float(item.reorder_point or 0)
            avg_daily = self._avg_daily_usage(usage.get(item.id, Decimal(0)), lookback_days)
            days_of_cover = (
                round(quantity_on_hand / avg_daily, 1)
                if avg_daily and quantity_on_hand > 0
                else (0.0 if avg_daily else None)
            )
            report_rows.append(
                ReorderRow(
                    item_id=item.id,
                    item_name=item.name,
                    sku=item.sku,
                    unit_of_measure=item.unit_of_measure,
                    quantity_on_hand=round(quantity_on_hand, 4),
                    reorder_point=reorder_point,
                    reorder_quantity=(
                        float(item.reorder_quantity) if item.reorder_quantity is not None else None
                    ),
                    safety_stock=float(item.safety_stock or 0),
                    lead_time_days=item.lead_time_days,
                    supplier_name=item.supplier_name,
                    supplier_sku=item.supplier_sku,
                    shortfall=round(max(reorder_point - quantity_on_hand, 0.0), 4),
                    days_of_cover=days_of_cover,
                    avg_daily_usage=round(avg_daily, 4) if avg_daily else None,
                    suggested_reorder_point=self._suggested_point(
                        avg_daily_usage=avg_daily,
                        lead_time_days=item.lead_time_days,
                        safety_stock=float(item.safety_stock or 0),
                    ),
                )
            )

        # Unknown cover sorts last: an item with no usage history is a weaker
        # signal than one measurably about to run out.
        report_rows.sort(
            key=lambda row: (
                row.days_of_cover if row.days_of_cover is not None else float("inf"),
                -row.shortfall,
                row.item_name.lower(),
            )
        )
        return ReorderReport(
            items=report_rows,
            total=len(report_rows),
            generated_at=datetime.now(UTC),
            lookback_days=lookback_days,
        )

    @staticmethod
    def _suggested_point(
        *,
        avg_daily_usage: float | None,
        lead_time_days: int | None,
        safety_stock: float,
    ) -> float | None:
        """``usage x lead time + safety stock``, or ``None`` when unknowable.

        Both inputs are required: without a lead time we cannot say how long the
        shelf must last, and without usage we have no demand rate. Guessing one
        would produce a confident wrong number.
        """
        if avg_daily_usage is None or lead_time_days is None:
            return None
        return round(avg_daily_usage * lead_time_days + safety_stock, 4)

    async def suggest_reorder_point(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> ReorderSuggestion:
        """Compute (never apply) a reorder point for one item."""
        item = await assert_workspace_owned(
            self.db, InventoryItem, item_id, workspace_id, detail="Inventory item not found"
        )
        usage = await self._usage_by_item(
            workspace_id, lookback_days=lookback_days, item_ids=[item.id]
        )
        avg_daily = self._avg_daily_usage(usage.get(item.id, Decimal(0)), lookback_days)
        safety_stock = float(item.safety_stock or 0)
        return ReorderSuggestion(
            item_id=item.id,
            stored_reorder_point=(
                float(item.reorder_point) if item.reorder_point is not None else None
            ),
            suggested_reorder_point=self._suggested_point(
                avg_daily_usage=avg_daily,
                lead_time_days=item.lead_time_days,
                safety_stock=safety_stock,
            ),
            avg_daily_usage=round(avg_daily, 4) if avg_daily else None,
            lead_time_days=item.lead_time_days,
            safety_stock=safety_stock,
            lookback_days=lookback_days,
        )
