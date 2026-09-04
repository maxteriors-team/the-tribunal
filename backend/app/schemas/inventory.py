"""Inventory schemas: items, locations, movements, stock levels, reorder rows.

Follows :mod:`app.schemas.catalog` conventions — ``float`` quantities/money in
major units, ``from_attributes`` responses, server-managed fields response-only.

Two rules are enforced at the schema boundary and repeated in the service:

- **Outbound movements never accept a cost.** ``consume``/``write_off`` payloads
  have no ``unit_cost`` field at all: the cost is the server-side weighted
  average at posting time. A client that could name its own cost could name its
  own margin.
- **Money is redacted, not omitted, for callers without ``billing:read``.** Cost
  fields stay in the response shape and are served as ``0`` so a field tech sees
  "3 buckets left on the truck" without seeing what they cost.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

InventoryLocationKind = Literal["warehouse", "truck", "other"]
InventoryValuationMethod = Literal["weighted_average"]
InventoryLedgerReason = Literal[
    "receipt",
    "job_usage",
    "sale",
    "adjustment",
    "shrinkage",
    "return_to_stock",
    "transfer_in",
    "transfer_out",
    "opening_balance",
]
InventoryReferenceType = Literal["job", "invoice", "quote", "manual", "transfer"]
InventoryBehavior = Literal["consumable", "reusable"]
InventoryAllocationStatus = Literal["reserved", "consumed", "deployed", "released", "returned"]
COGSGroupBy = Literal["item", "service_category", "job"]


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #
class InventoryLocationBase(BaseModel):
    """Client-settable fields on a stock location."""

    name: str = Field(min_length=1, max_length=120)
    kind: InventoryLocationKind = "warehouse"
    crew_id: uuid.UUID | None = Field(
        default=None, description="Owning crew when this location is a truck"
    )
    is_active: bool = True
    is_default: bool = Field(
        default=False,
        description="Fallback location used when a movement names none",
    )


class InventoryLocationCreate(InventoryLocationBase):
    """Create a stock location."""


class InventoryLocationUpdate(BaseModel):
    """Update a stock location (all fields optional)."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    kind: InventoryLocationKind | None = None
    crew_id: uuid.UUID | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class InventoryLocationResponse(InventoryLocationBase):
    """A stock location as returned by the API."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
def _normalize_service_category(value: str | None) -> str | None:
    """Treat blank service labels as uncategorized and store clean display text."""
    if value is None:
        return None
    return value.strip() or None


class InventoryItemBase(BaseModel):
    """Client-settable fields on a tracked item."""

    name: str = Field(min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=100)
    catalog_item_id: uuid.UUID | None = Field(
        default=None, description="Optional link to a price-book item in the same workspace"
    )
    service_category: str | None = Field(default=None, max_length=60)
    unit_of_measure: str = Field(default="each", min_length=1, max_length=30)
    is_active: bool = True
    valuation_method: InventoryValuationMethod = "weighted_average"
    # NULL means "not managed": the item never raises a low-stock alert.
    reorder_point: float | None = Field(default=None, ge=0)
    reorder_quantity: float | None = Field(default=None, ge=0)
    safety_stock: float = Field(default=0.0, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    supplier_name: str | None = Field(default=None, max_length=255)
    supplier_sku: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    _strip_service_category = field_validator("service_category")(_normalize_service_category)


class InventoryItemCreate(InventoryItemBase):
    """Create a tracked item."""


class InventoryItemUpdate(BaseModel):
    """Update a tracked item (all fields optional).

    ``reorder_point``, ``reorder_quantity``, ``lead_time_days``,
    ``catalog_item_id`` and ``service_category`` are cleared by an explicit
    ``null`` (the service checks ``model_fields_set``).
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=100)
    catalog_item_id: uuid.UUID | None = None
    service_category: str | None = Field(default=None, max_length=60)
    unit_of_measure: str | None = Field(default=None, min_length=1, max_length=30)
    is_active: bool | None = None
    valuation_method: InventoryValuationMethod | None = None
    reorder_point: float | None = Field(default=None, ge=0)
    reorder_quantity: float | None = Field(default=None, ge=0)
    safety_stock: float | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    supplier_name: str | None = Field(default=None, max_length=255)
    supplier_sku: str | None = Field(default=None, max_length=100)
    notes: str | None = None

    _strip_service_category = field_validator("service_category")(_normalize_service_category)


