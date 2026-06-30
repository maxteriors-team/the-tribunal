"""Quote (estimate) business logic.

Mirrors :class:`app.services.invoices.invoice_service.InvoiceService`
conventions (``get_or_404``/``get_nested_or_404`` lookups, ``paginate`` for
lists, ``selectinload`` + explicit ``refresh`` so async serialization never
triggers a lazy load, ``float`` money math rounded to two decimals).

A quote's lifecycle is operator-driven: ``draft -> sent -> approved/declined``.
``expired`` is derived from ``expiry_date`` on a still-``sent`` quote and is
applied lazily (a scoped bulk UPDATE) on read so listed/fetched quotes are
truthful without a background job. An ``approved`` quote can be **converted**
into a scheduled :class:`Job` and/or an :class:`Invoice`; the resulting ids are
recorded on the quote so the sales -> work -> billing chain stays auditable.
"""

import uuid
from datetime import UTC, date, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.db.pagination import paginate
from app.models.quote import Quote, QuoteLineItem
from app.schemas.invoice import InvoiceCreate, InvoiceLineItemCreate
from app.schemas.quote import (
    PaginatedQuotes,
    QuoteConvertResponse,
    QuoteCreate,
    QuoteDetailResponse,
    QuoteLineItemCreate,
    QuoteLineItemUpdate,
    QuoteResponse,
    QuoteUpdate,
)
from app.services.automations.events import (
    EVENT_QUOTE_APPROVED,
    EVENT_QUOTE_CONVERTED,
    EVENT_QUOTE_DECLINED,
    EVENT_QUOTE_SENT,
    emit_automation_event,
)
from app.services.exceptions import ConflictError

logger = structlog.get_logger()

# Statuses past which header/line edits and deletes are blocked: a quote the
# customer has decided on (or that lapsed) is a historical record.
_LOCKED_STATUSES = frozenset({"approved", "declined", "expired"})


