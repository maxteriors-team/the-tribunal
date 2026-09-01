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

Mutability rules, since "can I still change this?" has three different answers:

* **Hard delete** -- drafts only. An issued invoice is an accounting record, so it
  is voided (``_ISSUED_STATUSES``), never erased.
* **Line items** -- everything except ``paid`` and ``void`` (see
  ``_get_mutable_invoice``). Editing a *sent* invoice is deliberate: change orders
  ("while we were there we also did X") are routine in home services, and the
  customer's public page re-reads totals on load.
* **Header fields** -- anything except ``void``.
"""

import uuid
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import set_committed_value

from app.api.crud import get_nested_or_404, get_or_404
from app.core.config import settings
from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned
from app.models.contact import Contact
from app.models.invoice import Invoice, InvoiceLineItem, generate_invoice_token
from app.models.invoice_payment import InvoicePayment
from app.models.invoice_payment_receipt_outbox import (
    RECEIPT_PENDING,
    RECEIPT_PROCESSING,
    RECEIPT_SENT,
    RECEIPT_TERMINAL,
    InvoicePaymentReceiptOutbox,
)
from app.models.opportunity import Opportunity
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDeliverResult,
    InvoiceDeliveryStatus,
    InvoiceDetailResponse,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
    InvoiceManualPaymentCreate,
    InvoiceReceiptDelivery,
    InvoiceResponse,
    InvoiceSendResponse,
    InvoiceUpdate,
    PaginatedInvoices,
    PublicInvoice,
    PublicInvoiceLineItem,
    PublicInvoicePaymentCheckout,
    PublicInvoicePaymentStatus,
)
from app.schemas.proposal import PublicProposalBranding
from app.services.automations.events import (
    EVENT_INVOICE_PAID,
    EVENT_INVOICE_SENT,
    emit_automation_event,
)
from app.services.exceptions import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.services.idempotency import derive_outbound_key
from app.services.invoices.receipt_outbox_service import enqueue_invoice_payment_receipt
from app.services.opportunities.invoice_lifecycle import transition_invoice_opportunity
from app.services.payments import call_payment_service

logger = structlog.get_logger()

# Statuses that mean the invoice has been issued to the customer; line-item edits
# and hard deletes are blocked once an invoice reaches any of these.
_ISSUED_STATUSES = frozenset({"sent", "paid", "partial", "overdue"})


def serialize_invoice[R: InvoiceResponse](
    invoice: Invoice,
    model: type[R],
    *,
    receipt_job: InvoicePaymentReceiptOutbox | None = None,
) -> R:
    """Serialize an invoice with its contact label and safe receipt state.

    Relationships must be eager loaded before this synchronous projection. Raw
    outbox errors are never returned; operators get only an allowlisted next step.
    """
    response = model.model_validate(invoice)
    if "contact" not in inspect(invoice).unloaded:
        contact = invoice.contact
        response.contact_name = contact.full_name if contact else None

    if receipt_job is None:
        response.receipt_delivery = (
            InvoiceReceiptDelivery(
                status="needs_attention",
                timestamp=invoice.paid_at,
                reason="No receipt is queued. Retry the receipt to queue delivery.",
            )
            if invoice.paid_at is not None
            else InvoiceReceiptDelivery()
        )
    elif receipt_job.status in (RECEIPT_PENDING, RECEIPT_PROCESSING):
        response.receipt_delivery = InvoiceReceiptDelivery(
            status="pending",
            recipient=receipt_job.recipient_email,
            timestamp=receipt_job.updated_at or receipt_job.created_at,
        )
    elif receipt_job.status == RECEIPT_SENT:
        response.receipt_delivery = InvoiceReceiptDelivery(
            status="sent",
            recipient=receipt_job.recipient_email,
            timestamp=receipt_job.sent_at or receipt_job.updated_at,
        )
    else:
        reason = (
            "Add an email address to the customer, then retry the receipt."
            if not receipt_job.recipient_email
            else "Receipt delivery failed after multiple attempts. Retry the receipt."
        )
        response.receipt_delivery = InvoiceReceiptDelivery(
            status="needs_attention",
            recipient=receipt_job.recipient_email,
            timestamp=receipt_job.terminal_at or receipt_job.updated_at,
            reason=reason,
        )
    return response


class InvoiceService:
    """Service for customer-invoice CRUD, lifecycle, and payment reconciliation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="invoice_service")

    # ------------------------------------------------------------------
    # Reference validation (tenant-safe)
    # ------------------------------------------------------------------

    async def _validate_refs(
        self,
        workspace_id: uuid.UUID,
        *,
        contact_id: int | None = None,
        opportunity_id: uuid.UUID | None = None,
    ) -> None:
        """Validate client-supplied references belong to ``workspace_id``.

        Only ids that were actually supplied are checked. A foreign id 404s
        exactly like a missing one, so a caller cannot bill another tenant's
        contact and have the platform email that contact (which would echo
        their decrypted details back in the response).
        """
        if contact_id is not None:
            await assert_workspace_owned(
                self.db, Contact, contact_id, workspace_id, detail="Contact not found"
            )
        if opportunity_id is not None:
            await assert_workspace_owned(
                self.db,
                Opportunity,
                opportunity_id,
                workspace_id,
                detail="Opportunity not found",
            )

    async def _load_locked_invoice(self, workspace_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        """Load the latest workspace-scoped invoice state and hold its row lock."""
        result = await self.db.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id, Invoice.workspace_id == workspace_id)
            .options(selectinload(Invoice.line_items), selectinload(Invoice.contact))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Invoice not found")
        return invoice

    async def _latest_receipt_jobs(
        self, workspace_id: uuid.UUID, invoice_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, InvoicePaymentReceiptOutbox]:
        """Load one newest workspace-scoped receipt job per invoice."""
        if not invoice_ids:
            return {}
        jobs = (
            await self.db.scalars(
                select(InvoicePaymentReceiptOutbox)
                .where(
                    InvoicePaymentReceiptOutbox.workspace_id == workspace_id,
                    InvoicePaymentReceiptOutbox.invoice_id.in_(invoice_ids),
                )
                .order_by(
                    InvoicePaymentReceiptOutbox.invoice_id,
                    InvoicePaymentReceiptOutbox.created_at.desc(),
                )
            )
        ).all()
        latest: dict[uuid.UUID, InvoicePaymentReceiptOutbox] = {}
        for job in jobs:
            latest.setdefault(job.invoice_id, job)
        return latest

    async def _serialize_invoice[R: InvoiceResponse](
        self, workspace_id: uuid.UUID, invoice: Invoice, model: type[R]
    ) -> R:
        if issubclass(model, InvoiceDetailResponse):
            payments = (
                await self.db.scalars(
                    select(InvoicePayment)
                    .where(
                        InvoicePayment.workspace_id == workspace_id,
                        InvoicePayment.invoice_id == invoice.id,
                    )
                    .order_by(InvoicePayment.received_at, InvoicePayment.created_at)
                )
            ).all()
            set_committed_value(invoice, "payments", payments)
        jobs = await self._latest_receipt_jobs(workspace_id, [invoice.id])
        return serialize_invoice(invoice, model, receipt_job=jobs.get(invoice.id))

    async def _invalidate_checkout_for_edit(self, invoice: Invoice) -> None:
        """Expire a stored Checkout Session or abort without saving the edit."""
        session_id = invoice.stripe_checkout_session_id
        if session_id is None:
            return
        try:
            expired = await call_payment_service.expire_checkout_session_if_open(session_id)
        except Exception as exc:
            await self.db.rollback()
            self.log.warning(
                "invoice_checkout_expiration_failed",
                invoice_id=str(invoice.id),
                error=str(exc),
            )
            raise ServiceUnavailableError(
                "Could not invalidate the current checkout; invoice changes were not saved"
            ) from exc
        if not expired:
            await self.db.rollback()
            raise ConflictError(
                "The current checkout could not be invalidated; refresh the invoice before editing"
            )
        # Keep the stable customer URL and payment history. Only the now-expired
        # price snapshot is stale.
        invoice.stripe_checkout_session_id = None

    async def _prepare_checkout_for_manual_payment(self, invoice: Invoice) -> bool:
        """Expire an open card checkout; return True when Stripe already won."""
        session_id = invoice.stripe_checkout_session_id
        if not session_id:
            return False
        if not call_payment_service.is_payment_configured():
            raise ServiceUnavailableError(
                "The online payment link could not be closed safely. Try again when "
                "card payments are available."
            )

        async def retrieve_status() -> call_payment_service.SessionStatus:
            try:
                return await call_payment_service.retrieve_session_status(session_id)
            except Exception as exc:
                self.log.warning(
                    "invoice_manual_payment_checkout_lookup_failed",
                    invoice_id=str(invoice.id),
                    session_id=session_id,
                    error=str(exc),
                )
                raise ServiceUnavailableError(
                    "The online payment link could not be checked. Try again before "
                    "recording this payment."
                ) from exc

        checkout_status = await retrieve_status()
        if checkout_status.payment_status == "paid":
            remaining = max(0.0, round(float(invoice.total) - float(invoice.amount_paid), 2))
            await self.record_payment(
                invoice,
                remaining,
                payment_intent_id=checkout_status.payment_intent_id,
                checkout_session_id=session_id,
            )
            return True
        if checkout_status.status != "open":
            invoice.stripe_checkout_session_id = None
            return False

        try:
            expired = await call_payment_service.expire_checkout_session_if_open(session_id)
        except Exception as exc:
            self.log.warning(
                "invoice_manual_payment_checkout_expire_failed",
                invoice_id=str(invoice.id),
                session_id=session_id,
                error=str(exc),
            )
            raise ServiceUnavailableError(
                "The online payment link could not be closed. Try again before recording "
                "this payment."
            ) from exc
        if expired:
            invoice.stripe_checkout_session_id = None
            return False

        checkout_status = await retrieve_status()
        if checkout_status.payment_status == "paid":
            remaining = max(0.0, round(float(invoice.total) - float(invoice.amount_paid), 2))
            await self.record_payment(
                invoice,
                remaining,
                payment_intent_id=checkout_status.payment_intent_id,
                checkout_session_id=session_id,
            )
            return True
        raise ConflictError("The online payment changed state. Refresh the invoice and try again.")

    async def _transition_to_fully_paid(
        self,
        invoice: Invoice,
        *,
        payment_amount: float,
        payment_event_id: str | None,
        queue_receipt: bool = True,
    ) -> bool:
        """Atomically apply the first paid transition and optionally queue its receipt."""
        invoice.status = self.derive_status(invoice)
        if invoice.status != "paid" or invoice.paid_at is not None:
            return False

        invoice.paid_at = datetime.now(UTC)
        event_id = payment_event_id or f"paid-transition:{invoice.paid_at.isoformat()}"
        await emit_automation_event(
            self.db,
            workspace_id=invoice.workspace_id,
            event_type=EVENT_INVOICE_PAID,
            contact_id=invoice.contact_id,
            payload={
                "invoice_id": str(invoice.id),
                "number": invoice.number,
                "total": float(invoice.total or 0),
                "amount_paid": float(invoice.amount_paid or 0),
                "currency": invoice.currency,
                "opportunity_id": (
                    str(invoice.opportunity_id) if invoice.opportunity_id is not None else None
                ),
            },
        )
        await transition_invoice_opportunity(
            self.db,
            invoice,
            transition="paid",
        )
        if queue_receipt:
            await enqueue_invoice_payment_receipt(
                self.db,
                invoice,
                payment_amount=payment_amount,
                payment_event_id=event_id,
            )
        return True

    async def _commit_edit(self, invoice: Invoice, *, checkout_affecting: bool) -> None:
        """Validate and atomically commit one locked invoice edit."""
        total = round(float(invoice.total or 0), 2)
        paid = round(float(invoice.amount_paid or 0), 2)
        if total < paid:
            await self.db.rollback()
            raise ConflictError("Invoice total cannot be less than the amount already paid")

        if checkout_affecting:
            await self._invalidate_checkout_for_edit(invoice)
        await self._transition_to_fully_paid(
            invoice,
            payment_amount=paid,
            payment_event_id=invoice.stripe_payment_intent_id,
            queue_receipt=False,
        )
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items", "contact"])

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
        """Recompute totals from selected rows and re-derive status in place.

        Required rows are always selected. Optional rows contribute only when the
        recipient selected them. Requires ``invoice.line_items`` to be loaded.
        """
        for line_item in invoice.line_items:
            if not line_item.is_optional:
                line_item.is_selected = True
        subtotal = round(
            sum(
                float(line_item.total) for line_item in invoice.line_items if line_item.is_selected
            ),
            2,
        )
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
        """List a workspace's invoices, newest first, with optional filters.

        The bill-to contact is eager loaded so each row can name whose invoice it
        is. ``selectinload`` issues one extra query for the whole page rather than
        one per row, so naming 100 invoices costs 2 queries, not 101.
        """
        query = (
            select(Invoice)
            .where(Invoice.workspace_id == workspace_id)
            .options(selectinload(Invoice.contact))
        )
        if status:
            query = query.where(Invoice.status == status)
        if contact_id is not None:
            query = query.where(Invoice.contact_id == contact_id)
        query = query.order_by(Invoice.created_at.desc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        jobs = await self._latest_receipt_jobs(
            workspace_id, [invoice.id for invoice in result.items]
        )
        return result.build_response(
            item_mapper=lambda invoice: serialize_invoice(
                invoice, InvoiceResponse, receipt_job=jobs.get(invoice.id)
            ),
            response_builder=PaginatedInvoices,
        )

    async def create_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_in: InvoiceCreate,
        *,
        created_by_id: int | None = None,
        amount_paid: float = 0.0,
        payment_intent_id: str | None = None,
        opening_payment_method: str | None = None,
        commit: bool = True,
    ) -> InvoiceDetailResponse:
        """Create a draft invoice with its initial line items and computed totals.

        ``amount_paid``/``payment_intent_id`` open the invoice with money already
        collected -- today only a quote deposit the client paid on the public
        proposal page (see :meth:`QuoteService.convert_quote`). They are
        **service-internal on purpose**: ``InvoiceCreate`` does not carry them, so
        an API client still cannot declare an invoice pre-paid and mark itself
        settled without money moving. The opening credit is clamped to the
        invoice total so a stale deposit can never create a negative balance, and
        ``status`` is derived from it (a fully-covering deposit opens ``paid``).
        """
        await self._validate_refs(
            workspace_id,
            contact_id=invoice_in.contact_id,
            opportunity_id=invoice_in.opportunity_id,
        )
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
            stripe_payment_intent_id=payment_intent_id,
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
                    is_optional=item.is_optional,
                    is_selected=True,
                )
            )

        # Totals first: the opening credit clamps against the computed total.
        self._recompute_totals(invoice)
        opening_credit = round(max(0.0, min(float(amount_paid), float(invoice.total or 0))), 2)
        opening_method = opening_payment_method or ("card" if payment_intent_id else "other")
        if opening_credit > 0:
            invoice.amount_paid = opening_credit
            invoice.payment_method = opening_method if opening_method != "other" else None
        self.db.add(invoice)
        await self.db.flush()
        if opening_credit > 0:
            self.db.add(
                InvoicePayment(
                    workspace_id=workspace_id,
                    invoice_id=invoice.id,
                    payment_method=opening_method,
                    amount=opening_credit,
                    external_event_id=payment_intent_id,
                    received_at=datetime.now(UTC),
                )
            )
            await self._transition_to_fully_paid(
                invoice,
                payment_amount=opening_credit,
                payment_event_id=payment_intent_id,
            )
        if commit:
            await self.db.commit()
            await self.db.refresh(invoice, ["line_items"])
            self.log.info(
                "invoice_created",
                invoice_id=str(invoice.id),
                workspace_id=str(workspace_id),
                number=invoice.number,
                total=float(invoice.total),
                amount_paid=float(invoice.amount_paid),
            )
        else:
            # Quote conversion owns one transaction for quote, job, and invoice.
            # Flush assigns IDs while leaving rollback/commit to that caller.
            await self.db.flush()
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

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
            options=[selectinload(Invoice.line_items), selectinload(Invoice.contact)],
        )
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

    async def update_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        invoice_in: InvoiceUpdate,
    ) -> InvoiceDetailResponse:
        """Update a locked invoice and invalidate any stale checkout price."""
        invoice = await self._load_locked_invoice(workspace_id, invoice_id)
        if invoice.status == "void":
            await self.db.commit()
            raise ConflictError("Cannot edit a voided invoice")

        checkout_affecting_fields = invoice_in.checkout_affecting_fields
        if invoice.status == "paid" and checkout_affecting_fields:
            await self.db.commit()
            raise ConflictError(
                "Cannot change amounts, currency, contact, or line items on a paid invoice"
            )

        await self._validate_refs(
            workspace_id,
            contact_id=invoice_in.contact_id,
            opportunity_id=invoice_in.opportunity_id,
        )

        nullable_fields = {
            "contact_id",
            "opportunity_id",
            "issue_date",
            "due_date",
            "notes",
            "terms",
        }
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
            if field not in invoice_in.model_fields_set:
                continue
            value = getattr(invoice_in, field)
            if value is not None or field in nullable_fields:
                setattr(invoice, field, value)

        if invoice_in.line_items is not None:
            # Whole-set replacement inside this transaction, so a multi-row edit
            # can never half-apply. ``delete-orphan`` removes dropped rows.
            invoice.line_items.clear()
            for item in invoice_in.line_items:
                invoice.line_items.append(
                    InvoiceLineItem(
                        name=item.name,
                        description=item.description,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        discount=item.discount,
                        total=self._line_total(item.quantity, item.unit_price, item.discount),
                        is_optional=item.is_optional,
                        is_selected=True,
                    )
                )

        self._recompute_totals(invoice)
        await self._commit_edit(invoice, checkout_affecting=bool(checkout_affecting_fields))
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

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

    async def _load_for_send(self, workspace_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        """Lock an invoice with everything a delivery needs."""
        result = await self.db.execute(
            select(Invoice)
            .where(Invoice.id == invoice_id, Invoice.workspace_id == workspace_id)
            .options(
                selectinload(Invoice.line_items),
                selectinload(Invoice.contact),
                selectinload(Invoice.workspace),
            )
            .with_for_update()
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise NotFoundError("Invoice not found")
        return invoice

    async def _transition_to_sent(self, workspace_id: uuid.UUID, invoice: Invoice) -> None:
        """Move an invoice into ``sent`` and allocate its public token.

        Split out of :meth:`mark_sent` so a *text* delivery can put the invoice
        in the same state without also emailing it -- otherwise texting an
        invoice would silently send an email too.
        """
        if invoice.status == "void":
            raise ConflictError("Cannot send a voided invoice")
        was_sent = invoice.sent_at is not None
        if invoice.sent_at is None:
            invoice.sent_at = datetime.now(UTC)
        # Allocate the public page token lazily on first send, so a draft link
        # can never resolve. Kept stable across re-sends: the customer may have
        # bookmarked the link from an earlier reminder.
        if invoice.public_token is None:
            invoice.public_token = generate_invoice_token()
        invoice.status = self.derive_status(invoice)
        # Fire on the first send only; re-sending a reminder must not re-trigger.
        if not was_sent:
            await emit_automation_event(
                self.db,
                workspace_id=workspace_id,
                event_type=EVENT_INVOICE_SENT,
                contact_id=invoice.contact_id,
                payload={
                    "invoice_id": str(invoice.id),
                    "number": invoice.number,
                    "total": float(invoice.total or 0),
                    "currency": invoice.currency,
                    "opportunity_id": (
                        str(invoice.opportunity_id) if invoice.opportunity_id is not None else None
                    ),
                },
            )
            await transition_invoice_opportunity(
                self.db,
                invoice,
                transition="sent",
            )
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])

    async def mark_sent(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> InvoiceSendResponse:
        """Mark an invoice sent and report whether email reached the customer."""
        invoice = await self._load_for_send(workspace_id, invoice_id)
        await self._transition_to_sent(workspace_id, invoice)

        delivery, delivered_to = await self._email_invoice(workspace_id, invoice)
        detail = await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)
        return InvoiceSendResponse(
            **detail.model_dump(),
            delivery=delivery,
            delivered_to=delivered_to,
        )

    async def retry_payment_receipt(
        self, workspace_id: uuid.UUID, invoice_id: uuid.UUID
    ) -> InvoiceDetailResponse:
        """Idempotently queue or reopen a failed receipt; never deliver inline."""
        invoice = await self._load_locked_invoice(workspace_id, invoice_id)
        if float(invoice.amount_paid or 0) <= 0:
            await self.db.commit()
            raise ConflictError("A payment receipt can be retried only after a payment is recorded")

        job = await self.db.scalar(
            select(InvoicePaymentReceiptOutbox)
            .where(
                InvoicePaymentReceiptOutbox.workspace_id == workspace_id,
                InvoicePaymentReceiptOutbox.invoice_id == invoice_id,
            )
            .order_by(InvoicePaymentReceiptOutbox.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        if job is not None and job.status in (
            RECEIPT_PENDING,
            RECEIPT_PROCESSING,
            RECEIPT_SENT,
        ):
            await self.db.commit()
            return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)
        if job is not None and job.status != RECEIPT_TERMINAL:
            await self.db.commit()
            raise ConflictError("Receipt delivery is not in a retryable state")

        recipient = invoice.last_emailed_to or (invoice.contact.email if invoice.contact else None)
        if job is not None and job.recipient_email:
            recipient = job.recipient_email
        if not recipient:
            await self.db.commit()
            raise ConflictError(
                "Add an email address to the invoice customer before retrying the receipt"
            )

        if job is None and invoice.paid_at is None:
            await self.db.commit()
            raise ConflictError("No payment receipt is available to retry")

        if job is None:
            job = await enqueue_invoice_payment_receipt(
                self.db,
                invoice,
                payment_amount=float(invoice.total or invoice.amount_paid or 0),
                payment_event_id=f"operator-retry:{invoice.id}",
            )
        else:
            job.recipient_email = recipient
            job.idempotency_key = derive_outbound_key(
                "invoice_payment_receipt",
                invoice.id,
                job.payment_event_id,
                recipient,
            )
            job.status = RECEIPT_PENDING
            job.attempt_count = 0
            job.next_attempt_at = datetime.now(UTC)
            job.claimed_at = None
            job.sent_at = None
            job.terminal_at = None
            job.last_error = None

        await self.db.commit()
        await self.db.refresh(job)
        self.log.info(
            "invoice_receipt_retried",
            workspace_id=str(workspace_id),
            invoice_id=str(invoice_id),
            job_id=str(job.id),
        )
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

    async def deliver_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        *,
        channel: str,
        to: str | None = None,
    ) -> InvoiceDeliverResult:
        """Send the customer their invoice link by ``email`` or ``sms``.

        Transitions the invoice to ``sent`` first (allocating its share token),
        then delivers. Destination precedence: explicit ``to`` -> the bill-to
        contact's email/phone. Mirrors ``QuoteService.deliver_quote`` so the two
        customer-facing rails behave the same way.

        Texting matters for home services: a homeowner who ignores email will
        open a text, and the link is the same stable invoice page.
        """
        invoice = await self._load_for_send(workspace_id, invoice_id)
        await self._transition_to_sent(workspace_id, invoice)

        if channel == "email":
            override = (to or "").strip() or None
            delivery, delivered_to = await self._email_invoice(
                workspace_id, invoice, override_email=override
            )
            if delivery != "emailed":
                # Unlike ``mark_sent`` (a bulk action where a bounce must not
                # undo the transition), this is a deliberate one-shot "send it
                # to this person" -- so a miss is an error the operator sees.
                raise ValidationError(
                    "No email address for this customer — add one or pass a destination."
                    if delivery == "skipped_no_email"
                    else "The invoice email could not be sent. Please try again."
                )
            self.log.info("invoice_delivered", invoice_id=str(invoice.id), channel="email")
            return InvoiceDeliverResult(ok=True, channel="email", to=delivered_to or "")

        if channel != "sms":
            raise ValidationError(f"Unknown delivery channel: {channel!r}")

        phone = (to or "").strip() or (invoice.contact.phone_number if invoice.contact else None)
        if not phone:
            raise ValidationError(
                "No phone number for this customer — add one or pass a destination."
            )

        from app.services.messaging.client_sms import send_client_link_sms

        business = invoice.workspace.name if invoice.workspace else "our team"
        first = (invoice.contact.first_name or "").strip() if invoice.contact else ""
        greeting = f"Hi {first}, " if first else ""
        balance = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
        link = f"{settings.frontend_url.rstrip('/')}/p/invoices/{invoice.public_token}"
        # Lead with the amount owed: a text is glanced at, so the number and the
        # link have to survive a two-second read.
        amount = f"{balance:,.2f} {invoice.currency}"
        await send_client_link_sms(
            self.db,
            workspace_id,
            phone=phone,
            contact_id=invoice.contact_id,
            body=(
                f"{greeting}your invoice {invoice.number} from {business} is ready — "
                f"{amount} due. View and pay here: {link}"
            ),
            idempotency_scope="invoice_sms",
            idempotency_id=invoice.id,
        )
        self.log.info("invoice_delivered", invoice_id=str(invoice.id), channel="sms")
        return InvoiceDeliverResult(ok=True, channel="sms", to=phone)

    async def _email_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice: Invoice,
        *,
        override_email: str | None = None,
    ) -> tuple[InvoiceDeliveryStatus, str | None]:
        """Email the invoice to its bill-to contact (best-effort).

        Never raises: a delivery failure must not undo the ``sent`` transition,
        mirroring ``notify_payment_operators``.

        The "Pay now" link points at the customer's own invoice page, **not** a
        Stripe Checkout URL. A Checkout Session expires -- and a re-sent reminder
        would mint a new one, silently killing the link in the previous email --
        whereas the token page is stable for the life of the invoice and opens a
        fresh session on demand. It also shows the customer what they are paying
        for: line items, the credited deposit, and the remaining balance.

        Returns ``(delivery, delivered_to)`` so the caller can surface what really
        happened instead of assuming success.
        """
        from app.services.email import send_invoice_email
        from app.services.idempotency import derive_document_send_key

        contact_email = override_email or (invoice.contact.email if invoice.contact else None)
        if not contact_email:
            self.log.info("invoice_email_skipped_no_contact", invoice_id=str(invoice.id))
            return "skipped_no_email", None

        workspace_name = invoice.workspace.name if invoice.workspace else ""
        balance = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
        amount_str = f"{balance:.2f} {invoice.currency.upper()}"
        due_date = invoice.due_date.isoformat() if invoice.due_date else None

        # Only offer a payment link when something is actually owed; a settled
        # invoice emails as a receipt.
        pay_url: str | None = None
        if balance > 0 and invoice.public_token:
            pay_url = f"{settings.frontend_url}/p/invoices/{invoice.public_token}"

        try:
            accepted = await send_invoice_email(
                to_email=contact_email,
                workspace_name=workspace_name,
                invoice_number=invoice.number,
                amount_str=amount_str,
                due_date=due_date,
                pay_url=pay_url,
                notes=invoice.notes,
                # Revision-keyed: correcting an invoice and sending it again has
                # to reach the customer, not collide with the original send.
                idempotency_key=derive_document_send_key(
                    "invoice_send", invoice.id, invoice.updated_at, contact_email
                ),
            )
        except Exception as exc:  # pragma: no cover - best-effort email
            self.log.warning("invoice_email_failed", invoice_id=str(invoice.id), error=str(exc))
            return "failed", None

        # ``send_invoice_email`` returns True only when the provider accepted it,
        # so skipped/rejected sends leave the last successful destination intact.
        if not accepted:
            self.log.warning("invoice_email_not_accepted", invoice_id=str(invoice.id))
            return "failed", None

        accepted_at = datetime.now(UTC)
        try:
            # Delivery metadata is not an invoice content revision: preserve
            # ``updated_at`` so provider idempotency stays stable across request retries.
            await self.db.execute(
                update(Invoice)
                .where(
                    Invoice.id == invoice.id,
                    Invoice.workspace_id == workspace_id,
                    (Invoice.last_emailed_at.is_(None)) | (Invoice.last_emailed_at <= accepted_at),
                )
                .values(
                    last_emailed_to=contact_email,
                    last_emailed_at=accepted_at,
                    updated_at=Invoice.updated_at,
                )
                .execution_options(synchronize_session=False)
            )
            await self.db.commit()
            await self.db.refresh(invoice, ["last_emailed_to", "last_emailed_at"])
        except Exception as exc:  # pragma: no cover - provider already accepted
            await self.db.rollback()
            self.log.warning(
                "invoice_email_snapshot_failed",
                invoice_id=str(invoice.id),
                error=str(exc),
            )
            return "failed", None
        return "emailed", contact_email

    async def void_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> InvoiceDetailResponse:
        """Void a locked invoice after invalidating any active checkout."""
        invoice = await self._load_locked_invoice(workspace_id, invoice_id)
        if invoice.status == "paid":
            await self.db.commit()
            raise ConflictError("Cannot void a fully paid invoice")
        await self._invalidate_checkout_for_edit(invoice)
        invoice.status = "void"
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items", "contact"])
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

    async def _apply_manual_payment(
        self,
        invoice: Invoice,
        payment: InvoiceManualPaymentCreate,
        *,
        amount: float,
        reference: str | None,
        recorded_by_id: int,
    ) -> float:
        """Apply one validated payment inside the caller's locked transaction."""
        received_at = datetime.now(UTC)
        invoice.amount_paid = round(float(invoice.amount_paid or 0) + amount, 2)
        invoice.payment_method = payment.payment_method
        invoice.payment_recorded_by_id = recorded_by_id
        invoice.manual_payment_amount = amount
        invoice.manual_payment_reference = reference
        invoice.manual_payment_idempotency_key = payment.idempotency_key
        invoice.public_token = invoice.public_token or generate_invoice_token()
        self.db.add(
            InvoicePayment(
                workspace_id=invoice.workspace_id,
                invoice_id=invoice.id,
                payment_method=payment.payment_method,
                amount=amount,
                reference=reference,
                recorded_by_id=recorded_by_id,
                idempotency_key=payment.idempotency_key,
                received_at=received_at,
            )
        )

        balance_remaining = round(float(invoice.total) - float(invoice.amount_paid), 2)
        if balance_remaining <= 0:
            await self._transition_to_fully_paid(
                invoice,
                payment_amount=amount,
                payment_event_id=f"manual-payment:{payment.idempotency_key}",
            )
        else:
            invoice.status = self.derive_status(invoice)
            await enqueue_invoice_payment_receipt(
                self.db,
                invoice,
                payment_amount=amount,
                payment_event_id=f"manual-payment:{payment.idempotency_key}",
                balance_remaining=balance_remaining,
                received_at=received_at,
            )
        return balance_remaining

    async def record_manual_payment(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
        payment: InvoiceManualPaymentCreate,
        *,
        recorded_by_id: int,
    ) -> InvoiceDetailResponse:
        """Record a partial or final cash/check payment and queue its receipt."""
        invoice = await self._load_locked_invoice(workspace_id, invoice_id)
        reference = (
            payment.reference.strip()
            if payment.payment_method == "check" and payment.reference
            else None
        )
        amount = round(float(payment.amount), 2)
        if amount <= 0:
            await self.db.commit()
            raise ValidationError("Payment amount must be at least 0.01")

        existing_payment = await self.db.scalar(
            select(InvoicePayment).where(
                InvoicePayment.workspace_id == workspace_id,
                InvoicePayment.idempotency_key == payment.idempotency_key,
            )
        )
        if existing_payment is not None:
            if (
                existing_payment.invoice_id != invoice_id
                or existing_payment.payment_method != payment.payment_method
                or float(existing_payment.amount) != amount
                or (existing_payment.reference or None) != reference
            ):
                await self.db.commit()
                raise ConflictError("This payment request was already used with different details")
            await self.db.commit()
            return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

        if invoice.status == "void":
            await self.db.commit()
            raise ConflictError("A payment cannot be recorded on a void invoice")
        if invoice.paid_at is not None:
            await self.db.commit()
            raise ConflictError("This invoice is already fully paid")

        remaining = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
        if remaining <= 0:
            await self.db.commit()
            raise ConflictError("This invoice has no remaining balance")
        if amount > remaining:
            await self.db.commit()
            raise ValidationError(f"Payment cannot exceed the remaining balance of {remaining:.2f}")
        if await self._prepare_checkout_for_manual_payment(invoice):
            return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

        balance_remaining = await self._apply_manual_payment(
            invoice,
            payment,
            amount=amount,
            reference=reference,
            recorded_by_id=recorded_by_id,
        )
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            key_owner = await self.db.scalar(
                select(InvoicePayment.id).where(
                    InvoicePayment.workspace_id == workspace_id,
                    InvoicePayment.idempotency_key == payment.idempotency_key,
                )
            )
            if key_owner is not None:
                raise ConflictError("This payment request was already used") from None
            raise
        self.log.info(
            "invoice_manual_payment_recorded",
            workspace_id=str(workspace_id),
            invoice_id=str(invoice_id),
            payment_method=payment.payment_method,
            amount=amount,
            balance_remaining=balance_remaining,
            recorded_by_id=recorded_by_id,
        )
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

    async def record_payment(
        self,
        invoice: Invoice,
        amount: float,
        *,
        payment_intent_id: str | None = None,
        checkout_session_id: str | None = None,
    ) -> bool:
        """Apply a payment while holding the invoice lock; dedupe by Stripe ids.

        The lock serializes webhook retries with operator edits. The paid transition
        owns ``paid_at`` and its automation event, so no caller can derive ``paid``
        while skipping those side effects.
        """
        invoice = await self._load_locked_invoice(invoice.workspace_id, invoice.id)
        if (
            checkout_session_id is not None
            and invoice.stripe_checkout_session_id != checkout_session_id
        ):
            await self.db.commit()
            self.log.warning(
                "invoice_stale_checkout_ignored",
                invoice_id=str(invoice.id),
                checkout_session_id=checkout_session_id,
            )
            return False

        already_applied = payment_intent_id is not None and (
            invoice.stripe_payment_intent_id == payment_intent_id
            or await self.db.scalar(
                select(InvoicePayment.id).where(
                    InvoicePayment.external_event_id == payment_intent_id
                )
            )
            is not None
        )
        if already_applied:
            await self.db.commit()
            return False

        received_at = datetime.now(UTC)
        invoice.amount_paid = round(float(invoice.amount_paid or 0) + float(amount), 2)
        invoice.payment_method = "card"
        invoice.payment_recorded_by_id = None
        invoice.manual_payment_amount = None
        invoice.manual_payment_reference = None
        invoice.manual_payment_idempotency_key = None
        if payment_intent_id:
            invoice.stripe_payment_intent_id = payment_intent_id
        self.db.add(
            InvoicePayment(
                workspace_id=invoice.workspace_id,
                invoice_id=invoice.id,
                payment_method="card",
                amount=float(amount),
                external_event_id=payment_intent_id,
                received_at=received_at,
            )
        )
        payment_event_id = (
            payment_intent_id
            or checkout_session_id
            or f"card-payment:{invoice.id}:{received_at.isoformat()}"
        )
        became_fully_paid = await self._transition_to_fully_paid(
            invoice,
            payment_amount=float(amount),
            payment_event_id=payment_event_id,
        )
        if not became_fully_paid:
            await enqueue_invoice_payment_receipt(
                self.db,
                invoice,
                payment_amount=float(amount),
                payment_event_id=payment_event_id,
                balance_remaining=max(
                    0, round(float(invoice.total) - float(invoice.amount_paid), 2)
                ),
                received_at=received_at,
            )
        await self.db.commit()

        self.log.info(
            "invoice_payment_recorded",
            invoice_id=str(invoice.id),
            amount=float(amount),
            amount_paid=float(invoice.amount_paid),
            status=invoice.status,
        )
        # Tell the company money arrived. Fires on every real payment, including
        # a partial one -- a customer paying part of the balance is still news the
        # operator needs. The early return above makes webhook replays no-ops.
        await self._notify_payment_received(invoice, float(amount))
        return True

    async def _notify_payment_received(self, invoice: Invoice, amount: float) -> None:
        """Push + email the workspace that a customer paid (best-effort).

        Never raises: the payment is already banked and Stripe is waiting on a
        2xx, so a mail outage must not turn a successful charge into an event
        Stripe retries forever.
        """
        from app.services.payments.customer_payment_notifications import (
            notify_customer_payment,
        )

        try:
            contact = (
                await self.db.get(Contact, invoice.contact_id)
                if invoice.contact_id is not None
                else None
            )
            client_name = None
            if contact is not None:
                client_name = (
                    " ".join(part for part in (contact.first_name, contact.last_name) if part)
                    or None
                )
            await notify_customer_payment(
                self.db,
                workspace_id=invoice.workspace_id,
                amount=amount,
                currency=invoice.currency,
                description=f"Payment on invoice {invoice.number}",
                idempotency_scope="invoice_payment_operator_email",
                idempotency_id=invoice.id,
                deep_link="/(tabs)/invoices",
                client_name=client_name,
                client_email=contact.email if contact else None,
                client_phone=contact.phone_number if contact else None,
            )
        except Exception as exc:  # pragma: no cover - best-effort notification
            self.log.warning(
                "invoice_payment_notify_failed",
                invoice_id=str(invoice.id),
                error=str(exc),
            )

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
                is_optional=item_in.is_optional,
                is_selected=True,
            )
        )
        self._recompute_totals(invoice)
        await self._commit_edit(invoice, checkout_affecting=True)
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

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
        if item_in.is_optional is not None:
            line_item.is_optional = item_in.is_optional
            if not item_in.is_optional:
                line_item.is_selected = True
        line_item.total = self._line_total(
            float(line_item.quantity), float(line_item.unit_price), float(line_item.discount)
        )

        self._recompute_totals(invoice)
        await self._commit_edit(invoice, checkout_affecting=True)
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

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
        await self._commit_edit(invoice, checkout_affecting=True)
        return await self._serialize_invoice(workspace_id, invoice, InvoiceDetailResponse)

    async def _get_mutable_invoice(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> Invoice:
        """Lock an invoice and reject line-item edits once paid or void."""
        invoice = await self._load_locked_invoice(workspace_id, invoice_id)
        if invoice.status in ("paid", "void"):
            await self.db.commit()
            raise ConflictError(f"Cannot edit line items on a {invoice.status} invoice")
        return invoice

    # ------------------------------------------------------------------
    # Stripe payment link
    # ------------------------------------------------------------------

    async def create_payment_link(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> tuple[str, str | None]:
        """Create a Stripe Checkout link for the invoice's outstanding balance.

        Returns ``(session_id, url)``. Raises :class:`ServiceUnavailableError`
        when Stripe is not configured and :class:`ConflictError` when the invoice
        is void or has nothing left to pay.

        Only the checkout *session id* is persisted here. The payment-intent id is
        deliberately left unset until the webhook records the payment, because
        ``record_payment`` keys idempotency on it -- pre-storing it would make the
        completion webhook a no-op and the payment would never be recorded.
        """
        invoice = await self._load_locked_invoice(workspace_id, invoice_id)
        return await self._start_checkout(invoice)

    async def _start_checkout(
        self,
        invoice: Invoice,
        *,
        return_url: str | None = None,
    ) -> tuple[str, str | None]:
        """Open a Stripe Checkout Session for ``invoice``'s outstanding balance.

        Shared by the operator's ``create_payment_link`` and the customer's public
        pay action so both charge the **same server-computed balance** -- the
        amount owed is never taken from the caller. ``return_url`` sends the
        customer back to their own invoice page instead of the generic result
        page.

        Only the checkout *session id* is persisted. The payment-intent id is
        deliberately left unset until the webhook records the payment, because
        ``record_payment`` keys idempotency on it -- pre-storing it would make the
        completion webhook a no-op and the payment would never be recorded.
        """
        if not call_payment_service.is_payment_configured():
            raise ServiceUnavailableError("Stripe is not configured for payments")
        if invoice.status == "void":
            raise ConflictError("Cannot collect payment on a voided invoice")
        balance = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
        if balance <= 0:
            raise ConflictError("Invoice has no outstanding balance")

        if invoice.stripe_checkout_session_id:
            await self._invalidate_checkout_for_edit(invoice)

        customer_email = invoice.contact.email if invoice.contact else None
        result = await call_payment_service.create_payment_checkout_session(
            amount=balance,
            currency=invoice.currency,
            product_name=f"Invoice {invoice.number}",
            metadata={
                "invoice_id": str(invoice.id),
                "workspace_id": str(invoice.workspace_id),
            },
            customer_email=customer_email,
            success_url=f"{return_url}?payment=paid" if return_url else None,
            cancel_url=return_url,
        )
        invoice.stripe_checkout_session_id = result.session_id
        await self.db.commit()

        self.log.info(
            "invoice_payment_link_created",
            invoice_id=str(invoice.id),
            workspace_id=str(invoice.workspace_id),
            amount=balance,
            session_id=result.session_id,
        )
        return result.session_id, result.url

    # ----------------------------------------------------------------- #
    # Public customer invoice (no auth, token-keyed)
    # ----------------------------------------------------------------- #
    async def _load_by_public_token(self, token: str, *, for_update: bool = False) -> Invoice:
        """Load a sent invoice by its public token, or raise ``NotFoundError``.

        Drafts have no token and never resolve, so an invoice the operator is
        still editing cannot be viewed even if a link were guessed. Status is
        re-derived on read so an invoice that lapsed since it was sent reports
        ``overdue`` truthfully without waiting for a worker. Payment selection
        uses a row lock so concurrent requests cannot leave two differently
        priced Checkout Sessions open.
        """
        statement = (
            select(Invoice)
            .where(Invoice.public_token == token)
            .options(
                selectinload(Invoice.line_items),
                selectinload(Invoice.contact),
                selectinload(Invoice.workspace),
            )
        )
        if for_update:
            statement = statement.with_for_update()
        result = await self.db.execute(statement)
        invoice = result.scalar_one_or_none()
        if invoice is None or invoice.status == "draft":
            raise NotFoundError("Invoice not found")

        derived = self.derive_status(invoice)
        if derived != invoice.status:
            invoice.status = derived
            if for_update:
                await self.db.flush()
            else:
                await self.db.commit()
                await self.db.refresh(invoice, ["line_items"])
        return invoice

    def _to_public(self, invoice: Invoice) -> PublicInvoice:
        """Project an invoice onto its allowlisted public view."""
        from app.services.quotes.proposal_template import get_proposal_template

        template = get_proposal_template(invoice.workspace)
        business_name = template.business_name or (
            invoice.workspace.name if invoice.workspace else ""
        )
        client_name: str | None = None
        if invoice.contact is not None:
            client_name = invoice.contact.full_name or invoice.contact.first_name

        total = float(invoice.total or 0)
        paid = float(invoice.amount_paid or 0)
        balance = round(max(0.0, total - paid), 2)
        is_void = invoice.status == "void"
        is_paid = balance <= 0 and total > 0

        return PublicInvoice(
            token=invoice.public_token or "",
            number=invoice.number,
            status=invoice.status,  # type: ignore[arg-type]
            currency=invoice.currency,
            line_items=[
                PublicInvoiceLineItem(
                    id=li.id,
                    name=li.name,
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_price=float(li.unit_price),
                    discount=float(li.discount),
                    total=float(li.total),
                    is_optional=li.is_optional,
                    is_selected=li.is_selected,
                )
                for li in invoice.line_items
            ],
            subtotal=float(invoice.subtotal or 0),
            tax_amount=float(invoice.tax_amount or 0),
            discount_amount=float(invoice.discount_amount or 0),
            total=total,
            amount_paid=paid,
            balance_due=balance,
            issue_date=invoice.issue_date,
            due_date=invoice.due_date,
            is_paid=is_paid,
            is_void=is_void,
            is_overdue=invoice.status == "overdue",
            # Gated on Stripe too: a "Pay now" button that 503s the moment it is
            # pressed is worse than no button at all.
            is_payable=(
                balance > 0 and not is_void and call_payment_service.is_payment_configured()
            ),
            client_name=client_name,
            notes=invoice.notes,
            terms=invoice.terms,
            branding=PublicProposalBranding(
                business_name=business_name,
                logo_url=template.logo_url,
                brand_color=template.brand_color,
                accent_color=template.accent_color,
                business_address=template.business_address,
                business_phone=template.business_phone,
                business_email=template.business_email,
                footer=template.footer,
            ),
        )

    async def get_public_invoice(self, token: str) -> PublicInvoice:
        """Return the read-only, safe-fields-only invoice for a public token."""
        return self._to_public(await self._load_by_public_token(token))

    def _apply_recipient_selection(
        self,
        invoice: Invoice,
        selected_optional_line_item_ids: list[uuid.UUID],
    ) -> None:
        """Validate and apply optional-row choices before server-side pricing."""
        optional_ids = {line_item.id for line_item in invoice.line_items if line_item.is_optional}
        selected_ids = set(selected_optional_line_item_ids)
        if not selected_ids.issubset(optional_ids):
            raise ValidationError("Selected line items must be optional items on this invoice")

        for line_item in invoice.line_items:
            line_item.is_selected = not line_item.is_optional or line_item.id in selected_ids
        self._recompute_totals(invoice)

    async def create_public_payment_checkout(
        self,
        token: str,
        selected_optional_line_item_ids: list[uuid.UUID] | None = None,
    ) -> PublicInvoicePaymentCheckout:
        """Validate recipient choices and charge the resulting server-priced balance."""
        invoice = await self._load_by_public_token(token, for_update=True)
        selection_changed = selected_optional_line_item_ids is not None
        if selection_changed:
            self._apply_recipient_selection(invoice, selected_optional_line_item_ids or [])
        else:
            self._recompute_totals(invoice)

        balance = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
        if balance <= 0:
            await self._commit_edit(invoice, checkout_affecting=selection_changed)
            raise ConflictError("Invoice has no outstanding balance")

        return_url = f"{settings.frontend_url}/p/invoices/{token}"
        _, url = await self._start_checkout(invoice, return_url=return_url)
        if not url:
            raise ServiceUnavailableError("Could not start the payment")
        return PublicInvoicePaymentCheckout(url=url, amount=balance, currency=invoice.currency)

    async def reconcile_public_payment(self, token: str) -> PublicInvoicePaymentStatus:
        """Reconcile an invoice against Stripe on return from checkout.

        A webhook backstop, mirroring the proposal deposit flow: when the
        customer lands back on their invoice we ask Stripe about the stored
        session and record the payment if Stripe confirms it, so a delayed or
        dropped webhook never leaves a paid invoice reading unpaid. Idempotent
        (``record_payment`` dedupes on the payment-intent id) and never raises
        for a normal "not paid yet".
        """
        invoice = await self._load_by_public_token(token)
        total = float(invoice.total or 0)
        paid = float(invoice.amount_paid or 0)
        balance = round(max(0.0, total - paid), 2)

        session_id = invoice.stripe_checkout_session_id
        if balance > 0 and session_id and call_payment_service.is_payment_configured():
            try:
                status = await call_payment_service.retrieve_session_status(session_id)
            except Exception as exc:  # pragma: no cover - Stripe/network best-effort
                self.log.warning(
                    "invoice_payment_reconcile_failed",
                    invoice_id=str(invoice.id),
                    error=str(exc),
                )
            else:
                if status.payment_status == "paid":
                    await self.record_payment(
                        invoice,
                        balance,
                        payment_intent_id=status.payment_intent_id,
                        checkout_session_id=session_id,
                    )
                    paid = float(invoice.amount_paid or 0)
                    balance = round(max(0.0, total - paid), 2)

        return PublicInvoicePaymentStatus(
            is_paid=balance <= 0 and total > 0,
            amount_paid=paid,
            balance_due=balance,
            currency=invoice.currency,
        )


async def handle_invoice_checkout_session_completed(
    session: dict[str, Any],
    db: AsyncSession,
) -> None:
    """Reconcile a Stripe ``checkout.session.completed`` event for an invoice.

    Resolves the invoice from ``metadata.invoice_id`` (or the stored checkout
    session id) and records the collected amount. Idempotent via
    :meth:`InvoiceService.record_payment`, so Stripe retries are safe.
    """
    metadata = session.get("metadata") or {}
    invoice_id_raw = metadata.get("invoice_id")
    session_id = session.get("id")

    invoice: Invoice | None = None
    if invoice_id_raw:
        try:
            invoice = await db.get(Invoice, uuid.UUID(invoice_id_raw))
        except ValueError:
            invoice = None
    if invoice is None and session_id:
        result = await db.execute(
            select(Invoice).where(Invoice.stripe_checkout_session_id == session_id)
        )
        invoice = result.scalar_one_or_none()

    if invoice is None:
        logger.warning(
            "invoice_webhook_no_match",
            invoice_id=invoice_id_raw,
            session_id=session_id,
        )
        return

    payment_intent = session.get("payment_intent")
    payment_intent_id = payment_intent if isinstance(payment_intent, str) else None

    amount_total = session.get("amount_total")
    if amount_total is None:
        # Fall back to the outstanding balance if Stripe omitted the amount.
        amount = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
    else:
        amount = call_payment_service.from_minor_units(int(amount_total), invoice.currency)

    service = InvoiceService(db)
    await service.record_payment(
        invoice,
        amount,
        payment_intent_id=payment_intent_id,
        checkout_session_id=session_id if isinstance(session_id, str) else None,
    )
