"""Quote (estimate) schemas.

Mirrors :mod:`app.schemas.invoice` conventions (``float`` money fields,
``from_attributes`` responses). Server-computed fields (``number``, ``status``,
``subtotal``, ``total``, line ``total``, conversion ids) are response-only and
never accepted from clients.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

QuoteStatus = Literal["draft", "sent", "approved", "declined", "expired"]


# --------------------------------------------------------------------------- #
# Line items
# --------------------------------------------------------------------------- #
class QuoteLineItemBase(BaseModel):
    """Shared line-item fields."""

    name: str
    description: str | None = None
    quantity: float = Field(default=1.0, ge=0)
    unit_price: float = Field(ge=0)
    discount: float = Field(default=0.0, ge=0)


class QuoteLineItemCreate(QuoteLineItemBase):
    """Create a line item."""


class QuoteLineItemUpdate(BaseModel):
    """Update a line item (all fields optional)."""

    name: str | None = None
    description: str | None = None
    quantity: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    discount: float | None = Field(default=None, ge=0)


class QuoteLineItemResponse(QuoteLineItemBase):
    """Line item as returned by the API."""

    id: uuid.UUID
    quote_id: uuid.UUID
    total: float  # server-computed: quantity * unit_price - discount
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Quote
# --------------------------------------------------------------------------- #
class QuoteBase(BaseModel):
    """Client-settable quote fields."""

    contact_id: int | None = None
    service_location_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    currency: str = "USD"
    tax_amount: float = Field(default=0.0, ge=0)
    discount_amount: float = Field(default=0.0, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None
    terms: str | None = None


class QuoteCreate(QuoteBase):
    """Create a quote with its initial line items."""

    line_items: list[QuoteLineItemCreate] = Field(default_factory=list)


class QuoteUpdate(BaseModel):
    """Update quote header fields (all optional). Line items have their own
    sub-resource endpoints; ``status``/``number``/totals are server-derived."""

    contact_id: int | None = None
    service_location_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    title: str | None = Field(default=None, max_length=200)
    currency: str | None = None
    tax_amount: float | None = Field(default=None, ge=0)
    discount_amount: float | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None
    terms: str | None = None


class QuoteDeclineRequest(BaseModel):
    """Operator decline with an optional reason."""

    reason: str | None = Field(default=None, max_length=2000)


class QuoteConvertRequest(BaseModel):
    """Choose what an approved quote converts into. Defaults to both."""

    create_job: bool = True
    create_invoice: bool = True


class QuoteResponse(BaseModel):
    """Quote header as returned by list endpoints."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int | None = None
    service_location_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    number: str
    title: str | None = None
    status: QuoteStatus
    subtotal: float
    tax_amount: float
    discount_amount: float
    total: float
    currency: str
    issue_date: date | None = None
    expiry_date: date | None = None
    sent_at: datetime | None = None
    approved_at: datetime | None = None
    declined_at: datetime | None = None
    decline_reason: str | None = None
    notes: str | None = None
    terms: str | None = None
    converted_job_id: uuid.UUID | None = None
    converted_invoice_id: uuid.UUID | None = None
    # Public client-proposal token (staff-only field; null until first sent). The
    # dashboard uses it to build/copy the client-facing proposal link.
    public_token: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class QuoteDetailResponse(QuoteResponse):
    """Quote with its line items and (when built by the wizard) its rich snapshot."""

    line_items: list[QuoteLineItemResponse] = Field(default_factory=list)
    # Multi-tier sales-wizard snapshot; null for quotes created outside the wizard.
    proposal_document: dict[str, Any] | None = None


class PaginatedQuotes(BaseModel):
    """Paginated list of quotes."""

    items: list[QuoteResponse]
    total: int
    page: int
    page_size: int
    pages: int


class QuoteConvertResponse(BaseModel):
    """Result of converting an approved quote into a job and/or an invoice."""

    quote: QuoteDetailResponse
    job_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
