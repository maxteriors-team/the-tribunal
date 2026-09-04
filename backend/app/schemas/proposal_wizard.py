"""Sales-wizard save/preview payloads and the computed proposal document.

The wizard collects a client, per-fixture quantities (referencing catalog items),
add-on charges, a chosen tier, a Care Plan pick, and optional bistro/night
preview. It POSTs that raw *selection* — never money. The server resolves catalog
prices, applies the workspace pricing config, and returns a fully-computed
:class:`ProposalDocument` (the snapshot stored on ``quote.proposal_document`` and
rendered by the public page). Client totals are never trusted.
"""

import uuid
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.attach_rules import AttachDismissalRequest, AttachWarning
from app.schemas.pricing import (
    BistroInstallation,
    BistroPricing,
    CarePlanPricing,
    CategoryLine,
    TierPricing,
    ValueProp,
)

# Product lines the unified builder can quote, in canonical display order.
CATEGORY_ORDER = ("landscape", "permanent", "bistro", "christmas")
MAX_PROPOSAL_MOCKUP_IMAGE_CHARS = 3_000_000

# The three service paths a quote can come from, each mapping to the product
# lines it owns. A quote is single-service in the rep experience: landscape
# lighting, year-round permanent LED track, and seasonal Christmas are separate
# branches, not toggles on one form.
SERVICE_CATEGORIES: dict[str, tuple[str, ...]] = {
    "landscape": ("landscape", "bistro"),
    "permanent": ("permanent",),
    "christmas": ("christmas",),
}


def service_for_categories(categories: Sequence[str]) -> str | None:
    """Which service path a set of product lines belongs to.

    Returns ``"landscape"`` | ``"permanent"`` | ``"christmas"`` for a
    single-service selection, ``"mixed"`` when the selection spans more than one
    service path, and ``None`` when nothing recognizable was selected (the legacy
    empty-categories payload, which the builder infers as landscape).
    """
    services = {
        service
        for service, lines in SERVICE_CATEGORIES.items()
        if any(category in lines for category in categories)
    }
    if not services:
        return None
    if len(services) > 1:
        return "mixed"
    return next(iter(services))


# --------------------------------------------------------------------------- #
# Input (raw selection from the wizard)
# --------------------------------------------------------------------------- #
class WizardClient(BaseModel):
    """Client + job-site details captured on the wizard's first step."""

    first_name: str | None = Field(default=None, max_length=120)
    last_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=50)
    street: str | None = Field(default=None, max_length=300)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=60)
    zip: str | None = Field(default=None, max_length=20)
    rep_name: str | None = Field(default=None, max_length=120)


class WizardCharge(BaseModel):
    """A custom add-on charge. The rep enters the *net* they want to keep; the
    server grosses it up by the finance buffer like every other price.

    ``tier_key`` optionally pins the charge to **one package**, mirroring
    ``EstimateCustomLine.package_key`` on the estimator side:

    * ``None`` (default) — rides on every tier, which is how this has always
      behaved and what an unset field asks for.
    * set — charged only when the client is buying that tier, so the core
      drilling the Premier install needs stops inflating the Starter.

    A key naming no tier in the document stays global rather than being dropped.
    The estimator can drop a scoped line because it is only ever a preview; this
    charge is money the rep typed on a quote they are about to send, and
    silently zeroing it is worse than charging it somewhere they can see it.
    """

    description: str | None = Field(default=None, max_length=300)
    net_amount: float = Field(default=0, ge=0)
    tier_key: str | None = Field(default=None, max_length=64)
    # Set when the charge came from the price book rather than being typed by
    # hand — the attach prompt's "Add gutters" action picks a catalog item, and
    # this is what lets the resulting quote line snapshot that item's
    # ``service_category`` so the attach actually registers. A request-only hint
    # resolved within the workspace; an id that no longer resolves leaves the
    # line uncategorized, exactly like a hand-typed charge.
    catalog_item_id: uuid.UUID | None = None


