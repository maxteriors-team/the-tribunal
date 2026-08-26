"""Materials consumed on a job, sourced from the inventory ledger.

This is the bridge between the jobs domain and inventory, and it exists to make
one rule impossible to break by accident: **consuming stock on a job never
writes a** :class:`app.models.job_costing.JobExpense`. ``JobExpense`` already
has a free-form ``"materials"`` category, so writing both would double-count the
same bucket of chemical in the job's P&L. Material cost comes from the ledger
and only from the ledger.

Undo is a *compensating entry*, never a delete: removing a material line posts a
``return_to_stock`` row at the cost the stock left with, so the job's net
material cost returns to exactly zero and the audit trail keeps both the mistake
and the correction.

One line per item per job. The partial-unique index behind that
(``uq_inventory_ledger_job_usage``) is what makes a retried POST land on a 409
instead of quietly consuming the stock twice.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.field_service import Job
from app.models.inventory import InventoryItem, InventoryLedgerEntry, InventoryLocation
from app.schemas.inventory import (
    InventoryLedgerEntryResponse,
    JobMaterialCreate,
    JobMaterialsResponse,
)
from app.services.exceptions import ConflictError
from app.services.inventory.job_allocations import JobAllocationService
from app.services.inventory.stock_service import StockService

logger = structlog.get_logger()

# Rows that make up a job's material story: what was taken, and what came back.
_MATERIAL_REASONS = ("job_usage", "return_to_stock")


class JobMaterialsService:
    """List, consume, and return the stock a job used."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stock = StockService(db)
        self.log = logger.bind(component="job_materials_service")

    async def _assert_job(self, job_id: uuid.UUID, workspace_id: uuid.UUID) -> Job:
        return await assert_workspace_owned(
            self.db, Job, job_id, workspace_id, detail="Job not found"
        )

    async def _entries(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> list[InventoryLedgerEntry]:
        return list(
            (
                await self.db.execute(
                    select_workspace_owned(
                        InventoryLedgerEntry,
                        workspace_id,
                        InventoryLedgerEntry.reference_type == "job",
                        InventoryLedgerEntry.reference_id == job_id,
                        InventoryLedgerEntry.reason.in_(_MATERIAL_REASONS),
                    ).order_by(InventoryLedgerEntry.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _labels(
        self, workspace_id: uuid.UUID, entries: list[InventoryLedgerEntry]
    ) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
        """Item and location names for the rows being serialized."""
        if not entries:
            return {}, {}
        item_rows = (
            await self.db.execute(
                select(InventoryItem.id, InventoryItem.name).where(
                    InventoryItem.workspace_id == workspace_id,
                    InventoryItem.id.in_({entry.item_id for entry in entries}),
                )
            )
        ).all()
        location_rows = (
            await self.db.execute(
                select(InventoryLocation.id, InventoryLocation.name).where(
                    InventoryLocation.workspace_id == workspace_id,
                    InventoryLocation.id.in_({entry.location_id for entry in entries}),
                )
            )
        ).all()
        return (
            {row[0]: row[1] for row in item_rows},
            {row[0]: row[1] for row in location_rows},
        )

    async def _response(
        self,
        workspace_id: uuid.UUID,
        entry: InventoryLedgerEntry,
        *,
        include_costs: bool,
    ) -> InventoryLedgerEntryResponse:
        items, locations = await self._labels(workspace_id, [entry])
        return StockService.entry_response(
            entry,
            item_name=items.get(entry.item_id),
            location_name=locations.get(entry.location_id),
            include_costs=include_costs,
        )

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    async def list_for_job(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, *, include_costs: bool = True
    ) -> JobMaterialsResponse:
        """Every material movement on the job, oldest first, plus its net cost."""
        await self._assert_job(job_id, workspace_id)
        entries = await self._entries(job_id, workspace_id)
        items, locations = await self._labels(workspace_id, entries)
        inventory_plan = await JobAllocationService(self.db).get_plan(workspace_id, job_id)
        deployed_equipment = [
            allocation
            for allocation in inventory_plan.allocations
            if allocation.status == "deployed"
        ]
        total = sum((Decimal(entry.value_delta or 0) for entry in entries), Decimal(0))
        return JobMaterialsResponse(
            job_id=job_id,
            items=[
                StockService.entry_response(
                    entry,
                    item_name=items.get(entry.item_id),
                    location_name=locations.get(entry.location_id),
                    include_costs=include_costs,
                )
                for entry in entries
            ],
            deployed_equipment=deployed_equipment,
            # Consumption is a negative value delta; cost is its magnitude, net
            # of anything returned.
            total_material_cost=round(float(-total), 2) if include_costs else 0.0,
        )

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    async def consume_for_job(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        payload: JobMaterialCreate,
        *,
        created_by_id: int | None = None,
        include_costs: bool = True,
    ) -> InventoryLedgerEntryResponse:
        """Consume stock on a job at the item's current weighted-average cost."""
        await self._assert_job(job_id, workspace_id)

        already = (
            (
                await self.db.execute(
                    select_workspace_owned(
                        InventoryLedgerEntry,
                        workspace_id,
                        InventoryLedgerEntry.reference_type == "job",
                        InventoryLedgerEntry.reference_id == job_id,
                        InventoryLedgerEntry.reason == "job_usage",
                        InventoryLedgerEntry.item_id == payload.item_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if already is not None:
            # The same guard the partial-unique index enforces, raised here so a
            # retry gets a typed 409 instead of a database error.
            raise ConflictError(
                "That item is already recorded on this job; remove the existing "
                "line before recording a different quantity.",
                code="material_already_recorded",
            )

        entry = await self.stock.consume(
            workspace_id,
            payload.item_id,
            payload.quantity,
            location_id=payload.location_id,
            reason="job_usage",
            reference_type="job",
            reference_id=job_id,
            note=payload.note,
            created_by_id=created_by_id,
        )
        self.log.info(
            "job_material_consumed",
            job_id=str(job_id),
            item_id=str(payload.item_id),
            quantity=str(payload.quantity),
        )
        return await self._response(workspace_id, entry, include_costs=include_costs)

    async def return_for_job(
        self,
        job_id: uuid.UUID,
        workspace_id: uuid.UUID,
        entry_id: uuid.UUID,
        *,
        created_by_id: int | None = None,
        include_costs: bool = True,
    ) -> InventoryLedgerEntryResponse:
        """Undo a material line by returning its remaining quantity to stock."""
        await self._assert_job(job_id, workspace_id)
        usage = await assert_workspace_owned(
            self.db,
            InventoryLedgerEntry,
            entry_id,
            workspace_id,
            InventoryLedgerEntry.reference_type == "job",
            InventoryLedgerEntry.reference_id == job_id,
            InventoryLedgerEntry.reason == "job_usage",
            detail="Job material not found",
        )

        returned = sum(
            (
                Decimal(entry.quantity_delta or 0)
                for entry in await self._entries(job_id, workspace_id)
                if entry.reason == "return_to_stock" and entry.item_id == usage.item_id
            ),
            Decimal(0),
        )
        remaining = -Decimal(usage.quantity_delta or 0) - returned
        if remaining <= 0:
            raise ConflictError(
                "That material has already been returned to stock",
                code="material_already_returned",
            )

        entry = await self.stock.return_to_stock(
            workspace_id,
            usage.item_id,
            float(remaining),
            # Returned at the cost it left with, so the job's net material cost
            # lands back on exactly zero rather than at today's average.
            unit_cost=float(usage.unit_cost or 0),
            location_id=usage.location_id,
            reference_type="job",
            reference_id=job_id,
            note=usage.note,
            created_by_id=created_by_id,
        )
        self.log.info(
            "job_material_returned",
            job_id=str(job_id),
            item_id=str(usage.item_id),
            quantity=str(remaining),
        )
        return await self._response(workspace_id, entry, include_costs=include_costs)
