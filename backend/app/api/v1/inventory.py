"""Inventory endpoints: tracked items, stock movements, locations, reordering.

Thin transport over :mod:`app.services.inventory`. Two access rules run through
every route here:

- **Reads are ``jobs:read``, writes that change value are ``billing:write``.** A
  field technician must be able to see what is on the truck and burn it on a
  job (``jobs:write``); deciding what a receipt cost, or correcting a count, is
  a billing action.
- **Money is redacted, not withheld.** Reads pass ``include_costs``, derived
  from ``billing:read`` exactly as :mod:`app.api.v1.jobs` does for time entries,
  so a caller below that tier gets quantities with every cost field served as 0.
  A client-supplied ``unit_cost`` on an outbound movement is never read at all —
  the schemas for those movements have no such field.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import (
    DB,
    CanReadJobs,
    CanWriteBilling,
    CanWriteJobs,
    CurrentUser,
    TransactionalDB,
)
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability, role_can
from app.models.workspace import WorkspaceMembership
from app.schemas.inventory import (
    AdjustStockRequest,
    InventoryItemCreate,
    InventoryItemResponse,
    InventoryItemUpdate,
    InventoryLedgerEntryResponse,
    InventoryLedgerPage,
    InventoryLocationCreate,
    InventoryLocationResponse,
    InventoryLocationUpdate,
    PaginatedInventoryItems,
    ReceiveStockRequest,
    ReorderReport,
    ReorderSuggestion,
    StockLevelListResponse,
    TransferStockRequest,
)
from app.services.inventory import InventoryService, ReorderService, StockService

router = APIRouter(route_class=ServiceErrorRoute)


def _can_see_costs(membership: WorkspaceMembership) -> bool:
    """Whether this caller may see inventory money (unit costs, stock value)."""
    return role_can(membership.role, Capability.BILLING_READ)


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
@router.get("/items", response_model=PaginatedInventoryItems)
async def list_inventory_items(
    membership: CanReadJobs,
    db: DB,
    search: Annotated[str | None, Query()] = None,
    low_stock: Annotated[bool, Query(description="Only items at or below reorder point")] = False,
    include_inactive: Annotated[bool, Query()] = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> PaginatedInventoryItems:
    """List tracked items with their on-hand position (costs need billing:read)."""
    return await InventoryService(db).list_items(
        membership.workspace_id,
        page=page,
        page_size=page_size,
        search=search,
        low_stock_only=low_stock,
        include_inactive=include_inactive,
        include_costs=_can_see_costs(membership),
    )


@router.post("/items", response_model=InventoryItemResponse, status_code=status.HTTP_201_CREATED)
async def create_inventory_item(
    payload: InventoryItemCreate,
    membership: CanWriteBilling,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> InventoryItemResponse:
    """Create a tracked item. Stock arrives later, through a receipt."""
    return await InventoryService(db).create_item(
        membership.workspace_id, payload, created_by_id=current_user.id
    )


@router.get("/items/{item_id}", response_model=InventoryItemResponse)
async def get_inventory_item(
    item_id: uuid.UUID,
    membership: CanReadJobs,
    db: DB,
) -> InventoryItemResponse:
    """Get one tracked item with its rolled-up position."""
    return await InventoryService(db).get_item(
        membership.workspace_id, item_id, include_costs=_can_see_costs(membership)
    )


@router.put("/items/{item_id}", response_model=InventoryItemResponse)
async def update_inventory_item(
    item_id: uuid.UUID,
    payload: InventoryItemUpdate,
    membership: CanWriteBilling,
    db: TransactionalDB,
) -> InventoryItemResponse:
    """Update an item's details or its reorder settings."""
    return await InventoryService(db).update_item(
        membership.workspace_id, item_id, payload, include_costs=_can_see_costs(membership)
    )


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventory_item(
    item_id: uuid.UUID,
    membership: CanWriteBilling,
    db: TransactionalDB,
) -> None:
    """Delete an item that never moved; archive one that has stock history."""
    await InventoryService(db).delete_item(membership.workspace_id, item_id)


