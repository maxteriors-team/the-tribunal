"""Invoice schemas.

Mirrors :mod:`app.schemas.opportunity` conventions (``float`` money fields,
``from_attributes`` responses). Server-computed fields (``number``, ``status``,
``subtotal``, ``total``, ``amount_paid``, line ``total``) are response-only and
never accepted from clients.
"""

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.proposal import PublicProposalBranding

InvoiceStatus = Literal["draft", "sent", "paid", "partial", "void", "overdue"]


# --------------------------------------------------------------------------- #
# Line items
# --------------------------------------------------------------------------- #
class InvoiceLineItemBase(BaseModel):
    """Shared line-item fields."""

    name: str
    description: str | None = None
    quantity: float = Field(default=1.0, ge=0)
    unit_price: float = Field(ge=0)
    discount: float = Field(default=0.0, ge=0)


class InvoiceLineItemCreate(InvoiceLineItemBase):
    """Create a line item."""


class InvoiceLineItemUpdate(BaseModel):
    """Update a line item (all fields optional)."""

    name: str | None = None
    description: str | None = None
    quantity: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    discount: float | None = Field(default=None, ge=0)


class InvoiceLineItemResponse(InvoiceLineItemBase):
    """Line item as returned by the API."""

    id: uuid.UUID
    invoice_id: uuid.UUID
    total: float  # server-computed: quantity * unit_price - discount
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Invoice
# --------------------------------------------------------------------------- #
class InvoiceBase(BaseModel):
    """Client-settable invoice fields."""

    contact_id: int | None = None
    opportunity_id: uuid.UUID | None = None
    currency: str = "USD"
    tax_amount: float = Field(default=0.0, ge=0)
    discount_amount: float = Field(default=0.0, ge=0)
    issue_date: date | None = None
    due_date: date | None = None
    notes: str | None = None
    terms: str | None = None


class InvoiceCreate(InvoiceBase):
    """Create an invoice with its initial line items."""

    line_items: list[InvoiceLineItemCreate] = Field(default_factory=list)


class InvoiceUpdate(BaseModel):
    """Update invoice header fields (all optional); ``status``/``number``/totals
    are server-derived.

    ``line_items`` optionally **replaces the whole set** in the same transaction.
    An editor that reorders, edits, and deletes rows in one save would otherwise
    have to fan out across the per-item sub-resource endpoints, where a failure
    halfway through leaves a financial record in a state neither the operator nor
    the customer asked for. Omit the field to leave line items untouched; the
    per-item endpoints remain for incremental edits.
    """

    contact_id: int | None = None
    opportunity_id: uuid.UUID | None = None
    currency: str | None = None
    tax_amount: float | None = Field(default=None, ge=0)
    discount_amount: float | None = Field(default=None, ge=0)
    issue_date: date | None = None
    due_date: date | None = None
    notes: str | None = None
    terms: str | None = None
    line_items: list[InvoiceLineItemCreate] | None = None


class InvoiceResponse(BaseModel):
    """Invoice header as returned by list endpoints."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int | None = None
    opportunity_id: uuid.UUID | None = None
    number: str
    status: InvoiceStatus
    subtotal: float
    tax_amount: float
    discount_amount: float
    total: float
    amount_paid: float
    currency: str
    issue_date: date | None = None
    due_date: date | None = None
    sent_at: datetime | None = None
    paid_at: datetime | None = None
    notes: str | None = None
    terms: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InvoiceDetailResponse(InvoiceResponse):
    """Invoice with its line items."""

    line_items: list[InvoiceLineItemResponse] = Field(default_factory=list)


# How a send actually went. ``skipped_no_email`` is the common miss: an invoice
# with no bill-to contact (or a contact with no email on file) can be marked sent
# yet reach nobody, so the operator has to be told rather than shown a success.
InvoiceDeliveryStatus = Literal["emailed", "skipped_no_email", "failed"]


class InvoiceDeliverRequest(BaseModel):
    """Send the customer's invoice link by email or SMS.

    ``to`` overrides the destination; otherwise the bill-to contact's email or
    phone is used. Mirrors ``QuoteDeliverRequest`` so both customer-facing
    surfaces are driven the same way.
    """

    channel: Literal["email", "sms"]
    to: str | None = Field(default=None, max_length=320)


class InvoiceDeliverResult(BaseModel):
    """Outcome of an invoice delivery attempt.

    Unlike the bulk ``/send``, a failed delivery here surfaces as an error rather
    than a status field: the operator picked a channel and a recipient, so a miss
    is actionable, not informational.
    """

    ok: bool
    channel: Literal["email", "sms"]
    to: str


class InvoiceSendResponse(InvoiceDetailResponse):
    """Invoice after a send, plus whether the customer was actually emailed.

    Extends the detail response so callers keep every invoice field; ``delivery``
    is what lets the UI warn instead of claiming a delivery that never happened.
    """

    delivery: InvoiceDeliveryStatus
    # Address the invoice reached, when it reached anywhere. Echoed back so the
    # operator can confirm *who* received it.
    delivered_to: str | None = None


class PaginatedInvoices(BaseModel):
    """Paginated list of invoices."""

    items: list[InvoiceResponse]
    total: int
    page: int
    page_size: int
    pages: int


class InvoicePaymentLinkResponse(BaseModel):
    """Stripe Checkout link for collecting an invoice's outstanding balance."""

    session_id: str
    url: str | None


# --------------------------------------------------------------------------- #
# Public customer invoice (no auth, token-keyed)
# --------------------------------------------------------------------------- #
class PublicInvoiceLineItem(BaseModel):
    """One billable line as the customer sees it."""

    name: str
    description: str | None = None
    quantity: float
    unit_price: float
    discount: float
    total: float


class PublicInvoice(BaseModel):
    """Read-only, allowlisted view of an invoice for its public page.

    Deliberately **not** derived from ``InvoiceResponse``: this crosses an
    unauthenticated boundary, so fields are listed explicitly rather than
    inherited. Internal provenance (``workspace_id``, ``contact_id``,
    ``opportunity_id``, ``created_by_id``, Stripe handles, ``external_*``) is
    absent by construction -- a future column added to the model cannot leak
    here by default.
    """

    token: str
    number: str
    status: InvoiceStatus
    currency: str

    line_items: list[PublicInvoiceLineItem] = Field(default_factory=list)
    subtotal: float
    tax_amount: float
    discount_amount: float
    total: float
    # What has already been collected (a paid quote deposit lands here) and what
    # is still owed. ``balance_due`` is server-computed so the page and the
    # Stripe charge can never disagree about the amount.
    amount_paid: float
    balance_due: float

    issue_date: date | None = None
    due_date: date | None = None
    is_paid: bool
    is_void: bool
    is_overdue: bool
    # Whether a payment can be started right now: something is owed, the invoice
    # is live, and Stripe is configured for this deployment.
    is_payable: bool

    client_name: str | None = None
    notes: str | None = None
    terms: str | None = None

    branding: PublicProposalBranding


class PublicInvoicePaymentCheckout(BaseModel):
    """Hosted Stripe payment URL for the customer to pay their balance."""

    url: str
    amount: float
    currency: str


class PublicInvoicePaymentStatus(BaseModel):
    """Reconciled payment state, polled on return from Stripe Checkout."""

    is_paid: bool
    amount_paid: float
    balance_due: float
    currency: str