class QuoteService:
    """Service for quote CRUD, lifecycle, and conversion to job/invoice."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="quote_service")

    # ------------------------------------------------------------------
    # Derivation helpers (pure; no I/O)
    # ------------------------------------------------------------------

    async def _emit_lifecycle_event(self, quote: Quote, event_type: str) -> None:
        """Queue a quote lifecycle event for automations (no commit).

        Shares the caller's transaction so the event is durable only if the
        transition itself commits. ``emit_automation_event`` no-ops when the
        workspace has no automation listening for ``event_type``.
        """
        await emit_automation_event(
            self.db,
            workspace_id=quote.workspace_id,
            event_type=event_type,
            contact_id=quote.contact_id,
            payload={
                "quote_id": str(quote.id),
                "number": quote.number,
                "status": quote.status,
                "total": float(quote.total or 0),
                "currency": quote.currency,
            },
        )

    def _recompute_totals(self, quote: Quote) -> None:
        """Recompute subtotal/total from line items in place.

        Requires ``quote.line_items`` to be loaded.
        """
        subtotal = round(sum(float(li.total) for li in quote.line_items), 2)
        quote.subtotal = subtotal
        quote.total = round(
            subtotal + float(quote.tax_amount or 0) - float(quote.discount_amount or 0), 2
        )

    @staticmethod
    def _line_total(quantity: float, unit_price: float, discount: float) -> float:
        return round(quantity * unit_price - discount, 2)

    async def _next_quote_number(self, workspace_id: uuid.UUID) -> str:
        """Allocate the next ``QUO-000001`` number for a workspace.

        Uses ``max(existing suffix) + 1`` so numbers stay monotonic even after a
        draft is deleted. Concurrent creates rely on the
        ``uq_quotes_workspace_number`` constraint as the final guard.
        """
        result = await self.db.execute(
            select(Quote.number).where(Quote.workspace_id == workspace_id)
        )
        max_seq = 0
        for number in result.scalars().all():
            try:
                max_seq = max(max_seq, int(number.rsplit("-", 1)[-1]))
            except (ValueError, IndexError):
                continue
        return f"QUO-{max_seq + 1:06d}"

    async def _expire_overdue(self, workspace_id: uuid.UUID) -> None:
        """Flip still-``sent`` quotes past their ``expiry_date`` to ``expired``.

        One scoped UPDATE keeps reads truthful without a background worker; it is
        idempotent and a no-op when nothing has lapsed.
        """
        await self.db.execute(
            update(Quote)
            .where(
                Quote.workspace_id == workspace_id,
                Quote.status == "sent",
                Quote.expiry_date.is_not(None),
                Quote.expiry_date < date.today(),
            )
            .values(status="expired")
        )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def list_quotes(
        self,
        workspace_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
        contact_id: int | None = None,
    ) -> PaginatedQuotes:
        """List a workspace's quotes, newest first, with optional filters."""
        await self._expire_overdue(workspace_id)

        query = select(Quote).where(Quote.workspace_id == workspace_id)
        if status:
            query = query.where(Quote.status == status)
        if contact_id is not None:
            query = query.where(Quote.contact_id == contact_id)
        query = query.order_by(Quote.created_at.desc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        return result.build_response(
            item_model=QuoteResponse,
            response_builder=PaginatedQuotes,
        )

    async def create_quote(
        self,
        workspace_id: uuid.UUID,
        quote_in: QuoteCreate,
        *,
        created_by_id: int | None = None,
    ) -> QuoteDetailResponse:
        """Create a draft quote with its initial line items and computed totals."""
        quote = Quote(
            workspace_id=workspace_id,
            contact_id=quote_in.contact_id,
            service_location_id=quote_in.service_location_id,
            opportunity_id=quote_in.opportunity_id,
            number=await self._next_quote_number(workspace_id),
            title=quote_in.title,
            currency=quote_in.currency,
            tax_amount=quote_in.tax_amount,
            discount_amount=quote_in.discount_amount,
            issue_date=quote_in.issue_date,
            expiry_date=quote_in.expiry_date,
            notes=quote_in.notes,
            terms=quote_in.terms,
            status="draft",
            created_by_id=created_by_id,
        )
        for item in quote_in.line_items:
            quote.line_items.append(
                QuoteLineItem(
                    name=item.name,
                    description=item.description,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    discount=item.discount,
                    total=self._line_total(item.quantity, item.unit_price, item.discount),
                )
            )

        self._recompute_totals(quote)
        self.db.add(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

        self.log.info(
            "quote_created",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            number=quote.number,
            total=float(quote.total),
        )
        return QuoteDetailResponse.model_validate(quote)

    async def get_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Fetch a single quote with its line items."""
        await self._expire_overdue(workspace_id)
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        return QuoteDetailResponse.model_validate(quote)

    async def update_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        quote_in: QuoteUpdate,
    ) -> QuoteDetailResponse:
        """Update quote header fields. Totals are re-derived, not set."""
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot edit a {quote.status} quote")

        for field in (
            "contact_id",
            "service_location_id",
            "opportunity_id",
            "title",
            "currency",
            "tax_amount",
            "discount_amount",
            "issue_date",
            "expiry_date",
            "notes",
            "terms",
        ):
            value = getattr(quote_in, field)
            if value is not None:
                setattr(quote, field, value)

        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def delete_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> None:
        """Delete a draft/sent quote. Decided or expired quotes are kept."""
        quote = await get_or_404(self.db, Quote, quote_id, workspace_id=workspace_id)
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot delete a {quote.status} quote")
        await self.db.delete(quote)
        await self.db.commit()

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    async def mark_sent(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Mark a quote as sent (sets ``sent_at`` once) and email it to the
        quote-to contact (best-effort)."""
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[
                selectinload(Quote.line_items),
                selectinload(Quote.contact),
                selectinload(Quote.workspace),
            ],
        )
        if quote.status in {"approved", "declined"}:
            raise ConflictError(f"Cannot send a {quote.status} quote")
        if quote.sent_at is None:
            quote.sent_at = datetime.now(UTC)
        quote.status = "sent"
        await self._emit_lifecycle_event(quote, EVENT_QUOTE_SENT)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

        await self._email_quote(quote)
        return QuoteDetailResponse.model_validate(quote)

    async def approve_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Operator approves a quote on the customer's behalf."""
        await self._expire_overdue(workspace_id)
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status == "approved":
            return QuoteDetailResponse.model_validate(quote)
        if quote.status not in {"draft", "sent"}:
            raise ConflictError(f"Cannot approve a {quote.status} quote")
        quote.status = "approved"
        quote.approved_at = datetime.now(UTC)
        await self._emit_lifecycle_event(quote, EVENT_QUOTE_APPROVED)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info("quote_approved", quote_id=str(quote.id), workspace_id=str(workspace_id))
        return QuoteDetailResponse.model_validate(quote)

    async def decline_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        reason: str | None = None,
    ) -> QuoteDetailResponse:
        """Operator declines a quote on the customer's behalf."""
        await self._expire_overdue(workspace_id)
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status == "declined":
            return QuoteDetailResponse.model_validate(quote)
        if quote.status not in {"draft", "sent"}:
            raise ConflictError(f"Cannot decline a {quote.status} quote")
        quote.status = "declined"
        quote.declined_at = datetime.now(UTC)
        quote.decline_reason = reason
        await self._emit_lifecycle_event(quote, EVENT_QUOTE_DECLINED)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        self.log.info("quote_declined", quote_id=str(quote.id), workspace_id=str(workspace_id))
        return QuoteDetailResponse.model_validate(quote)

    async def _email_quote(self, quote: Quote) -> None:
        """Email the quote to its contact (best-effort; never raises)."""
        from app.services.email import send_quote_email
        from app.services.idempotency import derive_outbound_key

        contact_email = quote.contact.email if quote.contact else None
        if not contact_email:
            self.log.info("quote_email_skipped_no_contact", quote_id=str(quote.id))
            return

        workspace_name = quote.workspace.name if quote.workspace else ""
        amount_str = f"{float(quote.total or 0):.2f} {quote.currency.upper()}"
        expiry = quote.expiry_date.isoformat() if quote.expiry_date else None

        try:
            await send_quote_email(
                to_email=contact_email,
                workspace_name=workspace_name,
                quote_number=quote.number,
                amount_str=amount_str,
                title=quote.title,
                expiry_date=expiry,
                notes=quote.notes,
                idempotency_key=derive_outbound_key("quote_send", quote.id),
            )
        except Exception as exc:  # pragma: no cover - best-effort email
            self.log.warning("quote_email_failed", quote_id=str(quote.id), error=str(exc))

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    async def convert_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        *,
        create_job: bool = True,
        create_invoice: bool = True,
    ) -> QuoteConvertResponse:
        """Convert an approved quote into a job and/or an invoice (idempotent).

        Re-running returns the already-linked job/invoice rather than creating
        duplicates. A job needs a ``contact_id``; converting to an invoice copies
        the quote's line items verbatim.
        """
        from app.services.invoices import InvoiceService
        from app.services.jobs import JobService

        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status != "approved":
            raise ConflictError("Only an approved quote can be converted")

        job_id = quote.converted_job_id
        invoice_id = quote.converted_invoice_id
        prior_job_id = job_id
        prior_invoice_id = invoice_id

        # Create the invoice first so the job can be linked to it for costing
        # (its profitability reads revenue from the linked invoice).
        if create_invoice and invoice_id is None:
            invoice = await InvoiceService(self.db).create_invoice(
                workspace_id,
                InvoiceCreate(
                    contact_id=quote.contact_id,
                    opportunity_id=quote.opportunity_id,
                    currency=quote.currency,
                    tax_amount=float(quote.tax_amount or 0),
                    discount_amount=float(quote.discount_amount or 0),
                    notes=quote.notes,
                    terms=quote.terms,
                    line_items=[
                        InvoiceLineItemCreate(
                            name=li.name,
                            description=li.description,
                            quantity=float(li.quantity),
                            unit_price=float(li.unit_price),
                            discount=float(li.discount),
                        )
                        for li in quote.line_items
                    ],
                ),
                created_by_id=quote.created_by_id,
            )
            invoice_id = invoice.id
            quote.converted_invoice_id = invoice_id

        if create_job and job_id is None:
            if quote.contact_id is None:
                raise ConflictError("Cannot create a job from a quote with no contact")
            job = await JobService(self.db).create(
                workspace_id,
                {
                    "contact_id": quote.contact_id,
                    "service_location_id": quote.service_location_id,
                    "title": quote.title or f"Quote {quote.number}",
                    "description": quote.notes,
                    # Link the job to the just-created invoice (or a previously
                    # converted one) so its P&L has a revenue side.
                    "invoice_id": invoice_id,
                    "technician_ids": [],
                },
            )
            job_id = job.id
            quote.converted_job_id = job_id

        # Emit only when this call actually converted something — re-running an
        # already-converted quote is a no-op and must not re-fire the event.
        if job_id != prior_job_id or invoice_id != prior_invoice_id:
            await emit_automation_event(
                self.db,
                workspace_id=quote.workspace_id,
                event_type=EVENT_QUOTE_CONVERTED,
                contact_id=quote.contact_id,
                payload={
                    "quote_id": str(quote.id),
                    "number": quote.number,
                    "job_id": str(job_id) if job_id else None,
                    "invoice_id": str(invoice_id) if invoice_id else None,
                },
            )

        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])

        self.log.info(
            "quote_converted",
            quote_id=str(quote.id),
            workspace_id=str(workspace_id),
            job_id=str(job_id) if job_id else None,
            invoice_id=str(invoice_id) if invoice_id else None,
        )
        return QuoteConvertResponse(
            quote=QuoteDetailResponse.model_validate(quote),
            job_id=job_id,
            invoice_id=invoice_id,
        )

    # ------------------------------------------------------------------
    # Line items
    # ------------------------------------------------------------------

    async def add_line_item(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        item_in: QuoteLineItemCreate,
    ) -> QuoteDetailResponse:
        """Add a line item and recompute quote totals."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        quote.line_items.append(
            QuoteLineItem(
                name=item_in.name,
                description=item_in.description,
                quantity=item_in.quantity,
                unit_price=item_in.unit_price,
                discount=item_in.discount,
                total=self._line_total(item_in.quantity, item_in.unit_price, item_in.discount),
            )
        )
        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def update_line_item(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        item_id: uuid.UUID,
        item_in: QuoteLineItemUpdate,
    ) -> QuoteDetailResponse:
        """Update a line item, recompute its total and the quote totals."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        line_item = await get_nested_or_404(
            self.db,
            QuoteLineItem,
            item_id,
            parent_field="quote_id",
            parent_id=quote_id,
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

        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def remove_line_item(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
        item_id: uuid.UUID,
    ) -> QuoteDetailResponse:
        """Remove a line item and recompute quote totals."""
        quote = await self._get_mutable_quote(workspace_id, quote_id)
        line_item = await get_nested_or_404(
            self.db,
            QuoteLineItem,
            item_id,
            parent_field="quote_id",
            parent_id=quote_id,
            detail="Line item not found",
        )
        quote.line_items.remove(line_item)
        await self.db.delete(line_item)
        self._recompute_totals(quote)
        await self.db.commit()
        await self.db.refresh(quote, ["line_items"])
        return QuoteDetailResponse.model_validate(quote)

    async def _get_mutable_quote(
        self,
        workspace_id: uuid.UUID,
        quote_id: uuid.UUID,
    ) -> Quote:
        """Load a quote (with line items) and reject edits once decided/expired."""
        quote = await get_or_404(
            self.db,
            Quote,
            quote_id,
            workspace_id=workspace_id,
            options=[selectinload(Quote.line_items)],
        )
        if quote.status in _LOCKED_STATUSES:
            raise ConflictError(f"Cannot edit line items on a {quote.status} quote")
        return quote