class InventoryItemResponse(InventoryItemBase):
    """A tracked item as returned by the API, with its rolled-up stock position.

    ``quantity_on_hand`` sums every location; ``total_value``/``avg_unit_cost``
    are redacted to 0 for callers without ``billing:read``.
    """

    id: uuid.UUID
    workspace_id: uuid.UUID
    quantity_on_hand: float = 0.0
    quantity_reserved: float = 0.0
    quantity_deployed: float = 0.0
    available_to_promise: float = 0.0
    total_value: float = 0.0
    avg_unit_cost: float = 0.0
    is_low_stock: bool = False
    last_movement_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedInventoryItems(BaseModel):
    """Paginated list of tracked items."""

    items: list[InventoryItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


# --------------------------------------------------------------------------- #
# Movements
# --------------------------------------------------------------------------- #
class ReceiveStockRequest(BaseModel):
    """Bring stock in at a known cost (the only movement that sets one)."""

    quantity: float = Field(gt=0)
    unit_cost: float = Field(default=0.0, ge=0, description="Cost per unit in major units")
    location_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the workspace's default location"
    )
    reference_type: InventoryReferenceType | None = None
    reference_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    note: str | None = None


class AdjustStockRequest(BaseModel):
    """Reconcile to a counted quantity, or write off shrinkage.

    ``quantity_on_hand`` is the **absolute** counted number; the service posts
    the signed delta. ``write_off_quantity`` instead removes a known amount as
    ``shrinkage`` so waste is reported apart from cost of goods sold. Exactly
    one of the two must be supplied.
    """

    quantity_on_hand: float | None = Field(
        default=None, ge=0, description="Absolute counted quantity at this location"
    )
    write_off_quantity: float | None = Field(
        default=None, gt=0, description="Quantity to remove as shrinkage"
    )
    location_id: uuid.UUID | None = None
    occurred_at: datetime | None = None
    note: str | None = None


class TransferStockRequest(BaseModel):
    """Move stock between two locations at the source's weighted-average cost."""

    item_id: uuid.UUID
    from_location_id: uuid.UUID
    to_location_id: uuid.UUID
    quantity: float = Field(gt=0)
    occurred_at: datetime | None = None
    note: str | None = None


class JobMaterialCreate(BaseModel):
    """Consume stock on a job. No cost field: the server values it."""

    item_id: uuid.UUID
    quantity: float = Field(gt=0)
    location_id: uuid.UUID | None = None
    note: str | None = None


class InventoryLedgerEntryResponse(BaseModel):
    """One posted movement.

    ``unit_cost``/``value_delta``/``value_after``/``unit_cost_after`` are
    redacted to 0 for callers without ``billing:read``; quantities always serve.
    """

    id: uuid.UUID
    item_id: uuid.UUID
    item_name: str | None = None
    location_id: uuid.UUID
    location_name: str | None = None
    quantity_delta: float
    unit_cost: float
    value_delta: float
    reason: InventoryLedgerReason
    reference_type: str | None = None
    reference_id: uuid.UUID | None = None
    occurred_at: datetime
    note: str | None = None
    quantity_after: float
    value_after: float
    unit_cost_after: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryLedgerPage(BaseModel):
    """Paginated movement history for one item."""

    items: list[InventoryLedgerEntryResponse]
    total: int
    page: int
    page_size: int
    pages: int


class InventoryJobAllocationResponse(BaseModel):
    """One planned or fulfilled job allocation and its current stock position."""

    id: uuid.UUID
    job_id: uuid.UUID
    item_id: uuid.UUID
    item_name: str
    sku: str
    unit_of_measure: str
    behavior: InventoryBehavior
    status: InventoryAllocationStatus
    planned_quantity: float
    actual_quantity: float | None = None
    source_location_id: uuid.UUID | None = None
    source_location_name: str | None = None
    consumption_ledger_entry_id: uuid.UUID | None = None
    quantity_on_hand: float = 0.0
    quantity_reserved: float = 0.0
    quantity_deployed: float = 0.0
    available_to_promise: float = 0.0
    shortage_quantity: float = 0.0
    reserved_at: datetime
    fulfilled_at: datetime | None = None
    returned_at: datetime | None = None


class InventoryAllocationActual(BaseModel):
    """Actual quantity and stock source confirmed when a job is completed."""

    allocation_id: uuid.UUID
    actual_quantity: float = Field(ge=0, le=1_000_000_000)
    source_location_id: uuid.UUID | None = None


