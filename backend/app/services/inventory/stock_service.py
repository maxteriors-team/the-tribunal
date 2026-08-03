"""The stock posting engine: the only writer of inventory quantity and value.

Every verb (:meth:`receive`, :meth:`consume`, :meth:`adjust`, :meth:`write_off`,
:meth:`transfer`) funnels through one private :meth:`_post`, which does four
things inside the caller's transaction:

1. **Locks the item+location cache row** (``INSERT ... ON CONFLICT DO NOTHING``
   then ``SELECT ... FOR UPDATE``). The lock is the whole reason two crews can
   consume the same bucket at the same moment without one silently overwriting
   the other's weighted average.
2. **Computes the new state** with weighted-average cost. Inbound movements add
   ``qty x unit_cost`` to value and re-derive the average; outbound movements are
   valued at the *server-side* average — a client-supplied cost on an outbound
   move is never read. When on-hand reaches zero the prior average unit cost is
   **kept**, not reset to zero (ERPNext #1473): the next receipt would otherwise
   average against a phantom 0.
3. **Refuses to go negative** unless the workspace opted in via
   ``settings["inventory"]["allow_negative_stock"]``.
4. **Appends an immutable ledger row** carrying the post-state snapshot, and
   updates the cache.

Nothing here commits: routes run on the transactional session, so a failed
reference validation rolls back the whole movement (including a lazily created
location).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.scope import assert_workspace_owned, select_workspace_owned
from app.models.inventory import (
    DEFAULT_VALUATION_METHOD,
    InventoryItem,
    InventoryLedgerEntry,
    InventoryLocation,
    InventoryStockLevel,
)
from app.models.workspace import Workspace
from app.schemas.inventory import (
    AdjustStockRequest,
    InventoryLedgerEntryResponse,
    InventoryLedgerReason,
    ReceiveStockRequest,
    TransferStockRequest,
)
from app.services.exceptions import ConflictError, ValidationError
from app.services.inventory.locations import resolve_location

logger = structlog.get_logger()

# Quantities carry 4 decimals (Numeric(14,4)), money 2 (Numeric(14,2)), and unit
# costs 4 (Numeric(12,4)) — matching the columns so nothing is silently rounded
# by the driver on the way in.
QUANTITY_PLACES = Decimal("0.0001")
MONEY_PLACES = Decimal("0.01")
COST_PLACES = Decimal("0.0001")

# Reasons whose sign is fixed by the verb that posts them.
_INBOUND_REASONS = frozenset({"receipt", "return_to_stock", "transfer_in", "opening_balance"})
_OUTBOUND_REASONS = frozenset({"job_usage", "sale", "shrinkage", "transfer_out"})


def _quantize(value: Decimal | float | int | None, places: Decimal) -> Decimal:
    """Round a value to a column's scale, half-up (money convention)."""
    if value is None:
        return Decimal("0").quantize(places)
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(places, rounding=ROUND_HALF_UP)


