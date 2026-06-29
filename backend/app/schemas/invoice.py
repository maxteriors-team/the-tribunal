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
    """Update invoice header fields (all optional). Line items have their own
    sub-resource endpoints; ``status``/``number``/totals are server-derived."""

    contact_id: int | None = None
    opportunity_id: uuid.UUID | None = None
    currency: str | None = None
    tax_amount: float | None = Field(default=None, ge=0)
    discount_amount: float | None = Field(default=None, ge=0)
    issue_date: date | None = None
    due_date: date | None = None
    notes: str | None = None
    terms: str | None = None


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


class PaginatedInvoices(BaseModel):
    """Paginated list of invoices."""

    items: list[InvoiceResponse]
    total: int
    page: int
    page_size: int
    pages: int
