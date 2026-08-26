"""Workspace-scoped reservation and fulfillment for job inventory.

Owned stock is never reduced for reusable equipment: reservations and deployments
only change available-to-promise. Consumables post through :class:`StockService`
so weighted-average COGS and immutable ledger history stay canonical.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.scope import select_workspace_owned
from app.models.field_service import Job, JobStatus
from app.models.inventory import (
    InventoryItem,
    InventoryJobAllocation,
    InventoryLocation,
    InventoryStockLevel,
)
from app.schemas.inventory import (
    CompleteJobInventoryRequest,
    InventoryAllocationStatus,
    InventoryBehavior,
    InventoryJobAllocationResponse,
    JobInventoryPlanResponse,
)
from app.schemas.proposal_wizard import FulfillmentPart
from app.services.exceptions import ConflictError, ValidationError
from app.services.inventory.locations import resolve_location
from app.services.inventory.stock_service import StockService

_QUANTITY_PLACES = Decimal("0.0001")
_ACTIVE_STATUSES = frozenset({"reserved", "deployed"})
type _RequestedActuals = dict[uuid.UUID, tuple[Decimal, uuid.UUID | None]]


def _quantity(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(_QUANTITY_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class _StockSnapshot:
    on_hand: Decimal
    reserved: Decimal
    deployed: Decimal
    by_location: dict[uuid.UUID, Decimal]
    deployed_by_location: dict[uuid.UUID, Decimal]

    @property
    def available_to_promise(self) -> Decimal:
        return self.on_hand - self.reserved - self.deployed


class JobAllocationService:
    """Own every allocation transition; callers own the surrounding transaction."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _job(self, job_id: uuid.UUID, workspace_id: uuid.UUID, *, lock: bool = False) -> Job:
        query = select_workspace_owned(Job, workspace_id, Job.id == job_id)
        if lock:
            query = query.with_for_update()
        job = (await self.db.execute(query)).scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        return job

    async def _allocations(
        self, job_id: uuid.UUID, workspace_id: uuid.UUID, *, lock: bool = False
    ) -> list[InventoryJobAllocation]:
        query = select_workspace_owned(
            InventoryJobAllocation,
            workspace_id,
            InventoryJobAllocation.job_id == job_id,
            options=[
                selectinload(InventoryJobAllocation.item),
                selectinload(InventoryJobAllocation.source_location),
            ],
        ).order_by(InventoryJobAllocation.item_id, InventoryJobAllocation.id)
        if lock:
            query = query.with_for_update()
        return list((await self.db.execute(query)).scalars().all())

    async def _stock_snapshot(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> _StockSnapshot:
        level_query = select_workspace_owned(
            InventoryStockLevel,
            workspace_id,
            InventoryStockLevel.item_id == item_id,
        ).order_by(InventoryStockLevel.location_id)
        if lock:
            level_query = level_query.with_for_update()
        levels = list((await self.db.execute(level_query)).scalars().all())
        by_location = {
            level.location_id: _quantity(level.quantity_on_hand or 0) for level in levels
        }

        rows = (
            await self.db.execute(
                select(
                    InventoryJobAllocation.status,
                    InventoryJobAllocation.planned_quantity,
                    InventoryJobAllocation.actual_quantity,
                    InventoryJobAllocation.source_location_id,
                ).where(
                    InventoryJobAllocation.workspace_id == workspace_id,
                    InventoryJobAllocation.item_id == item_id,
                    InventoryJobAllocation.status.in_(_ACTIVE_STATUSES),
                )
            )
        ).all()
        reserved = Decimal("0")
        deployed = Decimal("0")
        deployed_by_location: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
        for allocation_status, planned, actual, location_id in rows:
            if allocation_status == "reserved":
                reserved += _quantity(planned)
            elif allocation_status == "deployed":
                quantity = _quantity(actual or 0)
                deployed += quantity
                if location_id is not None:
                    deployed_by_location[location_id] += quantity
        return _StockSnapshot(
            on_hand=sum(by_location.values(), Decimal("0")),
            reserved=_quantity(reserved),
            deployed=_quantity(deployed),
            by_location=by_location,
            deployed_by_location=dict(deployed_by_location),
        )

    async def _build_plan(
        self,
        job: Job,
        allocations: Sequence[InventoryJobAllocation],
    ) -> JobInventoryPlanResponse:
        snapshots: dict[uuid.UUID, _StockSnapshot] = {}
        lines: list[InventoryJobAllocationResponse] = []
        for allocation in allocations:
            snapshot = snapshots.get(allocation.item_id)
            if snapshot is None:
                snapshot = await self._stock_snapshot(job.workspace_id, allocation.item_id)
                snapshots[allocation.item_id] = snapshot
            planned = _quantity(allocation.planned_quantity)
            shortage = Decimal("0")
            if allocation.status == "reserved":
                available_for_job = (
                    snapshot.on_hand
                    - snapshot.deployed
                    - max(Decimal("0"), snapshot.reserved - planned)
                )
                shortage = max(Decimal("0"), planned - available_for_job)
            item = allocation.item
            lines.append(
                InventoryJobAllocationResponse(
                    id=allocation.id,
                    job_id=allocation.job_id,
                    item_id=allocation.item_id,
                    item_name=item.name,
                    sku=item.sku or "",
                    unit_of_measure=item.unit_of_measure,
                    behavior=cast(InventoryBehavior, allocation.behavior),
                    status=cast(InventoryAllocationStatus, allocation.status),
                    planned_quantity=float(planned),
                    actual_quantity=(
                        float(_quantity(allocation.actual_quantity))
                        if allocation.actual_quantity is not None
                        else None
                    ),
                    source_location_id=allocation.source_location_id,
                    source_location_name=(
                        allocation.source_location.name if allocation.source_location else None
                    ),
                    consumption_ledger_entry_id=allocation.consumption_ledger_entry_id,
                    quantity_on_hand=float(snapshot.on_hand),
                    quantity_reserved=float(snapshot.reserved),
                    quantity_deployed=float(snapshot.deployed),
                    available_to_promise=float(snapshot.available_to_promise),
                    shortage_quantity=float(shortage),
                    reserved_at=allocation.reserved_at,
                    fulfilled_at=allocation.fulfilled_at,
                    returned_at=allocation.returned_at,
                )
            )
        return JobInventoryPlanResponse(
            job_id=job.id,
            job_status=JobStatus(job.status).value,
            completion_confirmation_required=any(
                allocation.status == "reserved" for allocation in allocations
            ),
            allocations=lines,
        )

    @staticmethod
    def _requirements(
        fulfillment: Sequence[FulfillmentPart | dict[str, object]],
    ) -> dict[str, tuple[InventoryBehavior, Decimal, str | None]]:
        requirements: dict[str, tuple[InventoryBehavior, Decimal, str | None]] = {}
        for raw_part in fulfillment:
            part = (
                raw_part
                if isinstance(raw_part, FulfillmentPart)
                else FulfillmentPart.model_validate(raw_part)
            )
            sku = part.sku.strip()
            quantity = _quantity(part.qty)
            if not sku or quantity <= 0:
                continue
            behavior = part.inventory_behavior
            existing = requirements.get(sku)
            if existing is not None:
                if existing[0] != behavior:
                    raise ValidationError(f"Inventory SKU {sku} has conflicting behaviors")
                requirements[sku] = (behavior, existing[1] + quantity, existing[2])
            else:
                requirements[sku] = (behavior, quantity, part.description)
        return requirements

    async def reserve(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        fulfillment: Sequence[FulfillmentPart | dict[str, object]],
    ) -> list[InventoryJobAllocation]:
        """Reserve active tracked SKUs, aggregating duplicate fulfillment lines."""
        await self._job(job_id, workspace_id, lock=True)
        requirements = self._requirements(fulfillment)
        existing = await self._allocations(job_id, workspace_id, lock=True)

        items = list(
            (
                await self.db.execute(
                    select(InventoryItem).where(
                        InventoryItem.workspace_id == workspace_id,
                        InventoryItem.sku.in_(requirements),
                        InventoryItem.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        item_requirements = {
            item.id: (item, requirements[item.sku])
            for item in items
            if item.sku is not None and item.sku in requirements
        }

        if existing:
            matches = len(existing) == len(item_requirements) and all(
                allocation.item_id in item_requirements
                and allocation.status == "reserved"
                and allocation.behavior == item_requirements[allocation.item_id][1][0]
                and _quantity(allocation.planned_quantity)
                == item_requirements[allocation.item_id][1][1]
                for allocation in existing
            )
            if matches:
                return existing
            raise ConflictError(
                "This job already has a different inventory reservation",
                code="inventory_reservation_conflict",
            )

        snapshots: dict[uuid.UUID, _StockSnapshot] = {}
        shortages: list[dict[str, object]] = []
        for item_id in sorted(item_requirements, key=str):
            item, (_, required, _) = item_requirements[item_id]
            snapshot = await self._stock_snapshot(workspace_id, item_id, lock=True)
            snapshots[item_id] = snapshot
            if required > snapshot.available_to_promise:
                shortages.append(
                    {
                        "item_id": str(item.id),
                        "sku": item.sku,
                        "required_quantity": float(required),
                        "available_to_promise": float(snapshot.available_to_promise),
                        "shortage_quantity": float(required - snapshot.available_to_promise),
                    }
                )
        if shortages:
            raise ConflictError(
                "Insufficient inventory to reserve this job",
                code="insufficient_inventory",
                details={"shortages": shortages},
            )

        now = datetime.now(UTC)
        allocations = [
            InventoryJobAllocation(
                workspace_id=workspace_id,
                job_id=job_id,
                item=item,
                behavior=behavior,
                status="reserved",
                planned_quantity=required,
                reserved_at=now,
                updated_at=now,
            )
            for item, (behavior, required, _) in item_requirements.values()
        ]
        self.db.add_all(allocations)
        await self.db.flush()
        return allocations

    async def get_plan(
        self, workspace_id: uuid.UUID, job_id: uuid.UUID
    ) -> JobInventoryPlanResponse:
        job = await self._job(job_id, workspace_id)
        return await self._build_plan(job, await self._allocations(job_id, workspace_id))

    @staticmethod
    def _matches_completed_retry(
        allocations: Sequence[InventoryJobAllocation],
        requested: dict[uuid.UUID, tuple[Decimal, uuid.UUID | None]],
    ) -> bool:
        if {allocation.id for allocation in allocations} != set(requested):
            return False
        for allocation in allocations:
            quantity, source_location_id = requested[allocation.id]
            if allocation.status not in {"consumed", "deployed", "released"}:
                return False
            if _quantity(allocation.actual_quantity or 0) != quantity:
                return False
            if (
                source_location_id is not None
                and allocation.source_location_id != source_location_id
            ):
                return False
        return True

    @staticmethod
    def _completion_request(payload: CompleteJobInventoryRequest) -> _RequestedActuals:
        requested = {
            line.allocation_id: (_quantity(line.actual_quantity), line.source_location_id)
            for line in payload.allocations
        }
        if len(requested) != len(payload.allocations):
            raise ValidationError("Each allocation can appear only once")
        return requested

    @staticmethod
    def _validate_completion_state(
        job: Job,
        allocations: Sequence[InventoryJobAllocation],
        requested: _RequestedActuals,
    ) -> None:
        if JobStatus(job.status) == JobStatus.CANCELLED:
            raise ConflictError("A cancelled job cannot be completed", code="job_cancelled")
        if {allocation.id for allocation in allocations} != set(requested):
            raise ValidationError("Actual usage must include every job allocation exactly once")
        if any(allocation.status != "reserved" for allocation in allocations):
            raise ConflictError(
                "Job inventory is no longer fully reserved",
                code="inventory_allocation_state_conflict",
            )

    async def _completion_locations(
        self,
        workspace_id: uuid.UUID,
        allocations: Sequence[InventoryJobAllocation],
        requested: _RequestedActuals,
    ) -> dict[uuid.UUID, InventoryLocation]:
        locations: dict[uuid.UUID, InventoryLocation] = {}
        for allocation in allocations:
            actual, requested_location_id = requested[allocation.id]
            if actual > 0 or requested_location_id is not None:
                locations[allocation.id] = await resolve_location(
                    self.db, workspace_id, requested_location_id
                )
        return locations

    async def _completion_snapshots(
        self,
        workspace_id: uuid.UUID,
        allocations: Sequence[InventoryJobAllocation],
    ) -> dict[uuid.UUID, _StockSnapshot]:
        snapshots: dict[uuid.UUID, _StockSnapshot] = {}
        item_ids = sorted({allocation.item_id for allocation in allocations}, key=str)
        for item_id in item_ids:
            snapshots[item_id] = await self._stock_snapshot(workspace_id, item_id, lock=True)
        return snapshots

    @staticmethod
    def _completion_shortages(
        allocations: Sequence[InventoryJobAllocation],
        requested: _RequestedActuals,
        locations: dict[uuid.UUID, InventoryLocation],
        snapshots: dict[uuid.UUID, _StockSnapshot],
    ) -> list[dict[str, object]]:
        shortages: list[dict[str, object]] = []
        for allocation in allocations:
            actual, _ = requested[allocation.id]
            snapshot = snapshots[allocation.item_id]
            available_for_job = max(
                Decimal("0"),
                snapshot.on_hand
                - snapshot.deployed
                - max(
                    Decimal("0"),
                    snapshot.reserved - _quantity(allocation.planned_quantity),
                ),
            )
            if actual > available_for_job:
                shortages.append(
                    {
                        "allocation_id": str(allocation.id),
                        "sku": allocation.item.sku,
                        "required_quantity": float(actual),
                        "available_quantity": float(available_for_job),
                        "shortage_quantity": float(actual - available_for_job),
                    }
                )
                continue
            location = locations.get(allocation.id)
            if actual <= 0 or location is None:
                continue
            available_at_location = max(
                Decimal("0"),
                snapshot.by_location.get(location.id, Decimal("0"))
                - snapshot.deployed_by_location.get(location.id, Decimal("0")),
            )
            if actual > available_at_location:
                shortages.append(
                    {
                        "allocation_id": str(allocation.id),
                        "sku": allocation.item.sku,
                        "location_id": str(location.id),
                        "required_quantity": float(actual),
                        "available_quantity": float(available_at_location),
                        "shortage_quantity": float(actual - available_at_location),
                    }
                )
        return shortages

    async def _apply_completion(
        self,
        workspace_id: uuid.UUID,
        job: Job,
        allocations: Sequence[InventoryJobAllocation],
        requested: _RequestedActuals,
        locations: dict[uuid.UUID, InventoryLocation],
        *,
        created_by_id: int | None,
        completed_at: datetime,
    ) -> None:
        stock = StockService(self.db)
        for allocation in sorted(allocations, key=lambda row: str(row.item_id)):
            actual, _ = requested[allocation.id]
            location = locations.get(allocation.id)
            allocation.actual_quantity = actual
            allocation.fulfilled_at = completed_at
            allocation.updated_at = completed_at
            if location is not None:
                allocation.source_location_id = location.id
                allocation.source_location = location
            if actual == 0:
                allocation.status = "released"
            elif allocation.behavior == "consumable":
                entry = await stock.consume(
                    workspace_id,
                    allocation.item_id,
                    float(actual),
                    location_id=allocation.source_location_id,
                    reference_type="job",
                    reference_id=job.id,
                    note="Bistro inventory used on job completion",
                    created_by_id=created_by_id,
                )
                allocation.consumption_ledger_entry_id = entry.id
                allocation.status = "consumed"
            else:
                # simplification: reusable gear has no cycle depreciation; add a
                # usage/amortization ledger when per-deployment costing is required.
                allocation.status = "deployed"

    async def complete(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        payload: CompleteJobInventoryRequest,
        *,
        created_by_id: int | None = None,
    ) -> JobInventoryPlanResponse:
        """Atomically post actual consumables, deploy reusables, and complete a job."""
        job = await self._job(job_id, workspace_id, lock=True)
        allocations = await self._allocations(job_id, workspace_id, lock=True)
        if not allocations:
            raise ValidationError("This job has no inventory allocations")
        requested = self._completion_request(payload)
        if JobStatus(job.status) == JobStatus.COMPLETED:
            if self._matches_completed_retry(allocations, requested):
                return await self._build_plan(job, allocations)
            raise ConflictError(
                "The job was already completed with different inventory quantities",
                code="inventory_completion_conflict",
            )
        self._validate_completion_state(job, allocations, requested)
        locations = await self._completion_locations(workspace_id, allocations, requested)
        snapshots = await self._completion_snapshots(workspace_id, allocations)
        shortages = self._completion_shortages(allocations, requested, locations, snapshots)
        if shortages:
            raise ConflictError(
                "Insufficient inventory to complete this job",
                code="insufficient_inventory",
                details={"shortages": shortages},
            )

        completed_at = datetime.now(UTC)
        await self._apply_completion(
            workspace_id,
            job,
            allocations,
            requested,
            locations,
            created_by_id=created_by_id,
            completed_at=completed_at,
        )
        from app.services.jobs.job_service import JobService

        await JobService(self.db).complete_from_inventory(job)
        await self.db.flush()
        return await self._build_plan(job, allocations)

    async def release_for_cancel(
        self, workspace_id: uuid.UUID, job_id: uuid.UUID
    ) -> list[InventoryJobAllocation]:
        """Release reserved units; fulfilled history blocks cancellation."""
        await self._job(job_id, workspace_id, lock=True)
        allocations = await self._allocations(job_id, workspace_id, lock=True)
        if any(allocation.status in {"consumed", "deployed"} for allocation in allocations):
            raise ConflictError(
                "Consumed inventory or deployed equipment prevents cancellation",
                code="job_inventory_history",
            )
        now = datetime.now(UTC)
        for allocation in allocations:
            if allocation.status == "reserved":
                allocation.status = "released"
                allocation.actual_quantity = Decimal("0")
                allocation.fulfilled_at = now
                allocation.updated_at = now
        await self.db.flush()
        return allocations

    async def return_reusable(
        self,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        allocation_id: uuid.UUID,
    ) -> InventoryJobAllocationResponse:
        """Return deployed equipment without changing owned on-hand stock."""
        job = await self._job(job_id, workspace_id)
        query = select_workspace_owned(
            InventoryJobAllocation,
            workspace_id,
            InventoryJobAllocation.id == allocation_id,
            InventoryJobAllocation.job_id == job_id,
            options=[
                selectinload(InventoryJobAllocation.item),
                selectinload(InventoryJobAllocation.source_location),
            ],
        ).with_for_update()
        allocation = (await self.db.execute(query)).scalar_one_or_none()
        if allocation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Inventory allocation not found",
            )
        if allocation.status == "returned":
            return (await self._build_plan(job, [allocation])).allocations[0]
        if allocation.behavior != "reusable" or allocation.status != "deployed":
            raise ConflictError(
                "Only deployed reusable equipment can be returned",
                code="inventory_return_conflict",
            )
        now = datetime.now(UTC)
        allocation.status = "returned"
        allocation.returned_at = now
        allocation.updated_at = now
        await self.db.flush()
        return (await self._build_plan(job, [allocation])).allocations[0]

    async def assert_job_deletable(self, workspace_id: uuid.UUID, job_id: uuid.UUID) -> None:
        """Protect consumed history and equipment that is still out."""
        blocking = (
            await self.db.execute(
                select(InventoryJobAllocation.id)
                .where(
                    InventoryJobAllocation.workspace_id == workspace_id,
                    InventoryJobAllocation.job_id == job_id,
                    InventoryJobAllocation.status.in_({"consumed", "deployed"}),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if blocking is not None:
            raise ConflictError(
                "Return deployed equipment before deleting this job; "
                "consumed inventory history cannot be deleted",
                code="job_inventory_history",
            )
