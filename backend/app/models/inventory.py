"""Inventory tracking models: locations, items, an append-only ledger, and a cache.

The shape follows the dual-layer model every mature inventory system converges
on (ERPNext's ``Stock Ledger Entry`` + ``Bin``, Odoo's ``stock.move`` +
``stock.quant``):

- :class:`InventoryLedgerEntry` is the **truth**: one immutable row per physical
  movement, signed, with the resulting on-hand/value/cost snapshotted onto the
  row. It is never updated or deleted — a correction is a *new* entry.
- :class:`InventoryStockLevel` is a **derived cache** of "how much of item X is
  at location Y", rebuildable from the ledger at any time. Every "what's on
  hand" read hits this; every audit hits the ledger.

Valuation is weighted-average cost (WAC), computed forward-only: ``occurred_at``
is metadata, never a trigger to restate history. That deliberately trades
"perfectly restated costs after a backdated receipt" (ERPNext's repost engine)
for "no background reposting job and no mutating of settled costs".
``InventoryItem.valuation_method`` is a column so FIFO layers can be added later
without a data migration; only ``weighted_average`` is implemented today.

Money is stored in major units via ``Numeric`` to match :mod:`app.models.invoice`
and :mod:`app.models.job_costing`.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.tenancy import WorkspaceScoped

if TYPE_CHECKING:
    from app.models.catalog import CatalogItem
    from app.models.field_service import Crew, Job
    from app.models.user import User
    from app.models.workspace import Workspace


# Where stock physically sits. A ``truck`` is a crew's rolling stock; ``other``
# covers a job-site staging pile or a customer-supplied cache.
INVENTORY_LOCATION_KINDS = ("warehouse", "truck", "other")

# Why a movement happened. Kept as a DB enum (not free text) because the COGS
# report partitions on it: ``job_usage``/``sale`` are cost of goods sold,
# ``shrinkage`` is waste reported separately, and the rest are neutral moves.
INVENTORY_LEDGER_REASONS = (
    "receipt",
    "job_usage",
    "sale",
    "adjustment",
    "shrinkage",
    "return_to_stock",
    "transfer_in",
    "transfer_out",
    "opening_balance",
)
INVENTORY_LEDGER_REASON_ENUM = "inventory_ledger_reason"

# What a movement was posted against, when it was posted against anything.
INVENTORY_REFERENCE_TYPES = ("job", "invoice", "quote", "manual", "transfer")

INVENTORY_ALLOCATION_BEHAVIORS = ("consumable", "reusable")
INVENTORY_ALLOCATION_STATUSES = ("reserved", "consumed", "deployed", "released", "returned")

# The only valuation method the posting engine implements today.
DEFAULT_VALUATION_METHOD = "weighted_average"
INVENTORY_VALUATION_METHODS = ("weighted_average",)


class InventoryLocation(Base, WorkspaceScoped):
    """A place stock sits: a warehouse, a crew truck, or anywhere else."""

    __tablename__ = "inventory_locations"
    __table_args__ = (
        # Case-insensitive uniqueness: "Main" and "main" are the same shelf.
        Index(
            "uq_inventory_locations_workspace_name",
            "workspace_id",
            text("lower(name)"),
            unique=True,
        ),
        Index("ix_inventory_locations_workspace_active", "workspace_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(
        Enum(*INVENTORY_LOCATION_KINDS, name="inventory_location_kind"),
        nullable=False,
        default="warehouse",
    )
    # Optional owning crew for a truck. SET NULL so retiring a crew never orphans
    # the stock sitting in its van.
    crew_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("crews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The location the posting engine falls back to when a caller names none.
    # Lazily created ("Main") on the first movement so nobody has to configure
    # locations before receiving stock.
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    crew: Mapped["Crew | None"] = relationship("Crew")

    def __repr__(self) -> str:
        return f"<InventoryLocation(id={self.id}, name={self.name}, kind={self.kind})>"


class InventoryItem(Base, WorkspaceScoped):
    """A tracked SKU: the thing whose quantity and cost the ledger moves.

    Deliberately a separate table from :class:`app.models.catalog.CatalogItem`
    rather than columns on it. ``CatalogService.delete_item`` hard-deletes price
    book templates on the documented promise that documents snapshot their
    values — stock history must survive that, so the link is a nullable FK with
    ``ON DELETE SET NULL``.
    """

    __tablename__ = "inventory_items"
    __table_args__ = (
        Index("ix_inventory_items_workspace_active", "workspace_id", "is_active"),
        # One inventory item per catalog item, but plenty of items with no
        # catalog link at all (consumables nobody sells a line of).
        Index(
            "uq_inventory_items_workspace_catalog_item",
            "workspace_id",
            "catalog_item_id",
            unique=True,
            postgresql_where=text("catalog_item_id IS NOT NULL"),
        ),
        # SKUs are unique when present; messy imports may leave them null.
        Index(
            "uq_inventory_items_workspace_sku",
            "workspace_id",
            "sku",
            unique=True,
            postgresql_where=text("sku IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    catalog_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # "each", "gallon", "box", "ft" — a label the UI renders, not a unit the
    # backend converts between. No unit maths, so no conversion table.
    unit_of_measure: Mapped[str] = mapped_column(
        String(30), nullable=False, default="each", server_default="each"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Per-item so FIFO can land later without a migration. Writes reject
    # anything the posting engine does not implement.
    valuation_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=DEFAULT_VALUATION_METHOD,
        server_default=DEFAULT_VALUATION_METHOD,
    )

    # NULL reorder_point means "not managed": the item never raises a low-stock
    # alert. The reorder service *suggests* a value but never silently writes it.
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    reorder_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    safety_stock: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=0, server_default="0"
    )
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Enough supplier detail to tell an operator who to call. No supplier
    # entities and no purchase orders in v1.
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    catalog_item: Mapped["CatalogItem | None"] = relationship("CatalogItem")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return f"<InventoryItem(id={self.id}, name={self.name}, sku={self.sku})>"


class InventoryLedgerEntry(Base, WorkspaceScoped):
    """One immutable stock movement.

    Append-only: rows are never updated or deleted. Undoing a consumption posts
    a compensating ``return_to_stock`` row instead, so the audit trail keeps
    both the mistake and the correction.

    The ``*_after`` columns snapshot the post-state of the item+location cache
    at posting time. That makes the COGS report a cheap scan (no replay), keeps
    historical unit costs correct even after later receipts move the average,
    and makes cache drift detectable (recomputed vs. stored).
    """

    __tablename__ = "inventory_ledger_entries"
    __table_args__ = (
        Index("ix_inventory_ledger_workspace_item", "workspace_id", "item_id", "created_at"),
        # COGS scans a window partitioned by reason.
        Index("ix_inventory_ledger_workspace_reason", "workspace_id", "reason", "created_at"),
        # Job material roll-ups and the compensating-entry lookup.
        Index(
            "ix_inventory_ledger_workspace_reference",
            "workspace_id",
            "reference_type",
            "reference_id",
        ),
        # Idempotency guard: one job_usage row per (job, item) per posting. A
        # retried request lands on the conflict rather than double-consuming.
        Index(
            "uq_inventory_ledger_job_usage",
            "workspace_id",
            "reason",
            "reference_type",
            "reference_id",
            "item_id",
            unique=True,
            postgresql_where=text("reference_id IS NOT NULL AND reason = 'job_usage'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # RESTRICT, not CASCADE: deleting a location that still has history would
    # silently destroy the only record of where stock went.
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Signed: positive is inbound, negative is outbound.
    quantity_delta: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # Cost per unit for this movement (major units). On outbound this is the
    # server-side weighted average, never a client-supplied number.
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    # Signed value change: quantity_delta * unit_cost, rounded to cents.
    value_delta: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    reason: Mapped[str] = mapped_column(
        Enum(*INVENTORY_LEDGER_REASONS, name=INVENTORY_LEDGER_REASON_ENUM, create_type=False),
        nullable=False,
    )
    reference_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # When the movement happened in the real world. Metadata only: the engine
    # posts forward, so a backdated value never restates later rows.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Post-state snapshot of the item+location cache after this row landed.
    quantity_after: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    value_after: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    unit_cost_after: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)

    created_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    item: Mapped["InventoryItem"] = relationship("InventoryItem")
    location: Mapped["InventoryLocation"] = relationship("InventoryLocation")
    created_by: Mapped["User | None"] = relationship("User", foreign_keys=[created_by_id])

    def __repr__(self) -> str:
        return (
            f"<InventoryLedgerEntry(id={self.id}, item_id={self.item_id}, "
            f"reason={self.reason}, quantity_delta={self.quantity_delta})>"
        )


class InventoryJobAllocation(Base, WorkspaceScoped):
    """Reserved or fulfilled inventory attached to one field-service job."""

    __tablename__ = "inventory_job_allocations"
    __table_args__ = (
        UniqueConstraint("job_id", "item_id", name="uq_inventory_job_allocations_job_item"),
        CheckConstraint(
            "planned_quantity > 0",
            name="ck_inventory_job_allocations_planned_positive",
        ),
        CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="ck_inventory_job_allocations_actual_nonnegative",
        ),
        CheckConstraint(
            "behavior IN ('consumable', 'reusable')",
            name="ck_inventory_job_allocations_behavior",
        ),
        CheckConstraint(
            "status IN ('reserved', 'consumed', 'deployed', 'released', 'returned')",
            name="ck_inventory_job_allocations_status",
        ),
        Index(
            "ix_inventory_job_allocations_workspace_status",
            "workspace_id",
            "status",
        ),
        Index(
            "ix_inventory_job_allocations_workspace_item_status",
            "workspace_id",
            "item_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("field_service_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    consumption_ledger_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_ledger_entries.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )

    behavior: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="reserved", server_default="reserved"
    )
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    actual_quantity: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
    fulfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    job: Mapped["Job"] = relationship("Job")
    item: Mapped["InventoryItem"] = relationship("InventoryItem")
    source_location: Mapped["InventoryLocation | None"] = relationship(
        "InventoryLocation", foreign_keys=[source_location_id]
    )
    consumption_ledger_entry: Mapped["InventoryLedgerEntry | None"] = relationship(
        "InventoryLedgerEntry", foreign_keys=[consumption_ledger_entry_id]
    )


class InventoryStockLevel(Base, WorkspaceScoped):
    """Derived on-hand cache for one item at one location (the Bin/quant).

    Never written by anything except the posting engine, and always rebuildable
    by replaying :class:`InventoryLedgerEntry` for the same item+location.
    """

    __tablename__ = "inventory_stock_levels"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "item_id",
            "location_id",
            name="uq_inventory_stock_levels_item_location",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inventory_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    quantity_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(14, 4), nullable=False, default=0, server_default="0"
    )
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
    avg_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=0, server_default="0"
    )

    last_movement_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    workspace: Mapped["Workspace"] = relationship("Workspace")
    item: Mapped["InventoryItem"] = relationship("InventoryItem")
    location: Mapped["InventoryLocation"] = relationship("InventoryLocation")

    def __repr__(self) -> str:
        return (
            f"<InventoryStockLevel(item_id={self.item_id}, location_id={self.location_id}, "
            f"quantity_on_hand={self.quantity_on_hand})>"
        )