class WizardDepositSelection(BaseModel):
    """Optional upfront deposit the rep sets on the quote.

    ``mode`` picks how ``value`` is read: ``percentage`` (0-100 of the total) or
    ``fixed`` (a flat amount in major units). Omitting this object falls back to
    the workspace's default deposit config.
    """

    mode: Literal["percentage", "fixed"] = "percentage"
    value: float = Field(default=0, ge=0)


class WizardFixtureQty(BaseModel):
    """Quantity for one catalog item, keyed by its stable id (``sku`` or key)."""

    item_id: str = Field(min_length=1, max_length=120)
    quantity: float = Field(default=0, ge=0)


class WizardBistroRun(BaseModel):
    """Measured footage and explicitly marked support poles."""

    installation: BistroInstallation
    feet: float = Field(gt=0, le=100_000)
    pole_count: int = Field(default=0, ge=0, le=10_000)


class WizardBistroSelection(BaseModel):
    """Optional measured-run selection or compatible legacy product selection."""

    product: str = "color"  # "color" | "classic"
    tier: str = "easy"
    feet: float = Field(default=0, ge=0, le=100_000)
    runs: list[WizardBistroRun] = Field(default_factory=list, max_length=100)


class WizardPermanentSelection(BaseModel):
    """Permanent-holiday-lighting selection: roofline footage + zone count."""

    feet: float = Field(default=0, ge=0)
    channels: int = Field(default=0, ge=0)


class WizardCategoryCount(BaseModel):
    """A selected decor option: ``key`` -> value (quantity for ``each`` items,
    linear feet for ``per_ft`` items like garland)."""

    key: str = Field(min_length=1, max_length=60)
    quantity: float = Field(default=0, ge=0)


class WizardChristmasSelection(BaseModel):
    """Seasonal Christmas selection: roofline + decor items + takedown/storage.

    ``items`` maps a decor category key ("trees", "garland", …) to the selected
    options for that category, matching the standardized ``ChristmasConfig.items``
    catalog so any add-on is data, not a new field.

    When the workspace sells Christmas as Good/Better/Best packages
    (``ChristmasConfig.packages_enabled``), ``selected_package`` names the
    package the client picked; it is ignored in the à la carte flow and falls
    back server-side to the most inclusive priced package when unset or stale.
    """

    roofline_feet: float = Field(default=0, ge=0)
    items: dict[str, list[WizardCategoryCount]] = Field(default_factory=dict)
    takedown: bool = False
    storage: bool = False
    selected_package: str | None = None


class ProposalMockup(BaseModel):
    """A rep-uploaded design mockup shown in the proposal's visual gallery.

    ``image`` is a self-contained data URL (base64 JPEG/PNG/WebP) stored inline
    in the snapshot exactly like the night-preview image — this deployment has
    no object storage. The wizard resizes images client-side before upload, and
    the length cap is a defensive backstop against an oversized snapshot row.
    """

    image: str = Field(min_length=1, max_length=MAX_PROPOSAL_MOCKUP_IMAGE_CHARS)
    caption: str | None = Field(default=None, max_length=160)


def _clean_text(value: str | None) -> str | None:
    """Trim operator free text, treating a whitespace-only entry as absent."""
    cleaned = (value or "").strip()
    return cleaned or None


class ProposalNarrative(BaseModel):
    """Operator-authored project terms shown to the client.

    These are the fields the quote builder collects under "Design narrative":
    what the lighting is meant to do, who supplies line-voltage work, and any
    workmanship commitments. They were rendered as inputs but bound to nothing,
    so a rep could type them, save, and have them silently discarded.

    All values are plain operator free text and are escaped at render time; the
    length caps bound the snapshot row rather than validating meaning.
    """

    model_config = ConfigDict(from_attributes=True)

    design_intent: str | None = Field(default=None, max_length=2000)
    electrical_responsibility: str | None = Field(default=None, max_length=500)
    commitments: str | None = Field(default=None, max_length=2000)
    # The signatory the rep recorded. This is *not* proof the client signed:
    # consent of record is the client's own approve action on the public page,
    # which is timestamped server-side. Rendered as "prepared for", never as a
    # completed signature, so the page cannot assert consent nobody gave.
    signature_name: str | None = Field(default=None, max_length=120)
    signature_date: str | None = Field(default=None, max_length=40)

    @field_validator(
        "design_intent",
        "electrical_responsibility",
        "commitments",
        "signature_name",
        "signature_date",
        mode="after",
    )
    @classmethod
    def _blank_is_absent(cls, value: str | None) -> str | None:
        return _clean_text(value)

    @property
    def is_empty(self) -> bool:
        """True when nothing was filled in, so callers can store ``None``."""
        return not any(
            (
                self.design_intent,
                self.electrical_responsibility,
                self.commitments,
                self.signature_name,
                self.signature_date,
            )
        )