@router.get("/items/{item_id}/ledger", response_model=InventoryLedgerPage)
async def list_item_ledger(
    item_id: uuid.UUID,
    membership: CanReadJobs,
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> InventoryLedgerPage:
    """Movement history for one item, newest first (costs need billing:read)."""
    return await InventoryService(db).list_ledger(
        membership.workspace_id,
        item_id,
        page=page,
        page_size=page_size,
        include_costs=_can_see_costs(membership),
    )


@router.get("/items/{item_id}/reorder-suggestion", response_model=ReorderSuggestion)
async def suggest_item_reorder_point(
    item_id: uuid.UUID,
    membership: CanReadJobs,
    db: DB,
) -> ReorderSuggestion:
    """Suggest a reorder point from trailing usage. Never applies it."""
    return await ReorderService(db).suggest_reorder_point(membership.workspace_id, item_id)


# --------------------------------------------------------------------------- #
# Movements
# --------------------------------------------------------------------------- #
@router.post(
    "/items/{item_id}/receipts",
    response_model=InventoryLedgerEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def receive_stock(
    item_id: uuid.UUID,
    payload: ReceiveStockRequest,
    membership: CanWriteBilling,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> InventoryLedgerEntryResponse:
    """Receive stock at a known unit cost (this is what sets the average)."""
    entry = await StockService(db).receive(
        membership.workspace_id, item_id, payload, created_by_id=current_user.id
    )
    return StockService.entry_response(entry, include_costs=_can_see_costs(membership))


@router.post(
    "/items/{item_id}/adjustments",
    response_model=InventoryLedgerEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def adjust_stock(
    item_id: uuid.UUID,
    payload: AdjustStockRequest,
    membership: CanWriteBilling,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> InventoryLedgerEntryResponse:
    """Reconcile to a physical count, or write stock off as shrinkage."""
    entry = await StockService(db).adjust(
        membership.workspace_id, item_id, payload, created_by_id=current_user.id
    )
    return StockService.entry_response(entry, include_costs=_can_see_costs(membership))


@router.post(
    "/transfers",
    response_model=list[InventoryLedgerEntryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def transfer_stock(
    payload: TransferStockRequest,
    membership: CanWriteJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> list[InventoryLedgerEntryResponse]:
    """Move stock between locations (warehouse to truck), value included.

    ``jobs:write``, not ``billing:write``: loading a van is dispatch work and
    the transfer cannot change what the workspace's stock is worth.
    """
    out_entry, in_entry = await StockService(db).transfer(
        membership.workspace_id, payload, created_by_id=current_user.id
    )
    include_costs = _can_see_costs(membership)
    return [
        StockService.entry_response(out_entry, include_costs=include_costs),
        StockService.entry_response(in_entry, include_costs=include_costs),
    ]


# --------------------------------------------------------------------------- #
# Stock levels and reordering
# --------------------------------------------------------------------------- #
@router.get("/stock", response_model=StockLevelListResponse)
async def list_stock_levels(
    membership: CanReadJobs,
    db: DB,
    location_id: Annotated[uuid.UUID | None, Query()] = None,
    low_stock: Annotated[bool, Query()] = False,
) -> StockLevelListResponse:
    """On-hand positions per item and location."""
    return await InventoryService(db).list_stock(
        membership.workspace_id,
        location_id=location_id,
        low_stock=low_stock,
        include_costs=_can_see_costs(membership),
    )


@router.get("/reorder-report", response_model=ReorderReport)
async def reorder_report(
    membership: CanReadJobs,
    db: DB,
    lookback_days: Annotated[int, Query(ge=7, le=365)] = 90,
) -> ReorderReport:
    """Items at or below their reorder point, most urgent first."""
    return await ReorderService(db).low_stock(membership.workspace_id, lookback_days=lookback_days)


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
@router.get("/locations", response_model=list[InventoryLocationResponse])
async def list_inventory_locations(
    membership: CanReadJobs,
    db: DB,
    include_inactive: Annotated[bool, Query()] = False,
) -> list[InventoryLocationResponse]:
    """List stock locations, default first."""
    return await InventoryService(db).list_locations(
        membership.workspace_id, include_inactive=include_inactive
    )


@router.post(
    "/locations",
    response_model=InventoryLocationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inventory_location(
    payload: InventoryLocationCreate,
    membership: CanWriteBilling,
    db: TransactionalDB,
) -> InventoryLocationResponse:
    """Create a warehouse or truck."""
    return await InventoryService(db).create_location(membership.workspace_id, payload)


@router.put("/locations/{location_id}", response_model=InventoryLocationResponse)
async def update_inventory_location(
    location_id: uuid.UUID,
    payload: InventoryLocationUpdate,
    membership: CanWriteBilling,
    db: TransactionalDB,
) -> InventoryLocationResponse:
    """Rename a location, reassign its crew, or make it the default."""
    return await InventoryService(db).update_location(membership.workspace_id, location_id, payload)


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inventory_location(
    location_id: uuid.UUID,
    membership: CanWriteBilling,
    db: TransactionalDB,
) -> None:
    """Delete a location that never held stock (409 once it has history)."""
    await InventoryService(db).delete_location(membership.workspace_id, location_id)
