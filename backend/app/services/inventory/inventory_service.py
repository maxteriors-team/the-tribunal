"""Inventory item and location CRUD, plus the stock-level read model.

Mirrors :class:`app.services.catalog.catalog_service.CatalogService` for the
plain CRUD parts (``get_or_404`` + ``paginate`` + ``build_response``), with two
inventory-specific rules:

- **An item is never hard-deleted while it has history.** The ledger is the
  audit trail; deleting the item would cascade it away. ``delete_item``
  therefore archives (``is_active = False``) once movements exist and only
  hard-deletes an item nobody ever moved.
- **Cost is redacted, never dropped.** Reads take ``include_costs`` (derived at
  the route from ``billing:read``); without it, quantities are served and money
  fields come back as 0.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.catalog import CatalogItem
from app.models.field_service import Crew
from app.models.inventory import (
    InventoryItem,
    InventoryJobAllocation,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryStockLevel,
)
from app.schemas.inventory import (
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryLedgerPage,
    InventoryLocationCreate,
    InventoryLocationResponse,
    InventoryLocationUpdate,
    PaginatedInventoryItems,
    StockLevelListResponse,
    StockLevelRow,
)
from app.services.exceptions import ConflictError, ValidationError
from app.services.inventory.locations import ensure_default_location, resolve_location
from app.services.inventory.stock_service import StockService

logger = structlog.get_logger()


def _as_decimal(value: float | int | None) -> Decimal | None:
    """Convert an API float to the exact ``Numeric`` type the columns store.

    Going through ``str`` avoids binary-float artifacts (``0.1 + 0.2``) landing
    in a quantity that the ledger later has to reconcile against.
    """
    if value is None:
        return None
    return Decimal(str(value))


class _ItemPosition:
    """Rolled-up on-hand position for one item across every location."""

    __slots__ = ("deployed", "last_movement_at", "quantity", "reserved", "value")

    def __init__(
        self,
        quantity: Decimal = Decimal(0),
        value: Decimal = Decimal(0),
        last_movement_at: datetime | None = None,
        reserved: Decimal = Decimal(0),
        deployed: Decimal = Decimal(0),
    ) -> None:
        self.quantity = quantity
        self.value = value
        self.last_movement_at = last_movement_at
        self.reserved = reserved
        self.deployed = deployed


class InventoryService:
    """CRUD over tracked items and stock locations, plus on-hand reads."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="inventory_service")

    # ------------------------------------------------------------------ #
    # Positions (shared by item reads)
    # ------------------------------------------------------------------ #
    async def _positions(
        self, workspace_id: uuid.UUID, item_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, _ItemPosition]:
        """Aggregate the stock-level cache per item, across all locations."""
        if not item_ids:
            return {}
        rows = (
            await self.db.execute(
                select(
                    InventoryStockLevel.item_id,
                    func.sum(InventoryStockLevel.quantity_on_hand),
                    func.sum(InventoryStockLevel.total_value),
                    func.max(InventoryStockLevel.last_movement_at),
                )
                .where(
                    InventoryStockLevel.workspace_id == workspace_id,
                    InventoryStockLevel.item_id.in_(item_ids),
                )
                .group_by(InventoryStockLevel.item_id)
            )
        ).all()
        positions = {
            item_id: _ItemPosition(
                quantity=Decimal(quantity or 0),
                value=Decimal(value or 0),
                last_movement_at=last_movement_at,
            )
            for item_id, quantity, value, last_movement_at in rows
        }
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
            position = positions.setdefault(item_id, _ItemPosition())
            if allocation_status == "reserved":
                position.reserved += Decimal(planned or 0)
            else:
                position.deployed += Decimal(actual or 0)
        return positions

    @staticmethod
    def _item_response(
        item: InventoryItem,
        position: _ItemPosition | None,
        *,
        include_costs: bool = True,
    ) -> InventoryItemResponse:
        """Serialize an item with its rolled-up position, redacting money."""
        quantity = float(position.quantity if position else 0)
        reserved = float(position.reserved if position else 0)
        deployed = float(position.deployed if position else 0)
        available = quantity - reserved - deployed
        value = float(position.value if position else 0)
        reorder_point = float(item.reorder_point) if item.reorder_point is not None else None
        avg_cost = value / quantity if quantity else 0.0
        return InventoryItemResponse(
            id=item.id,
            workspace_id=item.workspace_id,
            catalog_item_id=item.catalog_item_id,
            name=item.name,
            sku=item.sku,
            unit_of_measure=item.unit_of_measure,
            is_active=item.is_active,
            valuation_method=item.valuation_method,  # type: ignore[arg-type]
            reorder_point=reorder_point,
            reorder_quantity=(
                float(item.reorder_quantity) if item.reorder_quantity is not None else None
            ),
            safety_stock=float(item.safety_stock or 0),
            lead_time_days=item.lead_time_days,
            supplier_name=item.supplier_name,
            supplier_sku=item.supplier_sku,
            notes=item.notes,
            quantity_on_hand=round(quantity, 4),
            quantity_reserved=round(reserved, 4),
            quantity_deployed=round(deployed, 4),
            available_to_promise=round(available, 4),
            total_value=round(value, 2) if include_costs else 0.0,
            avg_unit_cost=round(avg_cost, 4) if include_costs else 0.0,
            is_low_stock=(
                reorder_point is not None and item.is_active and available <= reorder_point
            ),
            last_movement_at=position.last_movement_at if position else None,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )

    # ------------------------------------------------------------------ #
    # Items
    # ------------------------------------------------------------------ #
    async def list_items(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        search: str | None = None,
        low_stock_only: bool = False,
        include_inactive: bool = False,
        include_costs: bool = True,
    ) -> PaginatedInventoryItems:
        """List tracked items alphabetically, with their on-hand position."""
        query: Select[tuple[InventoryItem]] = select_workspace_owned(InventoryItem, workspace_id)
        if not include_inactive:
            query = query.where(InventoryItem.is_active.is_(True))
        if search:
            term = f"%{search.strip()}%"
            query = query.where(
                or_(
                    InventoryItem.name.ilike(term),
                    InventoryItem.sku.ilike(term),
                    InventoryItem.supplier_name.ilike(term),
                )
            )
        if low_stock_only:
            # Aggregate across locations: an empty truck is not a reorder signal
            # while the warehouse is full.
            on_hand = (
                select(func.coalesce(func.sum(InventoryStockLevel.quantity_on_hand), 0))
                .where(
                    InventoryStockLevel.workspace_id == workspace_id,
                    InventoryStockLevel.item_id == InventoryItem.id,
                )
                .scalar_subquery()
            )
            reserved = (
                select(func.coalesce(func.sum(InventoryJobAllocation.planned_quantity), 0))
                .where(
                    InventoryJobAllocation.workspace_id == workspace_id,
                    InventoryJobAllocation.item_id == InventoryItem.id,
                    InventoryJobAllocation.status == "reserved",
                )
                .scalar_subquery()
            )
            deployed = (
                select(func.coalesce(func.sum(InventoryJobAllocation.actual_quantity), 0))
                .where(
                    InventoryJobAllocation.workspace_id == workspace_id,
                    InventoryJobAllocation.item_id == InventoryItem.id,
                    InventoryJobAllocation.status == "deployed",
                )
                .scalar_subquery()
            )
            query = query.where(
                InventoryItem.reorder_point.isnot(None),
                on_hand - reserved - deployed <= InventoryItem.reorder_point,
            )
        query = query.order_by(InventoryItem.name.asc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        items = list(result.items)
        positions = await self._positions(workspace_id, [item.id for item in items])
        return PaginatedInventoryItems(
            **result.to_dict(
                [
                    self._item_response(item, positions.get(item.id), include_costs=include_costs)
                    for item in items
                ]
            )
        )

    async def get_item(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        include_costs: bool = True,
    ) -> InventoryItemResponse:
        """Fetch one tracked item with its rolled-up position."""
        item = await assert_workspace_owned(
            self.db, InventoryItem, item_id, workspace_id, detail="Inventory item not found"
        )
        positions = await self._positions(workspace_id, [item.id])
        return self._item_response(item, positions.get(item.id), include_costs=include_costs)

    async def _assert_catalog_item(
        self, catalog_item_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> None:
        await assert_workspace_owned(
            self.db,
            CatalogItem,
            catalog_item_id,
            workspace_id,
            detail="Catalog item not found",
        )

    async def create_item(
        self,
        workspace_id: uuid.UUID,
        payload: InventoryItemCreate,
        *,
        created_by_id: int | None = None,
    ) -> InventoryItemResponse:
        """Create a tracked item (no stock; movements come from the ledger)."""
        if payload.catalog_item_id is not None:
            await self._assert_catalog_item(payload.catalog_item_id, workspace_id)
            await self._assert_catalog_link_free(workspace_id, payload.catalog_item_id)
        await self._assert_sku_free(workspace_id, payload.sku)

        item = InventoryItem(
            workspace_id=workspace_id,
            catalog_item_id=payload.catalog_item_id,
            name=payload.name,
            sku=payload.sku,
            unit_of_measure=payload.unit_of_measure,
            is_active=payload.is_active,
            valuation_method=payload.valuation_method,
            reorder_point=_as_decimal(payload.reorder_point),
            reorder_quantity=_as_decimal(payload.reorder_quantity),
            safety_stock=_as_decimal(payload.safety_stock),
            lead_time_days=payload.lead_time_days,
            supplier_name=payload.supplier_name,
            supplier_sku=payload.supplier_sku,
            notes=payload.notes,
            created_by_id=created_by_id,
        )
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        self.log.info(
            "inventory_item_created",
            item_id=str(item.id),
            workspace_id=str(workspace_id),
            name=item.name,
        )
        return self._item_response(item, None)

    async def _assert_sku_free(
        self,
        workspace_id: uuid.UUID,
        sku: str | None,
        *,
        exclude_item_id: uuid.UUID | None = None,
    ) -> None:
        """Reject a duplicate SKU with 409 instead of a raw unique-index 500."""
        if not sku:
            return
        criteria: list[Any] = [InventoryItem.sku == sku]
        if exclude_item_id is not None:
            criteria.append(InventoryItem.id != exclude_item_id)
        clash = (
            (await self.db.execute(select_workspace_owned(InventoryItem, workspace_id, *criteria)))
            .scalars()
            .first()
        )
        if clash is not None:
            raise ConflictError(f"SKU {sku!r} is already used by {clash.name!r}")

    async def _assert_catalog_link_free(
        self,
        workspace_id: uuid.UUID,
        catalog_item_id: uuid.UUID,
        *,
        exclude_item_id: uuid.UUID | None = None,
    ) -> None:
        criteria: list[Any] = [InventoryItem.catalog_item_id == catalog_item_id]
        if exclude_item_id is not None:
            criteria.append(InventoryItem.id != exclude_item_id)
        clash = (
            (await self.db.execute(select_workspace_owned(InventoryItem, workspace_id, *criteria)))
            .scalars()
            .first()
        )
        if clash is not None:
            raise ConflictError(
                f"That price-book item is already tracked as {clash.name!r}",
            )

    async def update_item(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: InventoryItemUpdate,
        *,
        include_costs: bool = True,
    ) -> InventoryItemResponse:
        """Update a tracked item. Only supplied fields change.

        ``reorder_point``, ``reorder_quantity``, ``lead_time_days`` and
        ``catalog_item_id`` are cleared by an explicit ``null`` — without that,
        an operator could set a reorder point but never un-manage the item.
        """
        item = await assert_workspace_owned(
            self.db, InventoryItem, item_id, workspace_id, detail="Inventory item not found"
        )
        fields_set = payload.model_fields_set

        if "sku" in fields_set:
            await self._assert_sku_free(workspace_id, payload.sku, exclude_item_id=item.id)
            item.sku = payload.sku
        if "catalog_item_id" in fields_set:
            if payload.catalog_item_id is not None:
                await self._assert_catalog_item(payload.catalog_item_id, workspace_id)
                await self._assert_catalog_link_free(
                    workspace_id, payload.catalog_item_id, exclude_item_id=item.id
                )
            item.catalog_item_id = payload.catalog_item_id

        for field in (
            "name",
            "unit_of_measure",
            "is_active",
            "valuation_method",
            "supplier_name",
            "supplier_sku",
            "notes",
        ):
            value = getattr(payload, field)
            if value is not None:
                setattr(item, field, value)

        if payload.safety_stock is not None:
            item.safety_stock = Decimal(str(payload.safety_stock))
        if "reorder_point" in fields_set:
            item.reorder_point = _as_decimal(payload.reorder_point)
        if "reorder_quantity" in fields_set:
            item.reorder_quantity = _as_decimal(payload.reorder_quantity)
        if "lead_time_days" in fields_set:
            item.lead_time_days = payload.lead_time_days

        await self.db.flush()
        await self.db.refresh(item)
        positions = await self._positions(workspace_id, [item.id])
        return self._item_response(item, positions.get(item.id), include_costs=include_costs)

    async def delete_item(self, workspace_id: uuid.UUID, item_id: uuid.UUID) -> None:
        """Delete an unused item; archive one with movements or allocations.

        Ledger and allocation rows are inventory history, so neither may be
        removed by deleting the item they describe.
        """
        item = await assert_workspace_owned(
            self.db, InventoryItem, item_id, workspace_id, detail="Inventory item not found"
        )
        has_history = (
            await self.db.execute(
                select(InventoryLedgerEntry.id)
                .where(
                    InventoryLedgerEntry.workspace_id == workspace_id,
                    InventoryLedgerEntry.item_id == item_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        has_allocation = (
            await self.db.execute(
                select(InventoryJobAllocation.id)
                .where(
                    InventoryJobAllocation.workspace_id == workspace_id,
                    InventoryJobAllocation.item_id == item_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if has_history is not None or has_allocation is not None:
            item.is_active = False
            await self.db.flush()
            self.log.info("inventory_item_archived", item_id=str(item_id))
            return
        await self.db.delete(item)
        await self.db.flush()

    # ------------------------------------------------------------------ #
    # Ledger reads
    # ------------------------------------------------------------------ #
    async def list_ledger(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        include_costs: bool = True,
    ) -> InventoryLedgerPage:
        """Movement history for one item, newest first."""
        item = await assert_workspace_owned(
            self.db, InventoryItem, item_id, workspace_id, detail="Inventory item not found"
        )
        query = select_workspace_owned(
            InventoryLedgerEntry,
            workspace_id,
            InventoryLedgerEntry.item_id == item_id,
        ).order_by(InventoryLedgerEntry.created_at.desc())
        result = await paginate(self.db, query, page=page, page_size=page_size)

        entries = list(result.items)
        location_names = await self._location_names(
            workspace_id, [entry.location_id for entry in entries]
        )
        return InventoryLedgerPage(
            **result.to_dict(
                [
                    StockService.entry_response(
                        entry,
                        item_name=item.name,
                        location_name=location_names.get(entry.location_id),
                        include_costs=include_costs,
                    )
                    for entry in entries
                ]
            )
        )

    async def _location_names(
        self, workspace_id: uuid.UUID, location_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        if not location_ids:
            return {}
        rows = (
            await self.db.execute(
                select(InventoryLocation.id, InventoryLocation.name).where(
                    InventoryLocation.workspace_id == workspace_id,
                    InventoryLocation.id.in_(set(location_ids)),
                )
            )
        ).all()
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------ #
    # Stock levels
    # ------------------------------------------------------------------ #
    async def list_stock(
        self,
        workspace_id: uuid.UUID,
        *,
        location_id: uuid.UUID | None = None,
        low_stock: bool = False,
        include_costs: bool = True,
    ) -> StockLevelListResponse:
        """Every on-hand position, optionally filtered to one location or to low stock.

        ``low_stock`` compares the item's **workspace-wide** on-hand against its
        reorder point, then lists the rows that make it up — so a low item shows
        which bins hold what is left.
        """
        query = (
            select(InventoryStockLevel, InventoryItem, InventoryLocation)
            .join(InventoryItem, InventoryItem.id == InventoryStockLevel.item_id)
            .join(InventoryLocation, InventoryLocation.id == InventoryStockLevel.location_id)
            .where(
                InventoryStockLevel.workspace_id == workspace_id,
                InventoryItem.is_active.is_(True),
            )
            .order_by(InventoryItem.name.asc(), InventoryLocation.name.asc())
        )
        if location_id is not None:
            await resolve_location(self.db, workspace_id, location_id)
            query = query.where(InventoryStockLevel.location_id == location_id)

        rows = (await self.db.execute(query)).all()

        positions = await self._positions(
            workspace_id, list({level.item_id for level, _item, _location in rows})
        )

        result: list[StockLevelRow] = []
        total_value = 0.0
        for level, item, location in rows:
            reorder_point = float(item.reorder_point) if item.reorder_point is not None else None
            position = positions.get(item.id, _ItemPosition())
            item_total = float(position.quantity)
            reserved = float(position.reserved)
            deployed = float(position.deployed)
            available = item_total - reserved - deployed
            is_low = reorder_point is not None and available <= reorder_point
            if low_stock and not is_low:
                continue
            value = float(level.total_value or 0)
            total_value += value
            result.append(
                StockLevelRow(
                    item_id=item.id,
                    item_name=item.name,
                    sku=item.sku,
                    unit_of_measure=item.unit_of_measure,
                    location_id=location.id,
                    location_name=location.name,
                    quantity_on_hand=float(level.quantity_on_hand or 0),
                    quantity_reserved=round(reserved, 4),
                    quantity_deployed=round(deployed, 4),
                    available_to_promise=round(available, 4),
                    total_value=round(value, 2) if include_costs else 0.0,
                    avg_unit_cost=(
                        round(float(level.avg_unit_cost or 0), 4) if include_costs else 0.0
                    ),
                    reorder_point=reorder_point,
                    is_low_stock=is_low,
                    last_movement_at=level.last_movement_at,
                )
            )

        return StockLevelListResponse(
            items=result,
            total=len(result),
            total_value=round(total_value, 2) if include_costs else 0.0,
        )

    # ------------------------------------------------------------------ #
    # Locations
    # ------------------------------------------------------------------ #
    async def list_locations(
        self, workspace_id: uuid.UUID, *, include_inactive: bool = False
    ) -> list[InventoryLocationResponse]:
        """List stock locations, default first, then alphabetically."""
        criteria = [] if include_inactive else [InventoryLocation.is_active.is_(True)]
        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(InventoryLocation, workspace_id, *criteria).order_by(
                        InventoryLocation.is_default.desc(), InventoryLocation.name.asc()
                    )
                )
            )
            .scalars()
            .all()
        )
        return [InventoryLocationResponse.model_validate(row) for row in rows]

    async def ensure_default_location(self, workspace_id: uuid.UUID) -> InventoryLocationResponse:
        """Return (creating if needed) the workspace's fallback location."""
        location = await ensure_default_location(self.db, workspace_id)
        return InventoryLocationResponse.model_validate(location)

    async def _assert_location_name_free(
        self,
        workspace_id: uuid.UUID,
        name: str,
        *,
        exclude_location_id: uuid.UUID | None = None,
    ) -> None:
        criteria: list[Any] = [func.lower(InventoryLocation.name) == name.strip().lower()]
        if exclude_location_id is not None:
            criteria.append(InventoryLocation.id != exclude_location_id)
        clash = (
            (
                await self.db.execute(
                    select_workspace_owned(InventoryLocation, workspace_id, *criteria)
                )
            )
            .scalars()
            .first()
        )
        if clash is not None:
            raise ConflictError(f"A location named {name!r} already exists")

    async def _clear_other_defaults(
        self, workspace_id: uuid.UUID, keep_id: uuid.UUID | None
    ) -> None:
        """Exactly one default: promoting a location demotes the previous one."""
        criteria: list[Any] = [InventoryLocation.is_default.is_(True)]
        if keep_id is not None:
            criteria.append(InventoryLocation.id != keep_id)
        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(InventoryLocation, workspace_id, *criteria)
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.is_default = False

    async def _assert_crew(self, crew_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
        await assert_workspace_owned(self.db, Crew, crew_id, workspace_id, detail="Crew not found")

    async def create_location(
        self, workspace_id: uuid.UUID, payload: InventoryLocationCreate
    ) -> InventoryLocationResponse:
        """Create a stock location."""
        await self._assert_location_name_free(workspace_id, payload.name)
        if payload.crew_id is not None:
            await self._assert_crew(payload.crew_id, workspace_id)

        location = InventoryLocation(
            workspace_id=workspace_id,
            name=payload.name.strip(),
            kind=payload.kind,
            crew_id=payload.crew_id,
            is_active=payload.is_active,
            is_default=payload.is_default,
        )
        self.db.add(location)
        await self.db.flush()
        if payload.is_default:
            await self._clear_other_defaults(workspace_id, location.id)
            await self.db.flush()
        await self.db.refresh(location)
        return InventoryLocationResponse.model_validate(location)

    async def update_location(
        self,
        workspace_id: uuid.UUID,
        location_id: uuid.UUID,
        payload: InventoryLocationUpdate,
    ) -> InventoryLocationResponse:
        """Update a stock location. Only supplied fields change."""
        location = await assert_workspace_owned(
            self.db,
            InventoryLocation,
            location_id,
            workspace_id,
            detail="Inventory location not found",
        )
        fields_set = payload.model_fields_set

        if payload.name is not None:
            await self._assert_location_name_free(
                workspace_id, payload.name, exclude_location_id=location.id
            )
            location.name = payload.name.strip()
        if "crew_id" in fields_set:
            if payload.crew_id is not None:
                await self._assert_crew(payload.crew_id, workspace_id)
            location.crew_id = payload.crew_id
        if payload.kind is not None:
            location.kind = payload.kind
        if payload.is_active is not None:
            location.is_active = payload.is_active
        if payload.is_default is not None:
            location.is_default = payload.is_default
            if payload.is_default:
                await self._clear_other_defaults(workspace_id, location.id)

        await self.db.flush()
        await self.db.refresh(location)
        return InventoryLocationResponse.model_validate(location)

    async def delete_location(self, workspace_id: uuid.UUID, location_id: uuid.UUID) -> None:
        """Delete a location that never held stock; refuse one with history.

        The ledger FK is ``ON DELETE RESTRICT`` on purpose — losing where stock
        went is worse than keeping a location an operator wanted gone, so this
        raises 409 with the reason instead of surfacing a database error.
        """
        location = await assert_workspace_owned(
            self.db,
            InventoryLocation,
            location_id,
            workspace_id,
            detail="Inventory location not found",
        )
        has_history = (
            await self.db.execute(
                select(InventoryLedgerEntry.id)
                .where(
                    InventoryLedgerEntry.workspace_id == workspace_id,
                    InventoryLedgerEntry.location_id == location_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if has_history is not None:
            raise ConflictError(
                f"{location.name!r} has stock movements and cannot be deleted; "
                "mark it inactive instead.",
                code="location_has_history",
            )
        if location.is_default:
            raise ValidationError(
                "The default location cannot be deleted; make another location the default first."
            )
        await self.db.delete(location)
        await self.db.flush()