class StockService:
    """Posts stock movements and keeps the derived on-hand cache correct."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="stock_service")
        # Per-request memo so a multi-row post does not requery the workspace.
        self._negative_allowed: dict[uuid.UUID, bool] = {}

    # ------------------------------------------------------------------ #
    # Reference validation (tenant-safe)
    # ------------------------------------------------------------------ #
    async def _assert_item(self, item_id: uuid.UUID, workspace_id: uuid.UUID) -> InventoryItem:
        item = await assert_workspace_owned(
            self.db,
            InventoryItem,
            item_id,
            workspace_id,
            detail="Inventory item not found",
        )
        if item.valuation_method != DEFAULT_VALUATION_METHOD:
            # The column exists so FIFO layers can be added without a data
            # migration; posting against an unimplemented method would silently
            # value stock wrong, so refuse instead.
            raise ValidationError(
                f"Valuation method {item.valuation_method!r} is not implemented; "
                f"only {DEFAULT_VALUATION_METHOD!r} can be posted."
            )
        return item

    async def _allows_negative(self, workspace_id: uuid.UUID) -> bool:
        """Whether this workspace lets stock go below zero."""
        cached = self._negative_allowed.get(workspace_id)
        if cached is not None:
            return cached

        settings = (
            await self.db.execute(select(Workspace.settings).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        inventory_settings = (settings or {}).get("inventory")
        allowed = bool(
            isinstance(inventory_settings, dict)
            and inventory_settings.get("allow_negative_stock", False)
        )
        self._negative_allowed[workspace_id] = allowed
        return allowed

    # ------------------------------------------------------------------ #
    # The posting engine
    # ------------------------------------------------------------------ #
    async def _lock_level(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
    ) -> InventoryStockLevel:
        """Return the item+location cache row, locked for update.

        Inserts the row first when missing (``ON CONFLICT DO NOTHING``, so two
        concurrent first movements do not both fail), then takes the row lock
        that serializes the read-modify-write of the weighted average.
        """
        await self.db.execute(
            pg_insert(InventoryStockLevel)
            .values(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                item_id=item_id,
                location_id=location_id,
                quantity_on_hand=Decimal("0"),
                total_value=Decimal("0"),
                avg_unit_cost=Decimal("0"),
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(
                index_elements=["workspace_id", "item_id", "location_id"],
            )
        )
        level = (
            await self.db.execute(
                select(InventoryStockLevel)
                .where(
                    InventoryStockLevel.workspace_id == workspace_id,
                    InventoryStockLevel.item_id == item_id,
                    InventoryStockLevel.location_id == location_id,
                )
                .with_for_update()
            )
        ).scalar_one()
        return level

    async def _post(
        self,
        *,
        workspace_id: uuid.UUID,
        item: InventoryItem,
        location: InventoryLocation,
        quantity_delta: Decimal,
        reason: str,
        unit_cost: Decimal | None = None,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        occurred_at: datetime | None = None,
        note: str | None = None,
        created_by_id: int | None = None,
    ) -> InventoryLedgerEntry:
        """Append one movement and roll the cache forward. Never commits."""
        delta = _quantize(quantity_delta, QUANTITY_PLACES)
        if delta == 0:
            raise ValidationError("A stock movement must change the quantity")
        if delta > 0 and reason in _OUTBOUND_REASONS:
            raise ValidationError(f"Reason {reason!r} cannot post a positive quantity")
        if delta < 0 and reason in _INBOUND_REASONS:
            raise ValidationError(f"Reason {reason!r} cannot post a negative quantity")

        level = await self._lock_level(workspace_id, item.id, location.id)
        prior_qty = _quantize(level.quantity_on_hand, QUANTITY_PLACES)
        prior_value = _quantize(level.total_value, MONEY_PLACES)
        prior_cost = _quantize(level.avg_unit_cost, COST_PLACES)

        new_qty = _quantize(prior_qty + delta, QUANTITY_PLACES)

        if delta > 0:
            # Inbound: value in at the stated cost, then re-derive the average.
            posted_cost = _quantize(unit_cost, COST_PLACES)
            if posted_cost < 0:
                raise ValidationError("unit_cost cannot be negative")
            value_delta = _quantize(delta * posted_cost, MONEY_PLACES)
            new_value = _quantize(prior_value + value_delta, MONEY_PLACES)
            if new_qty > 0:
                new_cost = _quantize(new_value / new_qty, COST_PLACES)
            else:
                # Divide-by-zero guard: keep a real cost rather than resetting to
                # 0, so a later receipt does not average against a phantom zero.
                new_cost = prior_cost if prior_cost > 0 else posted_cost
        else:
            # Outbound: valued at the server-side average, full stop.
            if new_qty < 0 and not await self._allows_negative(workspace_id):
                raise ConflictError(
                    f"Only {prior_qty.normalize()} {item.unit_of_measure} of {item.name} "
                    f"on hand at {location.name}; cannot remove {(-delta).normalize()}.",
                    code="insufficient_stock",
                )
            if new_qty == 0:
                # The move that empties a bin carries out whatever value is left
                # in it, so ``SUM(value_delta) == total_value`` stays exact and
                # per-unit rounding dust cannot accumulate as phantom value.
                value_delta = -prior_value
                posted_cost = _quantize(prior_value / -delta, COST_PLACES)
                new_value = Decimal("0.00")
            else:
                posted_cost = prior_cost
                value_delta = _quantize(delta * posted_cost, MONEY_PLACES)
                new_value = _quantize(prior_value + value_delta, MONEY_PLACES)
            # Keep the average across the emptying: the next receipt should not
            # average against a phantom 0 (ERPNext #1473).
            new_cost = prior_cost

        moment = occurred_at or datetime.now(UTC)
        entry = InventoryLedgerEntry(
            workspace_id=workspace_id,
            item_id=item.id,
            location_id=location.id,
            quantity_delta=delta,
            unit_cost=posted_cost,
            value_delta=value_delta,
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            occurred_at=moment,
            note=note,
            quantity_after=new_qty,
            value_after=new_value,
            unit_cost_after=new_cost,
            created_by_id=created_by_id,
        )
        self.db.add(entry)

        level.quantity_on_hand = new_qty
        level.total_value = new_value
        level.avg_unit_cost = new_cost
        level.last_movement_at = moment

        await self.db.flush()
        await self.db.refresh(entry)
        self.log.info(
            "stock_posted",
            workspace_id=str(workspace_id),
            item_id=str(item.id),
            location_id=str(location.id),
            reason=reason,
            quantity_delta=str(delta),
            quantity_after=str(new_qty),
        )
        return entry

    # ------------------------------------------------------------------ #
    # Response building
    # ------------------------------------------------------------------ #
    @staticmethod
    def entry_response(
        entry: InventoryLedgerEntry,
        *,
        item_name: str | None = None,
        location_name: str | None = None,
        include_costs: bool = True,
    ) -> InventoryLedgerEntryResponse:
        """Serialize a movement, redacting money unless the caller may see it."""
        zero = 0.0
        return InventoryLedgerEntryResponse(
            id=entry.id,
            item_id=entry.item_id,
            item_name=item_name,
            location_id=entry.location_id,
            location_name=location_name,
            quantity_delta=float(entry.quantity_delta or 0),
            unit_cost=float(entry.unit_cost or 0) if include_costs else zero,
            value_delta=float(entry.value_delta or 0) if include_costs else zero,
            reason=cast(InventoryLedgerReason, entry.reason),
            reference_type=entry.reference_type,
            reference_id=entry.reference_id,
            occurred_at=entry.occurred_at,
            note=entry.note,
            quantity_after=float(entry.quantity_after or 0),
            value_after=float(entry.value_after or 0) if include_costs else zero,
            unit_cost_after=float(entry.unit_cost_after or 0) if include_costs else zero,
            created_at=entry.created_at,
        )

    # ------------------------------------------------------------------ #
    # Public verbs
    # ------------------------------------------------------------------ #
    async def receive(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: ReceiveStockRequest,
        *,
        created_by_id: int | None = None,
    ) -> InventoryLedgerEntry:
        """Bring stock in at a known unit cost (the only movement that sets one)."""
        item = await self._assert_item(item_id, workspace_id)
        location = await resolve_location(self.db, workspace_id, payload.location_id)
        return await self._post(
            workspace_id=workspace_id,
            item=item,
            location=location,
            quantity_delta=Decimal(str(payload.quantity)),
            reason="receipt",
            unit_cost=Decimal(str(payload.unit_cost)),
            reference_type=payload.reference_type,
            reference_id=payload.reference_id,
            occurred_at=payload.occurred_at,
            note=payload.note,
            created_by_id=created_by_id,
        )

    async def consume(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        quantity: float,
        *,
        location_id: uuid.UUID | None = None,
        reason: str = "job_usage",
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        note: str | None = None,
        created_by_id: int | None = None,
    ) -> InventoryLedgerEntry:
        """Take stock out for a job or a sale, valued at the current average."""
        if reason not in {"job_usage", "sale"}:
            raise ValidationError(f"{reason!r} is not a consumption reason")
        if quantity <= 0:
            raise ValidationError("Consumed quantity must be positive")
        item = await self._assert_item(item_id, workspace_id)
        location = await resolve_location(self.db, workspace_id, location_id)
        return await self._post(
            workspace_id=workspace_id,
            item=item,
            location=location,
            quantity_delta=-Decimal(str(quantity)),
            reason=reason,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            created_by_id=created_by_id,
        )

    async def return_to_stock(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        quantity: float,
        *,
        unit_cost: float,
        location_id: uuid.UUID | None = None,
        reference_type: str | None = None,
        reference_id: uuid.UUID | None = None,
        note: str | None = None,
        created_by_id: int | None = None,
    ) -> InventoryLedgerEntry:
        """Put consumed stock back, at the cost it left with.

        The compensating entry for "that material never got used". Returning at
        the *original* cost (not today's average) is what keeps the job's
        material cost net to zero after an undo.
        """
        if quantity <= 0:
            raise ValidationError("Returned quantity must be positive")
        item = await self._assert_item(item_id, workspace_id)
        location = await resolve_location(self.db, workspace_id, location_id)
        return await self._post(
            workspace_id=workspace_id,
            item=item,
            location=location,
            quantity_delta=Decimal(str(quantity)),
            reason="return_to_stock",
            unit_cost=Decimal(str(unit_cost)),
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            created_by_id=created_by_id,
        )

    async def adjust(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: AdjustStockRequest,
        *,
        created_by_id: int | None = None,
    ) -> InventoryLedgerEntry:
        """Reconcile to a counted quantity, or write off shrinkage.

        A physical count is an *absolute* number; the engine posts the signed
        difference so the ledger still explains how the bin got there.
        """
        counted = payload.quantity_on_hand
        write_off = payload.write_off_quantity
        if (counted is None) == (write_off is None):
            raise ValidationError(
                "Supply exactly one of quantity_on_hand (a physical count) or "
                "write_off_quantity (shrinkage)"
            )

        item = await self._assert_item(item_id, workspace_id)
        location = await resolve_location(self.db, workspace_id, payload.location_id)

        if write_off is not None:
            return await self.write_off(
                workspace_id,
                item_id,
                write_off,
                location_id=location.id,
                occurred_at=payload.occurred_at,
                note=payload.note,
                created_by_id=created_by_id,
            )

        level = await self._lock_level(workspace_id, item.id, location.id)
        prior_qty = _quantize(level.quantity_on_hand, QUANTITY_PLACES)
        target = _quantize(counted, QUANTITY_PLACES)
        delta = _quantize(target - prior_qty, QUANTITY_PLACES)
        if delta == 0:
            raise ConflictError(
                f"{item.name} is already counted at {target.normalize()} "
                f"{item.unit_of_measure} at {location.name}",
                code="no_stock_change",
            )
        # An upward correction is valued at the bin's existing average: a count
        # discovers units, it does not tell us what they cost.
        return await self._post(
            workspace_id=workspace_id,
            item=item,
            location=location,
            quantity_delta=delta,
            reason="adjustment",
            unit_cost=_quantize(level.avg_unit_cost, COST_PLACES),
            reference_type="manual",
            occurred_at=payload.occurred_at,
            note=payload.note,
            created_by_id=created_by_id,
        )

    async def write_off(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        quantity: float,
        *,
        location_id: uuid.UUID | None = None,
        occurred_at: datetime | None = None,
        note: str | None = None,
        created_by_id: int | None = None,
    ) -> InventoryLedgerEntry:
        """Remove stock as waste. Reported apart from COGS, never inside it."""
        if quantity <= 0:
            raise ValidationError("Written-off quantity must be positive")
        item = await self._assert_item(item_id, workspace_id)
        location = await resolve_location(self.db, workspace_id, location_id)
        return await self._post(
            workspace_id=workspace_id,
            item=item,
            location=location,
            quantity_delta=-Decimal(str(quantity)),
            reason="shrinkage",
            reference_type="manual",
            occurred_at=occurred_at,
            note=note,
            created_by_id=created_by_id,
        )

    async def transfer(
        self,
        workspace_id: uuid.UUID,
        payload: TransferStockRequest,
        *,
        created_by_id: int | None = None,
    ) -> tuple[InventoryLedgerEntry, InventoryLedgerEntry]:
        """Move stock between locations at the source's average cost.

        Two rows in one transaction: ``transfer_out`` at the source's weighted
        average, then ``transfer_in`` at that *same* cost. Value moves with the
        goods, so a transfer never changes the workspace's inventory value.
        """
        if payload.from_location_id == payload.to_location_id:
            raise ValidationError("Source and destination locations must differ")

        item = await self._assert_item(payload.item_id, workspace_id)
        source = await resolve_location(self.db, workspace_id, payload.from_location_id)
        destination = await resolve_location(self.db, workspace_id, payload.to_location_id)

        out_entry = await self._post(
            workspace_id=workspace_id,
            item=item,
            location=source,
            quantity_delta=-Decimal(str(payload.quantity)),
            reason="transfer_out",
            reference_type="transfer",
            occurred_at=payload.occurred_at,
            note=payload.note,
            created_by_id=created_by_id,
        )
        in_entry = await self._post(
            workspace_id=workspace_id,
            item=item,
            location=destination,
            quantity_delta=Decimal(str(payload.quantity)),
            reason="transfer_in",
            unit_cost=_quantize(out_entry.unit_cost, COST_PLACES),
            reference_type="transfer",
            reference_id=out_entry.id,
            occurred_at=payload.occurred_at,
            note=payload.note,
            created_by_id=created_by_id,
        )
        return out_entry, in_entry

    # ------------------------------------------------------------------ #
    # Drift detection
    # ------------------------------------------------------------------ #
    async def replay_level(
        self,
        workspace_id: uuid.UUID,
        item_id: uuid.UUID,
        location_id: uuid.UUID,
    ) -> tuple[Decimal, Decimal]:
        """Recompute (quantity, value) for one bin straight from the ledger.

        The cache is derived state; this is the audit that proves it still
        matches its source. Used by tests and available for a support query when
        a number looks wrong in production.
        """
        rows = (
            (
                await self.db.execute(
                    select_workspace_owned(
                        InventoryLedgerEntry,
                        workspace_id,
                        InventoryLedgerEntry.item_id == item_id,
                        InventoryLedgerEntry.location_id == location_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        quantity = sum((_quantize(row.quantity_delta, QUANTITY_PLACES) for row in rows), Decimal(0))
        value = sum((_quantize(row.value_delta, MONEY_PLACES) for row in rows), Decimal(0))
        return _quantize(quantity, QUANTITY_PLACES), _quantize(value, MONEY_PLACES)
