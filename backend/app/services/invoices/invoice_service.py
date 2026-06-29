"""Invoice business logic.

Mirrors :class:`app.services.opportunities.opportunity_service.OpportunityService`
conventions (``get_or_404``/``get_nested_or_404`` lookups, ``paginate`` for lists,
``selectinload`` + explicit ``refresh`` so async serialization never triggers a
lazy load). Money math follows the repo's ``float`` convention, rounded to two
decimals to avoid binary-float dust.

``status`` is **derived** from ``amount_paid`` + ``due_date`` + ``sent_at`` rather
than free-set by clients. ``record_payment`` is the idempotent reconciliation
primitive the Stripe webhook will call (phase 4); it lives here so the domain rule
has one home and is testable without Stripe configured.
"""

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.db.pagination import paginate
from app.models.invoice import Invoice, InvoiceLineItem
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDetailResponse,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoiceResponse,
    InvoiceUpdate,
    PaginatedInvoices,
)
from app.services.exceptions import ConflictError

logger = structlog.get_logger()

# Statuses that mean the invoice has been issued to the customer; line-item edits
# and hard deletes are blocked once an invoice reaches any of these.
_ISSUED_STATUSES = frozenset({"sent", "paid", "partial", "overdue"})


class InvoiceService:
    """Service for customer-invoice CRUD, lifecycle, and payment reconciliation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="invoice_service")

    # ------------------------------------------------------------------
    # Derivation helpers (pure; no I/O)
    # ------------------------------------------------------------------

    @staticmethod
    def derive_status(invoice: Invoice) -> str:
        """Return the lifecycle status implied by amounts, due date, and send state.

        ``void`` is terminal and never overridden. Otherwise: fully paid -> ``paid``;
        some payment -> ``partial``; unpaid and past due after sending -> ``overdue``;
        sent but not due -> ``sent``; never sent -> ``draft``.
        """
        if invoice.status == "void":
            return "void"

        total = float(invoice.total or 0)
        paid = float(invoice.amount_paid or 0)

        if total > 0 and paid >= total:
            return "paid"
        if paid > 0:
            return "partial"

        is_sent = invoice.sent_at is not None
        if is_sent and invoice.due_date is not None and invoice.due_date < date.today():
            return "overdue"
        return "sent" if is_sent else "draft"

    def _recompute_totals(self, invoice: Invoice) -> None:
        """Recompute subtotal/total from line items and re-derive status in place.

        Requires ``invoice.line_items`` to be loaded.
        """
        subtotal = round(sum(float(li.total) for li in invoice.line_items), 2)
        invoice.subtotal = subtotal
        invoice.total = round(
            subtotal + float(invoice.tax_amount or 0) - float(invoice.discount_amount or 0), 2
        )
        invoice.status = self.derive_status(invoice)

    @staticmethod
    def _line_total(quantity: float, unit_price: float, discount: float) -> float:
        return round(quantity * unit_price - discount, 2)

    async def _next_invoice_number(self, workspace_id: uuid.UUID) -> str:
        """Allocate the next ``INV-000001`` number for a workspace.

        Uses ``max(existing suffix) + 1`` so numbers stay monotonic even after a
        draft is deleted. Concurrent creates rely on the
        ``uq_invoices_workspace_number`` constraint as the final guard.
        """
        result = await self.db.execute(
            select(Invoice.number).where(Invoice.workspace_id == workspace_id)
        )
        max_seq = 0
        for number in result.scalars().all():
            try:
                max_seq = max(max_seq, int(number.rsplit("-", 1)[-1]))
            except (ValueError, IndexError):
                continue
        return f"INV-{max_seq + 1:06d}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_invoices(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        contact_id: int | None = None,
    ) -> PaginatedInvoices:
        """List a workspace's invoices, newest first, with optional filters."""
        query = select(Invoice).where(Invoice.workspace_id == workspace_id)
        if status:
            query = query.where(Invoice.status == status)
        if contact_id is not None:
            query = query.where(Invoice.contact_id == contact_id)
        query = query.order_by(Invoice.created_at.desc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=InvoiceResponse,
            response_builder=PaginatedInvoices,
        )

    async def create_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_in: InvoiceCreate,
        *,
        created_by_id: int | None = None,
    ) -> InvoiceDetailResponse:
        """Create a draft invoice with its initial line items and computed totals."""
        invoice = Invoice(
            workspace_id=workspace_id,
            contact_id=invoice_in.contact_id,
            opportunity_id=invoice_in.opportunity_id,
            number=await self._next_invoice_number(workspace_id),
            currency=invoice_in.currency,
            tax_amount=invoice_in.tax_amount,
            discount_amount=invoice_in.discount_amount,
            issue_date=invoice_in.issue_date,
            due_date=invoice_in.due_date,
            notes=invoice_in.notes,
            terms=invoice_in.terms,
            amount_paid=0,
            status="draft",
            created_by_id=created_by_id,
        )
        for item in invoice_in.line_items:
            invoice.line_items.append(
                InvoiceLineItem(
                    name=item.name,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount=item.discount,
                    total=self._line_total(item.quantity, item.unit_price, item.discount),
                )
            )

        self._recompute_totals(invoice)
        self.db.add(invoice)
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])

        self.log.info(
            "invoice_created",
            invoice_id=str(invoice.id),
            workspace_id=str(workspace_id),
            number=invoice.number,
            total=float(invoice.total),
        )
        return InvoiceDetailResponse.model_validate(invoice)

    async def get_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> InvoiceDetailResponse:
        """Fetch a single invoice with its line items."""
        invoice = await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[selectinload(Invoice.line_items)],
        )
        return InvoiceDetailResponse.model_validate(invoice)

    async def update_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        invoice_in: InvoiceUpdate,
    ) -> InvoiceDetailResponse:
        """Update invoice header fields. Totals/status are re-derived, not set."""
        invoice = await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[selectinload(Invoice.line_items)],
        )
        if invoice.status == "void":
            raise ConflictError("Cannot edit a voided invoice")

        for field in (
            "contact_id",
            "opportunity_id",
            "currency",
            "tax_amount",
            "discount_amount",
            "issue_date",
            "due_date",
            "notes",
            "terms",
        ):
            value = getattr(invoice_in, field)
            if value is not None:
                setattr(invoice, field, value)

        # tax/discount changes move the total, which can change paid/partial state.
        self._recompute_totals(invoice)
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])
        return InvoiceDetailResponse.model_validate(invoice)

    async def delete_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> None:
        """Delete a draft invoice. Issued invoices must be voided instead."""
        invoice = await get_or_404(self.db, Invoice, invoice_id, workspace_id=workspace_id)
        if invoice.status in _ISSUED_STATUSES:
            raise ConflictError("Cannot delete an issued invoice; void it instead")
        await self.db.delete(invoice)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    async def mark_sent(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> InvoiceDetailResponse:
        """Mark an invoice as sent (sets ``sent_at`` once) and re-derive status."""
        invoice = await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[selectinload(Invoice.line_items)],
        )
        if invoice.status == "void":
            raise ConflictError("Cannot send a voided invoice")
        if invoice.sent_at is None:
            invoice.sent_at = datetime.now(UTC)
        invoice.status = self.derive_status(invoice)
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])
        return InvoiceDetailResponse.model_validate(invoice)

    async def void_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> InvoiceDetailResponse:
        """Void an invoice. Fully paid invoices cannot be voided."""
        invoice = await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[selectinload(Invoice.line_items)],
        )
        if invoice.status == "paid":
            raise ConflictError("Cannot void a fully paid invoice")
        invoice.status = "void"
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])
        return InvoiceDetailResponse.model_validate(invoice)

    async def record_payment(
        self,
        invoice: Invoice,
        amount: float,
        *,
        payment_intent_id: str | None = None,
    ) -> bool:
        """Apply a payment to an invoice (idempotent on ``payment_intent_id``).

        Returns ``True`` when this call recorded the payment, ``False`` on a replay
        of the most-recently-applied Stripe payment intent (so the webhook can
        avoid duplicate side effects on retries). Idempotency is keyed on the
        intent id alone, not on paid state, so replays of a *partial* payment are
        no-ops too. Distinguishing an older interleaved intent would need a full
        per-payment ledger (deferred); Stripe retries the same event, which this
        covers. ``invoice.line_items`` need not be loaded.
        """
        already_applied = (
            payment_intent_id is not None and invoice.stripe_payment_intent_id == payment_intent_id
        )
        if already_applied:
            return False

        invoice.amount_paid = round(float(invoice.amount_paid or 0) + float(amount), 2)
        if payment_intent_id:
            invoice.stripe_payment_intent_id = payment_intent_id
        invoice.status = self.derive_status(invoice)
        if invoice.status == "paid":
            invoice.paid_at = datetime.now(UTC)
        await self.db.commit()

        self.log.info(
            "invoice_payment_recorded",
            invoice_id=str(invoice.id),
            amount=float(amount),
            amount_paid=float(invoice.amount_paid),
            status=invoice.status,
        )
        return True

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    async def add_line_item(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        item_in: InvoiceLineItemCreate,
    ) -> InvoiceDetailResponse:
        """Add a line item and recompute invoice totals."""
        invoice = await self._get_mutable_invoice(workspace_id, invoice_id)
        invoice.line_items.append(
            InvoiceLineItem(
                name=item_in.name,
                description=item_in.description,
                quantity=item_in.quantity,
                unit_price=item_in.unit_price,
                discount=item_in.discount,
                total=self._line_total(item_in.quantity, item_in.unit_price, item_in.discount),
            )
        )
        self._recompute_totals(invoice)
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])
        return InvoiceDetailResponse.model_validate(invoice)

    async def update_line_item(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        item_id: uuid.UUID,
        item_in: InvoiceLineItemUpdate,
    ) -> InvoiceDetailResponse:
        """Update a line item, recompute its total and the invoice totals."""
        invoice = await self._get_mutable_invoice(workspace_id, invoice_id)
        line_item = await get_nested_or_404(
            self.db,
            InvoiceLineItem,
            item_id,
            parent_field="invoice_id",
            parent_id=invoice_id,
            detail="Line item not found",
        )

        if item_in.name is not None:
            line_item.name = item_in.name
        if item_in.description is not None:
            line_item.description = item_in.description
        if item_in.quantity is not None:
            line_item.quantity = item_in.quantity
        if item_in.unit_price is not None:
            line_item.unit_price = item_in.unit_price
        if item_in.discount is not None:
            line_item.discount = item_in.discount
        line_item.total = self._line_total(
            float(line_item.quantity), float(line_item.unit_price), float(line_item.discount)
        )

        self._recompute_totals(invoice)
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])
        return InvoiceDetailResponse.model_validate(invoice)

    async def remove_line_item(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> InvoiceDetailResponse:
        """Remove a line item and recompute invoice totals."""
        invoice = await self._get_mutable_invoice(workspace_id, invoice_id)
        line_item = await get_nested_or_404(
            self.db,
            InvoiceLineItem,
            item_id,
            parent_field="invoice_id",
            parent_id=invoice_id,
            detail="Line item not found",
        )
        invoice.line_items.remove(line_item)
        await self.db.delete(line_item)
        self._recompute_totals(invoice)
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])
        return InvoiceDetailResponse.model_validate(invoice)

    async def _get_mutable_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> Invoice:
        """Load an invoice (with line items) and reject edits once paid or void."""
        invoice = await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[selectinload(Invoice.line_items)],
        )
        if invoice.status in ("paid", "void"):
            raise ConflictError(f"Cannot edit line items on a {invoice.status} invoice")
        return invoice
