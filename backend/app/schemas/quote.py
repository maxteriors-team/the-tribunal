"""Quote (estimate) schemas.

Mirrors :mod:`app.schemas.invoice` conventions (``float`` money fields,
``from_attributes`` responses). Server-computed fields (``number``, ``status``,
``subtotal``, ``total``, line ``total``, conversion ids) are response-only and
never accepted from clients.
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.schemas.attach_rules import AttachDismissal, AttachDismissalRequest, AttachWarning
from app.schemas.pricing import FinancingEstimate

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
    """Create a line item, optionally sourced from the price book.

    ``catalog_item_id`` is a *request-only* hint from the catalog picker: the
    server looks the item up within the workspace and snapshots its
    ``service_category`` onto the line. Nothing links back to the catalog row,
    so the metric survives the item later being re-categorized or deleted, and
    the category can't be forged by a client since it is never read from the
    request body. An id that no longer resolves simply leaves the line
    uncategorized.
    """

    catalog_item_id: uuid.UUID | None = None


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
    # Server-snapshotted from the picked catalog item; drives attach metrics.
    service_category: str | None = None
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
    # Set when the rep saw the attach prompt and chose to skip the add-on. Only
    # the reason crosses the wire; which categories were skipped is resolved
    # server-side from the rule that fired. Ignored when no rule fires, and
    # required (with a reason, when the workspace demands one) to save past a
    # ``blocking`` rule.
    attach_dismissal: AttachDismissalRequest | None = None


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
    # Category-qualified, server-computed estimate. Null means this quote's
    # categorized subtotal is disabled, below its minimum, or above the cap.
    financing: FinancingEstimate | None = None
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
    # Client-view tracking, written only by the public view beacon
    # (``POST /p/quotes/{token}/view``). Read-only here and absent from
    # ``QuoteCreate``/``QuoteUpdate`` on purpose: accepting these from a request
    # body would let a client forge "the customer opened it", which is the one
    # claim this whole signal exists to make honestly. ``view_count`` counts
    # throttled visits, not raw beacon hits.
    first_viewed_at: datetime | None = None
    last_viewed_at: datetime | None = None
    view_count: int = 0
    # Denormalized attach metrics, re-derived from the line items on every save.
    # Read-only: setting them from a request would let a client rewrite its own
    # attach rate. ``primary_service`` is null on an uncategorized quote.
    primary_service: str | None = None
    attach_count: int = 0
    attach_value: float = 0.0
    # Recorded dismissals of the attach prompt, oldest first. Server-written.
    attach_dismissals: list[AttachDismissal] = Field(default_factory=list)

    @field_validator("view_count", "attach_count", "attach_value", mode="before")
    @classmethod
    def _null_counter_is_zero(cls, value: object) -> object:
        """Read a null counter as zero.

        These columns are NOT NULL with a ``'0'`` server default, but a column
        default only lands on flush — an in-memory ``Quote`` that has not been
        inserted yet still reads ``None`` for every one of them. Serializing such
        a quote is legitimate (the approve path does it with the object it just
        mutated), and "nothing counted yet" is the truthful answer, so coerce
        rather than 500 on a response the caller did nothing wrong to ask for.

        A pydantic field default does **not** cover this: a default applies when
        the attribute is *missing*, not when it is present and null.
        """
        return 0 if value is None else value

    @field_validator("attach_dismissals", mode="before")
    @classmethod
    def _empty_dismissals(cls, value: object) -> object:
        """Read a null dismissal list as an empty one.

        Same flush-timing reason as :meth:`_null_counter_is_zero`; the column is
        NOT NULL with a ``'[]'`` server default, and "nobody dismissed anything"
        is the truthful reading of an uninserted row.
        """
        return [] if value is None else value

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
    # The cross-sell prompt this save earned, when an advisory attach rule
    # matched and nothing was attached. Transient: computed per save from the
    # workspace's attach-rule config, never stored on the quote and therefore
    # always null on a plain read. Null also means "nothing to ask" — a blocking
    # rule never returns here because it rejects the save instead.
    attach_warning: AttachWarning | None = None


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