# One composited photo may not exceed this many characters of base64. Same cap
# as a rep-uploaded mockup: both are inline data URLs in the same snapshot row.
MAX_NIGHT_PREVIEW_IMAGE_CHARS = 3_000_000
# How many designed photos one night preview may carry. Mirrors ``MAX_SHOTS`` in
# the frontend designer; the client downloads every one of these on the public
# proposal link, so the ceiling is theirs as much as the database's.
MAX_NIGHT_PREVIEW_IMAGES = 6


def _validate_night_preview(value: dict[str, Any] | None) -> dict[str, Any] | None:
    """Bound the images inside the otherwise-opaque night-preview blob.

    The blob stays opaque on purpose (the drawing's shape is the frontend's
    business), but its images are not: a design can span several photos, each a
    full-size inline data URL, and they are served to the homeowner over the
    public link. Unbounded, one save could write a snapshot row big enough to
    make that page unloadable.

    Rejects rather than truncates. Silently dropping a photo the rep drew would
    ship a proposal the client sees as incomplete, with nothing to indicate why.
    """
    if value is None:
        return None

    images = value.get("images")
    if images is not None:
        if not isinstance(images, list):
            raise ValueError("night_preview.images must be a list of data URLs")
        if len(images) > MAX_NIGHT_PREVIEW_IMAGES:
            raise ValueError(
                f"night_preview.images holds at most {MAX_NIGHT_PREVIEW_IMAGES} "
                f"photos, got {len(images)}"
            )
        for index, image in enumerate(images):
            if not isinstance(image, str) or not image:
                raise ValueError(f"night_preview.images[{index}] must be a data URL")
            if len(image) > MAX_NIGHT_PREVIEW_IMAGE_CHARS:
                raise ValueError(
                    f"night_preview.images[{index}] exceeds "
                    f"{MAX_NIGHT_PREVIEW_IMAGE_CHARS} characters"
                )

    # The hero shot, carried on its own key for snapshots and readers that
    # predate multi-photo designs.
    hero = value.get("image")
    if hero is not None:
        if not isinstance(hero, str) or not hero:
            raise ValueError("night_preview.image must be a data URL")
        if len(hero) > MAX_NIGHT_PREVIEW_IMAGE_CHARS:
            raise ValueError(
                f"night_preview.image exceeds {MAX_NIGHT_PREVIEW_IMAGE_CHARS} characters"
            )

    return value


