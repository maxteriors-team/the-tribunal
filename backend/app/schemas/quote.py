"""Quote (estimate) schemas.

Mirrors :mod:`app.schemas.invoice` conventions (``float`` money fields,
``from_attributes`` responses). Server-computed fields (``number``, ``status``,
``subtotal``, ``total``, line ``total``, conversion ids) are response-only and
never accepted from clients.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
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
from app.schemas.pricing import FinancingEstimate, PermanentKitSelection
from app.schemas.proposal_wizard import ProposalWizardPayload
from app.schemas.user import AssigneeSummary

QuoteStatus = Literal["draft", "sent", "approved", "declined", "expired"]
QuotePaymentOption = Literal["cash_check", "financing"]
WizardEditMode = Literal["update", "revise"]
DepositPaymentMethod = Literal["card", "cash", "check", "other"]
ManualDepositPaymentMethod = Literal["cash", "check", "other"]


class PermanentPricingSnapshot(BaseModel):
    """Private, immutable-at-approval Permanent Lighting economics."""

    model_config = ConfigDict(extra="forbid")

    cash_check_price: Decimal = Field(ge=0, decimal_places=2)
    financing_price: Decimal = Field(ge=0, decimal_places=2)
    provider: Literal["GreenSky"] = "GreenSky"
    plan_number: str = Field(min_length=1, max_length=32, pattern=r"^\d+$")
    apr: Decimal = Field(ge=0, le=1)
    term_months: int = Field(ge=1, le=360)
    merchant_fee_rate: Decimal = Field(ge=0, lt=1)
    sales_commission_rate: Decimal = Field(ge=0, lt=1)
    material_cogs: Decimal = Field(ge=0, decimal_places=2)

    @model_validator(mode="after")
    def one_customer_price(self) -> "PermanentPricingSnapshot":
        if self.cash_check_price != self.financing_price:
            raise ValueError("Cash/check and financing prices must match")
        return self


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
    lighting_project_id: uuid.UUID | None = None
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


# --------------------------------------------------------------------------- #
# Services (post-save adds)
# --------------------------------------------------------------------------- #
class QuoteServiceCreate(BaseModel):
    """Add one service to a quote that already exists.

    Deliberately amount-only, with no quantity. A quote built by the sales wizard
    stores its money in ``proposal_document`` and only *derives* line items from
    it, so an added service has to persist as a
    :class:`~app.schemas.proposal_wizard.ProposalCharge` to survive the client
    switching packages (which rebuilds every line from the document). A charge
    carries an amount and no quantity, and offering a quantity that the wizard
    shape cannot keep would be a field that silently collapses to 1 on most
    quotes.

    ``amount`` is the customer selling price on every quote. Wizard snapshots keep
    it as a direct add-on charge, matching the amount entered by the operator.
    """

    name: str = Field(min_length=1, max_length=300)
    amount: float = Field(gt=0)
    # Price-book provenance so the resulting quote line snapshots the item's
    # service category and the add registers as an attach. A request-only hint,
    # resolved within the workspace; an id that no longer resolves is ignored.
    catalog_item_id: uuid.UUID | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned


class QuoteServiceResponse(BaseModel):
    """One operator-added service, in a shape that hides where it is stored.

    A quote keeps added services in one of two places depending on how it was
    built: a document charge for wizard quotes, a line item for plain ones. That
    split is a persistence detail rather than something a caller should branch
    on, so both project into this one shape, and ``id`` is whatever the delete
    endpoint needs in order to remove it.
    """

    id: str
    name: str
    description: str | None = None
    amount: float


class QuoteAssignmentRequest(BaseModel):
    """Reassign or clear a quote's sales owner independently of quote content."""

    assigned_user_id: int | None


class QuoteDeclineRequest(BaseModel):
    """Operator decline with an optional reason."""

    reason: str | None = Field(default=None, max_length=2000)


class QuoteApproveRequest(BaseModel):
    """Operator approval; Permanent snapshots require one server-validated method."""

    model_config = ConfigDict(extra="forbid")

    payment_option: QuotePaymentOption | None = None