class CompleteJobInventoryRequest(BaseModel):
    """Actual usage for every active allocation on a job."""

    allocations: list[InventoryAllocationActual] = Field(min_length=1, max_length=100)

    @field_validator("allocations")
    @classmethod
    def _unique_allocation_ids(
        cls, values: list[InventoryAllocationActual]
    ) -> list[InventoryAllocationActual]:
        ids = [value.allocation_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("Each allocation can appear only once")
        return values


class JobInventoryPlanResponse(BaseModel):
    """Inventory confirmation state for one workspace-scoped job."""

    job_id: uuid.UUID
    job_status: str
    completion_confirmation_required: bool
    allocations: list[InventoryJobAllocationResponse] = Field(default_factory=list)


class InventoryAvailabilityLine(BaseModel):
    """Sellable stock position for one internal quote requirement."""

    sku: str
    description: str | None = None
    inventory_behavior: InventoryBehavior = "consumable"
    required_quantity: float
    item_id: uuid.UUID | None = None
    item_name: str | None = None
    unit_of_measure: str | None = None
    tracked: bool = False
    is_counted: bool = False
    quantity_on_hand: float = 0.0
    quantity_reserved: float = 0.0
    quantity_deployed: float = 0.0
    available_to_promise: float = 0.0
    shortage_quantity: float = 0.0
    is_available: bool = False


class QuoteInventoryAvailabilityResponse(BaseModel):
    """Private inventory readiness for a quote or proposal preview."""

    connected: bool
    is_available: bool
    items: list[InventoryAvailabilityLine] = Field(default_factory=list)


class JobMaterialsResponse(BaseModel):
    """Consumed COGS plus reusable equipment currently deployed on one job."""

    job_id: uuid.UUID
    items: list[InventoryLedgerEntryResponse]
    deployed_equipment: list[InventoryJobAllocationResponse] = Field(default_factory=list)
    total_material_cost: float = Field(
        0.0, description="Sum of consumption cost, net of returns (0 without billing:read)"
    )


# --------------------------------------------------------------------------- #
# Stock levels
# --------------------------------------------------------------------------- #
class StockLevelRow(BaseModel):
    """On-hand position for one item at one location."""

    item_id: uuid.UUID
    item_name: str
    sku: str | None = None
    unit_of_measure: str
    location_id: uuid.UUID
    location_name: str
    quantity_on_hand: float
    quantity_reserved: float = 0.0
    quantity_deployed: float = 0.0
    available_to_promise: float = 0.0
    total_value: float
    avg_unit_cost: float
    reorder_point: float | None = None
    is_low_stock: bool = False
    last_movement_at: datetime | None = None


class StockLevelListResponse(BaseModel):
    """Every tracked on-hand position, plus the workspace's total value."""

    items: list[StockLevelRow]
    total: int
    total_value: float = Field(0.0, description="Sum of on-hand value (0 without billing:read)")


# --------------------------------------------------------------------------- #
# Reorder
# --------------------------------------------------------------------------- #
class ReorderRow(BaseModel):
    """One item at or below its reorder point, aggregated across locations."""

    item_id: uuid.UUID
    item_name: str
    sku: str | None = None
    unit_of_measure: str
    quantity_on_hand: float
    quantity_reserved: float = 0.0
    quantity_deployed: float = 0.0
    available_to_promise: float = 0.0
    reorder_point: float
    reorder_quantity: float | None = None
    safety_stock: float
    lead_time_days: int | None = None
    supplier_name: str | None = None
    supplier_sku: str | None = None
    # How far below the trigger this item sits (never negative).
    shortfall: float
    # on_hand / average daily usage. None when the item has no usage history —
    # an unreadable gauge, never a full tank.
    days_of_cover: float | None = None
    avg_daily_usage: float | None = None
    suggested_reorder_point: float | None = Field(
        None,
        description="avg daily usage x lead time + safety stock; never applied automatically",
    )


class ReorderReport(BaseModel):
    """Items needing a purchase, most urgent first."""

    items: list[ReorderRow]
    total: int
    generated_at: datetime
    lookback_days: int


class ReorderSuggestion(BaseModel):
    """The computed reorder point for one item, alongside the stored value."""

    item_id: uuid.UUID
    stored_reorder_point: float | None = None
    suggested_reorder_point: float | None = None
    avg_daily_usage: float | None = None
    lead_time_days: int | None = None
    safety_stock: float
    lookback_days: int


# --------------------------------------------------------------------------- #
# COGS
# --------------------------------------------------------------------------- #
class COGSBreakdownRow(BaseModel):
    """One grouped slice of cost of goods sold."""

    key: str | None = Field(None, description="Grouping id (item/job UUID, or category name)")
    label: str
    cogs: float
    quantity: float


class COGSReport(BaseModel):
    """Cost of goods sold over a window, recognized when stock is consumed.

    Valued at the weighted-average cost at posting time (snapshotted on the
    ledger row), so the report never recomputes history. ``shrinkage_cost`` is
    reported separately so waste never hides inside gross margin.
    """

    date_from: date
    date_to: date
    currency: str
    total_cogs: float
    shrinkage_cost: float
    ending_inventory_value: float
    revenue: float | None = Field(None, description="Invoice revenue in the window, when available")
    gross_margin: float | None = Field(
        None, description="(revenue - total_cogs) / revenue, or null when revenue is 0"
    )
    group_by: COGSGroupBy
    breakdown: list[COGSBreakdownRow]
