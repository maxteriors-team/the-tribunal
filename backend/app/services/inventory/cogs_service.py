"""Cost of goods sold, computed from the inventory ledger.

Cost is recognized **when stock is consumed** (``job_usage`` / ``sale``), valued
at the weighted average that applied at posting time. That average is already
snapshotted on the ledger row, so this report is a window scan — it never
replays or restates history, which is exactly the property the forward-only
posting engine was chosen to preserve.

Two things are deliberately kept out of the COGS number:

- **Shrinkage** is reported on its own line. Waste buried inside gross margin is
  waste nobody fixes.
- **Transfers, adjustments and returns** move or correct value without selling
  anything, so they are not cost of goods sold.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogItem
from app.models.field_service import Job
from app.models.inventory import InventoryItem, InventoryLedgerEntry, InventoryStockLevel
from app.models.invoice import Invoice
from app.schemas.inventory import COGSBreakdownRow, COGSGroupBy, COGSReport

# Consumption is the moment cost is recognized.
COGS_REASONS = ("job_usage", "sale")
SHRINKAGE_REASON = "shrinkage"

# Invoices that represent recognized revenue in a window.
_REVENUE_STATUSES = ("sent", "partial", "paid", "overdue")

UNCATEGORIZED_LABEL = "Uncategorized"


def _require_single_currency(currencies: set[str], report: str) -> str:
    """Return the lone currency present, defaulting to USD when there is none.

    Same guard as :mod:`app.services.reporting.reporting_service`: summing money
    across currencies is meaningless, so refuse with 422 rather than emit a
    confidently wrong total.
    """
    present = {code for code in currencies if code}
    if len(present) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"{report} spans multiple currencies "
                f"({', '.join(sorted(present))}); reporting across currencies "
                "is not supported."
            ),
        )
    return next(iter(present), "USD")


class COGSService:
    """Window-scoped cost of goods sold, with a grouped breakdown."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def cogs(
        self,
        workspace_id: uuid.UUID,
        *,
        date_from: date,
        date_to: date,
        group_by: COGSGroupBy = "item",
    ) -> COGSReport:
        """Cost of goods sold between two inclusive dates."""
        if date_to < date_from:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="date_to must be on or after date_from",
            )

        start_at = datetime.combine(date_from, time.min, tzinfo=UTC)
        end_before = datetime.combine(date_to, time.min, tzinfo=UTC) + timedelta(days=1)

        totals = (
            await self.db.execute(
                select(
                    func.coalesce(
                        func.sum(InventoryLedgerEntry.value_delta).filter(
                            InventoryLedgerEntry.reason.in_(COGS_REASONS)
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(InventoryLedgerEntry.value_delta).filter(
                            InventoryLedgerEntry.reason == SHRINKAGE_REASON
                        ),
                        0,
                    ),
                ).where(
                    InventoryLedgerEntry.workspace_id == workspace_id,
                    InventoryLedgerEntry.created_at >= start_at,
                    InventoryLedgerEntry.created_at < end_before,
                )
            )
        ).one()
        # Outbound value deltas are negative; cost is their magnitude.
        total_cogs = float(-Decimal(totals[0] or 0))
        shrinkage_cost = float(-Decimal(totals[1] or 0))

        breakdown = await self._breakdown(
            workspace_id, start_at=start_at, end_before=end_before, group_by=group_by
        )

        ending_value = (
            await self.db.execute(
                select(func.coalesce(func.sum(InventoryStockLevel.total_value), 0)).where(
                    InventoryStockLevel.workspace_id == workspace_id
                )
            )
        ).scalar_one()

        revenue, currency = await self._revenue(workspace_id, date_from=date_from, date_to=date_to)
        gross_margin = (
            round((revenue - total_cogs) / revenue, 4)
            if revenue is not None and revenue > 0
            else None
        )

        return COGSReport(
            date_from=date_from,
            date_to=date_to,
            currency=currency,
            total_cogs=round(total_cogs, 2),
            shrinkage_cost=round(shrinkage_cost, 2),
            ending_inventory_value=round(float(ending_value or 0), 2),
            revenue=round(revenue, 2) if revenue is not None else None,
            gross_margin=gross_margin,
            group_by=group_by,
            breakdown=breakdown,
        )

    async def _revenue(
        self, workspace_id: uuid.UUID, *, date_from: date, date_to: date
    ) -> tuple[float | None, str]:
        """Issued invoice revenue in the window, plus its (single) currency."""
        rows = (
            await self.db.execute(
                select(Invoice.total, Invoice.currency).where(
                    Invoice.workspace_id == workspace_id,
                    Invoice.status.in_(_REVENUE_STATUSES),
                    Invoice.issue_date.isnot(None),
                    Invoice.issue_date >= date_from,
                    Invoice.issue_date <= date_to,
                )
            )
        ).all()
        currency = _require_single_currency({row.currency for row in rows}, "COGS")
        if not rows:
            return None, currency
        return sum(float(row.total or 0) for row in rows), currency

    async def _breakdown(
        self,
        workspace_id: uuid.UUID,
        *,
        start_at: datetime,
        end_before: datetime,
        group_by: COGSGroupBy,
    ) -> list[COGSBreakdownRow]:
        """Grouped COGS slices, largest first."""
        base_filters = (
            InventoryLedgerEntry.workspace_id == workspace_id,
            InventoryLedgerEntry.reason.in_(COGS_REASONS),
            InventoryLedgerEntry.created_at >= start_at,
            InventoryLedgerEntry.created_at < end_before,
        )
        cost = func.coalesce(func.sum(-InventoryLedgerEntry.value_delta), 0)
        quantity = func.coalesce(func.sum(-InventoryLedgerEntry.quantity_delta), 0)

        slices: list[COGSBreakdownRow]
        if group_by == "item":
            item_rows = (
                await self.db.execute(
                    select(InventoryItem.id, InventoryItem.name, cost, quantity)
                    .join(InventoryItem, InventoryItem.id == InventoryLedgerEntry.item_id)
                    .where(*base_filters)
                    .group_by(InventoryItem.id, InventoryItem.name)
                )
            ).all()
            slices = [
                COGSBreakdownRow(
                    key=str(item_id), label=name, cogs=float(value), quantity=float(qty)
                )
                for item_id, name, value, qty in item_rows
            ]
        elif group_by == "service_category":
            category = func.coalesce(
                InventoryItem.service_category,
                CatalogItem.service_category,
            )
            category_rows = (
                await self.db.execute(
                    select(category, cost, quantity)
                    .join(InventoryItem, InventoryItem.id == InventoryLedgerEntry.item_id)
                    .outerjoin(CatalogItem, CatalogItem.id == InventoryItem.catalog_item_id)
                    .where(*base_filters)
                    .group_by(category)
                )
            ).all()
            slices = [
                COGSBreakdownRow(
                    key=category,
                    label=category or UNCATEGORIZED_LABEL,
                    cogs=float(value),
                    quantity=float(qty),
                )
                for category, value, qty in category_rows
            ]
        else:
            job_rows = (
                await self.db.execute(
                    select(Job.id, Job.title, cost, quantity)
                    .join(
                        Job,
                        Job.id == InventoryLedgerEntry.reference_id,
                    )
                    .where(
                        *base_filters,
                        InventoryLedgerEntry.reference_type == "job",
                        Job.workspace_id == workspace_id,
                    )
                    .group_by(Job.id, Job.title)
                )
            ).all()
            slices = [
                COGSBreakdownRow(
                    key=str(job_id), label=title, cogs=float(value), quantity=float(qty)
                )
                for job_id, title, value, qty in job_rows
            ]

        slices.sort(key=lambda row: (-row.cogs, row.label.lower()))
        return [
            COGSBreakdownRow(
                key=row.key,
                label=row.label,
                cogs=round(row.cogs, 2),
                quantity=round(row.quantity, 4),
            )
            for row in slices
        ]

    async def material_cost_by_job(
        self,
        workspace_id: uuid.UUID,
        job_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, float]:
        """Net material cost per job, from the ledger.

        Net of returns: a ``return_to_stock`` row posted when a consumption is
        undone adds its value back, so an undone material line costs the job
        nothing. This is the *only* source of ``material_cost`` — consuming
        stock never writes a ``JobExpense``, so the two can never double-count.
        """
        if not job_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    InventoryLedgerEntry.reference_id,
                    func.coalesce(func.sum(-InventoryLedgerEntry.value_delta), 0),
                )
                .where(
                    InventoryLedgerEntry.workspace_id == workspace_id,
                    InventoryLedgerEntry.reference_type == "job",
                    InventoryLedgerEntry.reference_id.in_(job_ids),
                    InventoryLedgerEntry.reason.in_((*COGS_REASONS, "return_to_stock")),
                )
                .group_by(InventoryLedgerEntry.reference_id)
            )
        ).all()
        return {job_id: round(float(value or 0), 2) for job_id, value in rows if job_id is not None}
