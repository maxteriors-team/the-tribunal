"""Quote (estimate) schemas.

Mirrors :mod:`app.schemas.invoice` conventions (``float`` money fields,
``from_attributes`` responses). Server-computed fields (``number``, ``status``,
``subtotal``, ``total``, line ``total``, conversion ids) are response-only and
never accepted from clients.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

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
    # Optional upfront deposit. Set at most one: ``deposit_percentage`` (0-100 of
    # the total) or ``deposit_amount_fixed`` (a flat amount in major units). Null
    # on both = no deposit requested. A fixed amount wins if both are supplied.
    deposit_percentage: float | None = Field(default=None, ge=0, le=100)
    deposit_amount_fixed: float | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None
    terms: str | None = None

    @model_validator(mode="after")
    def _one_deposit_mode(self) -> "QuoteBase":
        if self.deposit_percentage is not None and self.deposit_amount_fixed is not None:
            raise ValueError("Set only one of deposit_percentage or deposit_amount_fixed")
        return self


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
    deposit_percentage: float | None = Field(default=None, ge=0, le=100)
    deposit_amount_fixed: float | None = Field(default=None, ge=0)
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None
    terms: str | None = None

    @model_validator(mode="after")
    def _one_deposit_mode(self) -> "QuoteUpdate":
        if self.deposit_percentage is not None and self.deposit_amount_fixed is not None:
            raise ValueError("Set only one of deposit_percentage or deposit_amount_fixed")
        return self


class QuoteDeclineRequest(BaseModel):
    """Operator decline with an optional reason."""

    reason: str | None = Field(default=None, max_length=2000)


class QuoteDeliverRequest(BaseModel):
    """Send the client proposal link by email or SMS.

    ``to`` overrides the destination; otherwise the wizard snapshot's client
    email/phone is used, falling back to the linked contact's.
    """

    channel: Literal["email", "sms"]
    to: str | None = Field(default=None, max_length=320)


class QuoteDeliverResult(BaseModel):
    """Outcome of a proposal delivery attempt."""

    ok: bool
    channel: Literal["email", "sms"]
    to: str


class QuoteConvertRequest(BaseModel):
    """Choose what an approved quote converts into. Defaults to both.

    An optional ``scheduled_start``/``scheduled_end`` window schedules the created
    job on the calendar in one step; omit both to land the job unscheduled.
    """

    create_job: bool = True
    create_invoice: bool = True
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None

    @model_validator(mode="after")
    def _check_window(self) -> "QuoteConvertRequest":
        start, end = self.scheduled_start, self.scheduled_end
        if (start is None) != (end is None):
            raise ValueError("scheduled_start and scheduled_end must be provided together")
        if start is not None and end is not None and end <= start:
            raise ValueError("scheduled_end must be after scheduled_start")
        return self


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
    deposit_percentage: float | None = None
    deposit_amount_fixed: float | None = None
    deposit_paid_at: datetime | None = None
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deposit_amount(self) -> float | None:
        """Effective deposit in major units (fixed wins, clamped to total)."""
        if self.deposit_amount_fixed is not None:
            amount = float(self.deposit_amount_fixed)
            if amount <= 0:
                return None
            return round(min(amount, self.total), 2) if self.total > 0 else round(amount, 2)
        if self.deposit_percentage is not None and self.deposit_percentage > 0:
            return round(self.total * float(self.deposit_percentage) / 100, 2)
        return None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deposit_required(self) -> bool:
        """True when a deposit is owed and not yet paid."""
        return self.deposit_amount is not None and self.deposit_paid_at is None

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