class ProposalWizardPayload(BaseModel):
    """Everything the authenticated wizard submits (selection only, no money)."""

    # Dedicated design tools can quote the workspace catalog price exactly, while
    # the general sales wizard retains its configured gross-up/cash/finance model.
    pricing_source: Literal["workspace_rules", "price_book"] = "workspace_rules"
    contact_id: int | None = None
    service_location_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    # Staff-only stable design link. It is deliberately omitted from the stored
    # proposal document and from every unauthenticated public response schema.
    lighting_project_id: uuid.UUID | None = None
    client: WizardClient | None = None
    quantities: list[WizardFixtureQty] = Field(default_factory=list)
    # Exact catalog products deliberately selected in the fixture schedule. They
    # are priced into every package instead of being replaced by tier defaults.
    fixed_items: list[WizardFixtureQty] = Field(default_factory=list, max_length=100)
    additional_charges: list[WizardCharge] = Field(default_factory=list)
    # Tier priced into the quote before it is sent.
    selected_tier: str | None = None
    # Existing proposals remain customer-selectable when this intent is absent.
    customer_can_select_package: bool = True
    care_plan_tier: str | None = None
    care_count_manual: int | None = Field(default=None, ge=0)
    bistro: WizardBistroSelection | None = None
    # Which product lines this quote includes. Empty => legacy landscape(+bistro)
    # inference so existing payloads keep working.
    categories: list[str] = Field(default_factory=list)
    permanent: WizardPermanentSelection | None = None
    christmas: WizardChristmasSelection | None = None
    # Opaque night-preview snapshot: the composited photos the rep designed
    # (``image`` is the hero shot, ``images`` the full set), plus light markers
    # and dusk level. Opaque except for the images, which are bounded below.
    night_preview: dict[str, Any] | None = None
    # Rep-uploaded design mockups rendered in the proposal's visual gallery.
    mockups: list[ProposalMockup] = Field(default_factory=list, max_length=8)
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    terms: str | None = None
    # Operator-authored project terms (design intent, electrical responsibility,
    # commitments, recorded signatory) shown on the client proposal page.
    narrative: ProposalNarrative | None = None
    # Optional upfront deposit; falls back to the workspace default when null.
    deposit: WizardDepositSelection | None = None
    # Set when the rep saw the attach prompt and chose to skip the add-on. Only
    # the reason crosses the wire; the skipped categories are resolved on the
    # server from the rule that fired. Required to save past a ``blocking`` rule.
    attach_dismissal: AttachDismissalRequest | None = None

    _check_night_preview = field_validator("night_preview")(_validate_night_preview)


# --------------------------------------------------------------------------- #
# Output (computed proposal document)
# --------------------------------------------------------------------------- #
class ProposalLine(BaseModel):
    """A priced fixture line within a tier (grossed-up unit price)."""

    item_id: str
    name: str
    unit_price: float
    quantity: float
    line_total: float
    transformer: bool = False


class ProposalTierView(BaseModel):
    """One tier's presentation copy + priced lines + computed money."""

    key: str
    label: str
    name: str | None = None
    experience: str | None = None
    warranty: str | None = None
    marker: str | None = None
    value_tag: str | None = None
    popular: bool = False
    points: list[str] = Field(default_factory=list)
    lines: list[ProposalLine] = Field(default_factory=list)
    pricing: TierPricing


class ProposalCharge(BaseModel):
    """A grossed-up add-on charge.

    On every tier unless ``tier_key`` pins it to one — see :class:`WizardCharge`
    for the rules. Snapshotted onto the document so re-selecting a tier reprices
    correctly without the original wizard payload.
    """

    # Stable handle for one charge within a document, so a service added after
    # the quote was saved can later be removed by name-independent id. Assigned
    # server-side at build time and backfilled onto older documents by
    # migration ``a7f3c21d9e04``; optional only so a snapshot written before
    # that still validates. Never read from a client request.
    id: str | None = None
    description: str
    amount: float
    tier_key: str | None = None
    # Price-book provenance, carried through so the saved quote line can snapshot
    # the item's service category. Null for a hand-typed charge.
    catalog_item_id: uuid.UUID | None = None


class ProposalCarePlan(BaseModel):
    """Care Plan block: fixture count + priced options + the client's pick."""

    fixture_count: int
    free_fixtures: int
    options: list[CarePlanPricing] = Field(default_factory=list)
    selected: str | None = None


class ProposalFinancing(BaseModel):
    """Financing copy echoed into the snapshot for the public page."""

    enabled: bool
    provider: str
    terms: list[int]
    default_term: int
    max_amount: float
    headline: str | None = None
    body: str | None = None
    points: list[str] = Field(default_factory=list)
    disclaimer: str | None = None


GREEN_SKY_APPLICATION_URL: Literal["https://projects.greensky.com/applyshort"] = (
    "https://projects.greensky.com/applyshort"
)
GREEN_SKY_APPLICATION_DISCLOSURE = (
    "Financing is subject to credit approval and the terms in your GreenSky loan "
    "documents. Applying does not accept this proposal, reserve an installation date, "
    "or guarantee approval. GreenSky Servicing, LLC is a financial technology company, "
    "not a lender. Program lenders determine credit approval and loan terms."
)