class QuoteDepositRecordRequest(BaseModel):
    """Record money already received outside the online card flow.

    ``card`` is deliberately excluded: only Stripe confirmation can attest that
    an online card transaction completed.
    """

    payment_method: ManualDepositPaymentMethod


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

    Explicit unpaid confirmation never changes provider-derived payment truth.
    """

    create_job: bool = True
    create_invoice: bool = True
    scheduled_start: datetime | None = None
    scheduled_end: datetime | None = None
    crew_id: uuid.UUID | None = None
    technician_ids: list[uuid.UUID] = Field(default_factory=list)
    confirm_unpaid_deposit: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> "QuoteConvertRequest":
        start, end = self.scheduled_start, self.scheduled_end
        if (start is None) != (end is None):
            raise ValueError("scheduled_start and scheduled_end must be provided together")
        if start is not None and end is not None and end <= start:
            raise ValueError("scheduled_end must be after scheduled_start")
        if not self.create_job and (start is not None or self.crew_id or self.technician_ids):
            raise ValueError("schedule and installation team require create_job")
        return self


CrewNotificationStatus = Literal["sent", "partial", "not_applicable", "failed"]


class CrewNotificationResult(BaseModel):
    """Post-commit assignment delivery; never payment/job transaction state."""

    status: CrewNotificationStatus = "not_applicable"
    recipient_count: int = Field(default=0, ge=0)
    sent_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)


class QuoteResponse(BaseModel):
    """Quote header as returned by list endpoints."""

    id: uuid.UUID
    workspace_id: uuid.UUID
    contact_id: int | None = None
    service_location_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    assigned_user_id: int | None = None
    assignee: AssigneeSummary | None = None
    # Authenticated linkage only. PublicProposal has no corresponding fields.
    lighting_project_id: uuid.UUID | None = None
    revision_of_quote_id: uuid.UUID | None = None
    revision_root_quote_id: uuid.UUID | None = None
    revision_number: int = Field(default=1, ge=1)
    proposal_version: int = Field(default=1, ge=1)
    is_wizard_quote: bool = False
    wizard_edit_mode: WizardEditMode | None = None
    number: str
    title: str | None = None
    status: QuoteStatus
    payment_option: QuotePaymentOption | None = None
    subtotal: float
    tax_amount: float
    discount_amount: float
    total: float
    currency: str
    # Server-computed only for newly snapshotted exact Permanent Lighting quotes.
    financing: FinancingEstimate | None = None
    deposit_percentage: float | None = None
    deposit_amount_fixed: float | None = None
    deposit_paid_at: datetime | None = None
    deposit_payment_method: DepositPaymentMethod | None = None
    deposit_recorded_by_id: int | None = None
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
    # Server-priced procurement metadata. Intentionally absent from create/update
    # request schemas so clients cannot forge which kits were selected.
    selected_permanent_kits: list[PermanentKitSelection] = Field(default_factory=list)

    @field_validator("revision_number", "proposal_version", mode="before")
    @classmethod
    def _null_version_is_one(cls, value: object) -> object:
        return 1 if value is None else value

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

    @field_validator("attach_dismissals", "selected_permanent_kits", mode="before")
    @classmethod
    def _empty_defaulted_lists(cls, value: object) -> object:
        """Read a null JSON list as empty before SQLAlchemy defaults land.

        These columns are NOT NULL with ``'[]'`` server defaults; an unflushed
        ORM object still exposes ``None``, where an empty list is the truthful
        value.
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def deposit_paid(self) -> bool:
        """Provider-confirmed card payment or authenticated offline record."""
        return self.deposit_paid_at is not None

    model_config = ConfigDict(from_attributes=True)


class PermanentProfitabilityScenario(BaseModel):
    """Private economics for one Permanent Lighting payment method."""

    payment_option: QuotePaymentOption
    contract_price: float
    merchant_fee_rate: float
    merchant_fee: float
    sales_commission_rate: float
    sales_commission: float
    material_cogs: float
    contribution_before_labor: float
    contribution_margin: float


class PermanentProfitabilityResponse(BaseModel):
    """Billing-scoped comparison computed only from the quote's private snapshot."""

    quote_id: uuid.UUID
    currency: str
    provider: str
    plan_number: str
    apr: float
    term_months: int
    estimated_monthly_payment: float
    selected_payment_option: QuotePaymentOption | None = None
    cash_check: PermanentProfitabilityScenario
    financing: PermanentProfitabilityScenario


class QuoteDetailResponse(QuoteResponse):
    """Quote with its line items and (when built by the wizard) its rich snapshot."""

    line_items: list[QuoteLineItemResponse] = Field(default_factory=list)
    # Services an operator may add to or remove from this quote, already resolved
    # to one shape across both persistences (see :class:`QuoteServiceResponse`).
    # On a wizard quote this is the document's add-on charges, *not* its fixture
    # lines: a fixture is priced by the tier and can only be changed by rebuilding
    # the design, so offering it here would promise an edit the server refuses.
    services: list[QuoteServiceResponse] = Field(default_factory=list)
    # Multi-tier sales-wizard snapshot; null for quotes created outside the wizard.
    proposal_document: dict[str, Any] | None = None
    # Exact validated builder input. Staff-only; public proposal responses expose
    # only the safe rendered document and never this contact-rich hydration state.
    proposal_input: ProposalWizardPayload | None = None
    proposal_input_version: int | None = None
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
    """Authoritative conversion links plus best-effort crew delivery."""

    quote: QuoteDetailResponse
    job_id: uuid.UUID | None = None
    invoice_id: uuid.UUID | None = None
    idempotent_replay: bool = False
    crew_notification: CrewNotificationResult = Field(default_factory=CrewNotificationResult)
