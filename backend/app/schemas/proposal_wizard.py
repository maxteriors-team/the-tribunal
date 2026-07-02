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
    TierPricing,
)


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
    # Opaque night-preview snapshot (image ref, light markers, dusk level).
    night_preview: dict[str, Any] | None = None
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
    # Selected tier's headline figures, surfaced for quick reads.
    selected_financed_total: float = 0
    selected_cash_total: float = 0
    selected_monthly_payment: float = 0
    # Internal fulfillment sheet for the selected tier (staff-only).
    fulfillment: list[FulfillmentPart] = Field(default_factory=list)
    notes: str | None = None
    terms: str | None = None