class ProposalGreenSky(BaseModel):
    """Public-safe snapshot of one configured GreenSky merchant program."""

    application_url: Literal["https://projects.greensky.com/applyshort"] = GREEN_SKY_APPLICATION_URL
    merchant_number: str = Field(pattern=r"^[0-9]+$", max_length=32)
    plan_number: str = Field(pattern=r"^[0-9]+$", max_length=32)
    apr_percent: float = Field(ge=0, le=100)
    term_months: int = Field(ge=1, le=360)
    offer_details: str = Field(min_length=1, max_length=500)
    disclosure: str = Field(
        default=GREEN_SKY_APPLICATION_DISCLOSURE,
        min_length=1,
        max_length=500,
    )


class ProposalCategorySection(BaseModel):
    """One priced product-line section (permanent / christmas) in a quote.

    Landscape keeps its rich tier cards and bistro its bespoke block; these
    sections carry the *new* per-linear-ft / decor lines so the client page can
    render any mix of product lines uniformly.

    ``takedown``/``storage`` record the seasonal services the client actually
    bought, so downstream dispatch reads a field instead of pattern-matching a
    display label. Both are ``None`` on sections written before this existed and
    on non-seasonal lines — a consumer must read ``None`` as "unknown", never as
    "declined", or a season already sold silently loses its takedown crew.

    ``value_props`` is the "why buy from us" copy for this product line,
    snapshot at save time so a later Settings edit never rewrites the promises
    on a proposal a customer has already read. Empty on sections written before
    this existed, which the client page renders as nothing rather than as an
    empty section.
    """

    key: str
    label: str
    lines: list[CategoryLine] = Field(default_factory=list)
    value_props: list[ValueProp] = Field(default_factory=list)
    financed_total: float = 0
    cash_total: float = 0
    cash_savings: float = 0
    monthly_payment: float = 0
    min_applied: bool = False
    takedown: bool | None = None
    storage: bool | None = None


class FulfillmentPart(BaseModel):
    """Aggregated internal SKU line for the fulfillment sheet (never client-facing)."""

    sku: str
    description: str | None = None
    qty: float
    inventory_behavior: Literal["consumable", "reusable"] = "consumable"


class QuoteInventoryAvailabilityItem(BaseModel):
    """One internal fulfillment requirement compared with current workspace stock."""

    sku: str
    description: str | None = None
    required_quantity: float
    inventory_item_id: uuid.UUID | None = None
    inventory_item_name: str | None = None
    unit_of_measure: str | None = None
    quantity_on_hand: float | None = None
    shortfall: float | None = None
    status: Literal["in_stock", "shortage", "not_counted", "untracked"]


class QuoteInventoryAvailability(BaseModel):
    """Live-at-quote-time inventory coverage; internal and never customer-facing."""

    items: list[QuoteInventoryAvailabilityItem] = Field(default_factory=list)
    has_requirements: bool = False
    has_shortages: bool = False
    shortage_items: int = 0
    not_counted_items: int = 0
    untracked_items: int = 0


