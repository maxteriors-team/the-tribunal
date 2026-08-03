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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404, get_or_404
from app.core.config import settings
from app.db.pagination import paginate
from app.db.scope import assert_workspace_owned
from app.models.contact import Contact
from app.models.invoice import Invoice, InvoiceLineItem, generate_invoice_token
from app.models.opportunity import Opportunity
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceDeliverResult,
    InvoiceDeliveryStatus,
    InvoiceDetailResponse,
    InvoiceLineItemCreate,
    InvoiceLineItemUpdate,
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
from app.services.payments import call_payment_service

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
        amount_paid: float = 0.0,
        payment_intent_id: str | None = None,
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
                )
            )

        # Totals first: the opening credit clamps against the computed total.
        self._recompute_totals(invoice)
        opening_credit = round(max(0.0, min(float(amount_paid), float(invoice.total or 0))), 2)
        if opening_credit > 0:
            invoice.amount_paid = opening_credit
            invoice.status = self.derive_status(invoice)
            if invoice.status == "paid":
                invoice.paid_at = datetime.now(UTC)
        self.db.add(invoice)
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

        await self._validate_refs(
            workspace_id,
            contact_id=invoice_in.contact_id,
            opportunity_id=invoice_in.opportunity_id,
        )

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

        if invoice_in.line_items is not None:
            # Same rule as the per-item endpoints (``_get_mutable_invoice``):
            # a settled invoice's lines are history, not a draft.
            if invoice.status in ("paid", "void"):
                raise ConflictError(f"Cannot edit line items on a {invoice.status} invoice")
            # Whole-set replacement inside this transaction, so a multi-row edit
            # can never half-apply. ``delete-orphan`` on the relationship removes
            # the dropped rows.
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
                    )
                )

        # tax/discount/line changes move the total, which can change paid/partial state.
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

    async def _load_for_send(self, workspace_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
        """Load an invoice with everything a delivery needs (items, contact, brand)."""
        return await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[
                selectinload(Invoice.line_items),
                selectinload(Invoice.contact),
                selectinload(Invoice.workspace),
            ],
        )

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
                },
            )
        await self.db.commit()
        await self.db.refresh(invoice, ["line_items"])

    async def mark_sent(
        self,
        workspace_id: uuid.UUID,
        invoice_id: uuid.UUID,
    ) -> InvoiceSendResponse:
        """Mark an invoice as sent (sets ``sent_at`` once), re-derive status, and
        email the invoice to the bill-to contact.

        Emailing stays best-effort -- a bounce must not undo the ``sent``
        transition -- but the outcome is *reported* rather than swallowed, so an
        operator is never told a contactless invoice reached the customer.
        """
        invoice = await self._load_for_send(workspace_id, invoice_id)
        await self._transition_to_sent(workspace_id, invoice)

        delivery, delivered_to = await self._email_invoice(workspace_id, invoice)
        detail = InvoiceDetailResponse.model_validate(invoice)
        return InvoiceSendResponse(
            **detail.model_dump(),
            delivery=delivery,
            delivered_to=delivered_to,
        )

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
        from app.services.idempotency import derive_outbound_key

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
                idempotency_key=derive_outbound_key("invoice_send", invoice.id),
            )
        except Exception as exc:  # pragma: no cover - best-effort email
            self.log.warning("invoice_email_failed", invoice_id=str(invoice.id), error=str(exc))
            return "failed", None

        # ``send_invoice_email`` returns True only when the provider accepted it,
        # so a False here (unconfigured provider, rejected send) is a real miss.
        if not accepted:
            self.log.warning("invoice_email_not_accepted", invoice_id=str(invoice.id))
            return "failed", None
        return "emailed", contact_email

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

        was_paid = invoice.status == "paid"
        invoice.amount_paid = round(float(invoice.amount_paid or 0) + float(amount), 2)
        if payment_intent_id:
            invoice.stripe_payment_intent_id = payment_intent_id
        invoice.status = self.derive_status(invoice)
        if invoice.status == "paid":
            invoice.paid_at = datetime.now(UTC)
        # Fire once, on the transition into fully paid (not on partial payments
        # and not on a replay that leaves an already-paid invoice paid).
        if invoice.status == "paid" and not was_paid:
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
                },
            )
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
        invoice = await get_or_404(
            self.db,
            Invoice,
            invoice_id,
            workspace_id=workspace_id,
            options=[selectinload(Invoice.contact)],
        )
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
    async def _load_by_public_token(self, token: str) -> Invoice:
        """Load a sent invoice by its public token, or raise ``NotFoundError``.

        Drafts have no token and never resolve, so an invoice the operator is
        still editing cannot be viewed even if a link were guessed. Status is
        re-derived on read so an invoice that lapsed since it was sent reports
        ``overdue`` truthfully without waiting for a worker.
        """
        result = await self.db.execute(
            select(Invoice)
            .where(Invoice.public_token == token)
            .options(
                selectinload(Invoice.line_items),
                selectinload(Invoice.contact),
                selectinload(Invoice.workspace),
            )
        )
        invoice = result.scalar_one_or_none()
        if invoice is None or invoice.status == "draft":
            raise NotFoundError("Invoice not found")

        derived = self.derive_status(invoice)
        if derived != invoice.status:
            invoice.status = derived
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
                    name=li.name,
                    description=li.description,
                    quantity=float(li.quantity),
                    unit_price=float(li.unit_price),
                    discount=float(li.discount),
                    total=float(li.total),
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

    async def create_public_payment_checkout(self, token: str) -> PublicInvoicePaymentCheckout:
        """Start a Stripe Checkout Session so the customer can pay their balance.

        The amount is re-derived from the invoice server-side, so a customer
        cannot influence what they are charged by editing the request.
        """
        invoice = await self._load_by_public_token(token)
        return_url = f"{settings.frontend_url}/p/invoices/{token}"
        _, url = await self._start_checkout(invoice, return_url=return_url)
        if not url:
            raise ServiceUnavailableError("Could not start the payment")
        balance = round(float(invoice.total or 0) - float(invoice.amount_paid or 0), 2)
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
                        invoice, balance, payment_intent_id=status.payment_intent_id
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
    await service.record_payment(invoice, amount, payment_intent_id=payment_intent_id)
