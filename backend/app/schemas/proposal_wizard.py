"""Sales-wizard save/preview payloads and the computed proposal document.

The wizard collects a client, per-fixture quantities (referencing catalog items),
add-on charges, a chosen tier, a Care Plan pick, and optional bistro/night
preview. It POSTs that raw *selection* — never money. The server resolves catalog
prices, applies the workspace pricing config, and returns a fully-computed
:class:`ProposalDocument` (the snapshot stored on ``quote.proposal_document`` and
rendered by the public page). Client totals are never trusted.
"""

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.pricing import (
    BistroPricing,
    CarePlanPricing,
    CategoryLine,
    TierPricing,
)

# Product lines the unified builder can quote, in canonical display order.
CATEGORY_ORDER = ("landscape", "permanent", "bistro", "christmas")


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
    server grosses it up by the finance buffer like every other price."""

    description: str | None = Field(default=None, max_length=300)
    net_amount: float = Field(default=0, ge=0)


class WizardFixtureQty(BaseModel):
    """Quantity for one catalog item, keyed by its stable id (``sku`` or key)."""

    item_id: str = Field(min_length=1, max_length=120)
    quantity: float = Field(default=0, ge=0)


class WizardBistroSelection(BaseModel):
    """Optional string-lighting selection."""

    product: str = "color"  # "color" | "classic"
    tier: str = "easy"
    feet: float = Field(default=0, ge=0)


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
    """

    roofline_feet: float = Field(default=0, ge=0)
    items: dict[str, list[WizardCategoryCount]] = Field(default_factory=dict)
    takedown: bool = False
    storage: bool = False


class ProposalMockup(BaseModel):
    """A rep-uploaded design mockup shown in the proposal's visual gallery.

    ``image`` is a self-contained data URL (base64 JPEG/PNG/WebP) stored inline
    in the snapshot exactly like the night-preview image — this deployment has
    no object storage. The wizard resizes images client-side before upload, and
    the length cap is a defensive backstop against an oversized snapshot row.
    """

    image: str = Field(min_length=1, max_length=3_000_000)
    caption: str | None = Field(default=None, max_length=160)


class ProposalWizardPayload(BaseModel):
    """Everything the wizard submits on save/preview (selection only, no money)."""

    contact_id: int | None = None
    service_location_id: uuid.UUID | None = None
    opportunity_id: uuid.UUID | None = None
    client: WizardClient | None = None
    quantities: list[WizardFixtureQty] = Field(default_factory=list)
    additional_charges: list[WizardCharge] = Field(default_factory=list)
    # Tier the client is buying; defaults to the highest-value ("headline") tier.
    selected_tier: str | None = None
    care_plan_tier: str | None = None
    care_count_manual: int | None = Field(default=None, ge=0)
    bistro: WizardBistroSelection | None = None
    # Which product lines this quote includes. Empty => legacy landscape(+bistro)
    # inference so existing payloads keep working.
    categories: list[str] = Field(default_factory=list)
    permanent: WizardPermanentSelection | None = None
    christmas: WizardChristmasSelection | None = None
    # Opaque night-preview snapshot (image ref, light markers, dusk level).
    night_preview: dict[str, Any] | None = None
    # Rep-uploaded design mockups rendered in the proposal's visual gallery.
    mockups: list[ProposalMockup] = Field(default_factory=list, max_length=8)
    title: str | None = Field(default=None, max_length=200)
    notes: str | None = None
    terms: str | None = None


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
    """A grossed-up add-on charge included in every tier's price."""

    description: str
    amount: float


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


class ProposalCategorySection(BaseModel):
    """One priced product-line section (permanent / christmas) in a quote.

    Landscape keeps its rich tier cards and bistro its bespoke block; these
    sections carry the *new* per-linear-ft / decor lines so the client page can
    render any mix of product lines uniformly.
    """

    key: str
    label: str
    lines: list[CategoryLine] = Field(default_factory=list)
    financed_total: float = 0
    cash_total: float = 0
    cash_savings: float = 0
    monthly_payment: float = 0
    min_applied: bool = False


class FulfillmentPart(BaseModel):
    """Aggregated internal SKU line for the fulfillment sheet (never client-facing)."""

    sku: str
    description: str | None = None
    qty: float


class ProposalDocument(BaseModel):
    """The full computed snapshot stored on ``quote.proposal_document``."""

    model_config = ConfigDict(from_attributes=True)

    version: int = 1
    client: WizardClient | None = None
    tier_order: list[str] = Field(default_factory=list)
    tiers: list[ProposalTierView] = Field(default_factory=list)
    selected_tier: str | None = None
    headline_tier: str | None = None
    additional_charges: list[ProposalCharge] = Field(default_factory=list)
    care_plan: ProposalCarePlan | None = None
    bistro: BistroPricing | None = None
    financing: ProposalFinancing | None = None
    night_preview: dict[str, Any] | None = None
    # Rep-uploaded design mockups (data-URL images) shown in the visual gallery.
    mockups: list[ProposalMockup] = Field(default_factory=list)
    # Product lines included in this quote (canonical order) + their new sections.
    categories: list[str] = Field(default_factory=list)
    category_sections: list[ProposalCategorySection] = Field(default_factory=list)
    # Selected tier's headline figures, surfaced for quick reads.
    selected_financed_total: float = 0
    selected_cash_total: float = 0
    selected_monthly_payment: float = 0
    # Combined all-in figures across every included product line.
    grand_financed_total: float = 0
    grand_cash_total: float = 0
    grand_monthly_payment: float = 0
    # Internal fulfillment sheet for the selected tier (staff-only).
    fulfillment: list[FulfillmentPart] = Field(default_factory=list)
    notes: str | None = None
    terms: str | None = None