class ProposalDocument(BaseModel):
    """The full computed snapshot stored on ``quote.proposal_document``."""

    model_config = ConfigDict(from_attributes=True)

    version: int = 1
    pricing_source: Literal["workspace_rules", "price_book"] = "workspace_rules"
    client: WizardClient | None = None
    tier_order: list[str] = Field(default_factory=list)
    tiers: list[ProposalTierView] = Field(default_factory=list)
    selected_tier: str | None = None
    headline_tier: str | None = None
    additional_charges: list[ProposalCharge] = Field(default_factory=list)
    care_plan: ProposalCarePlan | None = None
    bistro: BistroPricing | None = None
    financing: ProposalFinancing | None = None
    green_sky: ProposalGreenSky | None = None
    night_preview: dict[str, Any] | None = None
    # Rep-uploaded design mockups (data-URL images) shown in the visual gallery.
    mockups: list[ProposalMockup] = Field(default_factory=list)
    # Product lines included in this quote (canonical order) + their new sections.
    categories: list[str] = Field(default_factory=list)
    category_sections: list[ProposalCategorySection] = Field(default_factory=list)
    # Which service path this quote came from: "landscape" | "permanent" |
    # "christmas", "mixed" for a legacy cross-service payload, or null when no
    # product line was recognized. Derived, never trusted from the client.
    service: str | None = None
    # Selected tier's headline figures, surfaced for quick reads.
    selected_financed_total: float = 0
    selected_cash_total: float = 0
    selected_monthly_payment: float = 0
    # Combined all-in figures across every included product line.
    grand_financed_total: float = 0
    grand_cash_total: float = 0
    grand_monthly_payment: float = 0
    # Resolved upfront deposit for the selected (financed) total, when requested.
    # ``deposit_mode``/``deposit_value`` echo the rep's selection; ``deposit_amount``
    # is the money due today. All null/zero when no deposit applies.
    deposit_mode: str | None = None
    deposit_value: float = 0
    deposit_amount: float = 0
    # Operator-entered top of a ballpark range, snapshotted with the quote.
    # Deliberately **not** client-safe: the public payload gets the validated
    # low/high pair, while the proposal document remains staff-only.
    price_range_high: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    # Internal fulfillment sheet for the selected tier (staff-only).
    fulfillment: list[FulfillmentPart] = Field(default_factory=list)
    # Snapshot of current on-hand coverage when this preview/quote was built.
    # No stock is reserved or consumed until accepted work becomes a job.
    inventory_availability: QuoteInventoryAvailability | None = None
    notes: str | None = None
    terms: str | None = None
    # Operator-authored project terms carried through to the client page.
    narrative: ProposalNarrative | None = None
    # The cross-sell prompt this selection currently earns, e.g. a roof job with
    # no gutters on it. **Preview-only and never persisted**: the live preview
    # sets it so the builder can prompt the rep while the quote is still being
    # built — which is the only point at which adding the attach costs nothing
    # and a dismissal can be recorded against the quote as it is created. The
    # save path deliberately leaves it null, so a stored snapshot never carries
    # a stale prompt, and enforcement still happens server-side on save rather
    # than being something the client can talk its way out of.
    attach_warning: AttachWarning | None = None


# Fields of :class:`ProposalDocument` that may cross to the unauthenticated
# client proposal page. Deliberately an ALLOWLIST, not a denylist: a new field
# added to the document is withheld from clients until someone adds it here, so
# leaking internal data takes an explicit act rather than an oversight.
#
# ``fulfillment`` is the field this guards today — distributor part numbers and
# the bill-of-materials, which the client must never see.
CLIENT_SAFE_DOCUMENT_FIELDS: frozenset[str] = frozenset(
    {
        "version",
        "client",
        "tier_order",
        "tiers",
        "selected_tier",
        "headline_tier",
        "additional_charges",
        "care_plan",
        "bistro",
        "financing",
        "green_sky",
        "night_preview",
        "mockups",
        "categories",
        "category_sections",
        "service",
        "selected_financed_total",
        "selected_cash_total",
        "selected_monthly_payment",
        "grand_financed_total",
        "grand_cash_total",
        "grand_monthly_payment",
        "deposit_mode",
        "deposit_value",
        "deposit_amount",
        "notes",
        "terms",
        # Operator-authored project terms. Safe to show: this is the same copy
        # the rep is describing to the customer, not internal fulfilment data.
        "narrative",
    }
)


def client_safe_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Copy a stored ``proposal_document`` down to its client-safe fields.

    The stored snapshot mixes presentation data with staff-only data (see
    :data:`CLIENT_SAFE_DOCUMENT_FIELDS`). Never hand the raw dict to the public
    proposal payload — run it through here first. Returns a new dict; the
    caller's snapshot is not mutated.
    """
    if document is None:
        return None
    return {k: v for k, v in document.items() if k in CLIENT_SAFE_DOCUMENT_FIELDS}
