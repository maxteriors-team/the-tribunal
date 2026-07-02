"""Per-workspace sales-pricing config schemas.

The single source of truth for a workspace's proposal *engine* — everything the
uploaded landscape-lighting wizard kept in its ``CONFIG`` object **except the
fixture catalog** (that lives in :mod:`app.models.catalog`). Stored as a JSONB
blob under ``workspace.settings["pricing"]`` and read through
:mod:`app.services.quotes.pricing_config`, exactly like the proposal template.

This is the "fork the data, not the code" boundary: a second lighting business is
a new workspace whose ``pricing`` block is a clone of the first's with different
tax/financing/commission and tier labels — no code change, no duplicated engine.

Read leniently (a hand-edited blob never 500s a settings read); write validated
(bad rates/perconfig are rejected at the edge). Money is plain ``float`` to match
the quote/invoice schemas; the server recomputes canonical totals with
``Numeric`` in :mod:`app.services.quotes.proposal_pricing`.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Money / financing knobs
# --------------------------------------------------------------------------- #
TaxMethod = Literal["Exclusive", "Inclusive"]


class TaxConfig(BaseModel):
    """Sales-tax rule applied to the proposal + canonical totals."""

    enabled: bool = False
    rate: float = Field(default=0.06, ge=0, le=1)
    method: TaxMethod = "Exclusive"
    label: str = "Sales Tax"


class FinancingConfig(BaseModel):
    """Wisetack 0% APR promotional financing (shared across lighting brands).

    ``feeBuffer`` grosses every price up by ``price / (1 - feeBuffer)`` so a
    financed job never eats margin; cash pricing backs it out again while keeping
    the card reserve. Defaults mirror the landscape wizard so a new lighting
    workspace inherits the same financing before it customizes anything.
    """

    enabled: bool = True
    provider: str = "Wisetack"
    max_amount: float = Field(default=25000, ge=0)
    terms: list[int] = Field(default_factory=lambda: [6, 12, 24])
    default_term: int = 24
    apr: float = Field(default=0.0, ge=0, le=1)
    fee_buffer: float = Field(default=0.11, ge=0, lt=0.95)
    headline: str | None = None
    body: str | None = None
    points: list[str] = Field(default_factory=list)
    disclaimer: str | None = None


class CashDiscountConfig(BaseModel):
    """Cash/check pricing: backs out the finance buffer, keeps a card reserve."""

    enabled: bool = True
    card_reserve_rate: float = Field(default=0.03, ge=0, lt=0.95)
    label: str = "Cash / Check Pricing"


class CommissionConfig(BaseModel):
    """Internal-only rep commission. Never rendered on the client proposal."""

    enabled: bool = True
    rate: float = Field(default=0.12, ge=0, lt=0.95)
    in_price: bool = False
    label: str = "Sales Commission"


# --------------------------------------------------------------------------- #
# Tiers (Good / Better / Best) — named groups of catalog items + copy
# --------------------------------------------------------------------------- #
class TierSection(BaseModel):
    """A titled group of catalog-item ids inside a tier (calculator section)."""

    title: str
    item_ids: list[str] = Field(default_factory=list)


class TierConfig(BaseModel):
    """One proposal package (a named group of catalog items + presentation copy).

    ``item_ids`` reference catalog items by their ``sku`` (or a stable key) so the
    same tier definition survives catalog edits. All copy is per-business.
    """

    key: str
    label: str
    tab: str | None = None
    tab_sub: str | None = None
    marker: str | None = None
    card_tier: str | None = None
    name: str | None = None
    warranty: str | None = None
    experience: str | None = None
    points: list[str] = Field(default_factory=list)
    value_tag: str | None = None
    popular: bool = False
    sections: list[TierSection] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Add-on modules (Care Plan, savings, bistro string lighting)
# --------------------------------------------------------------------------- #
class CarePlanTier(BaseModel):
    """One Care Plan tier; price = base + perFixture × (fixtures over free)."""

    key: str
    name: str
    base: float = Field(default=0, ge=0)
    per_fixture: float = Field(default=0, ge=0)
    visits: int = Field(default=1, ge=0)
    repair_discount: float = Field(default=0, ge=0, le=1)
    blurb: str | None = None
    popular: bool = False


class CarePlanConfig(BaseModel):
    """Auto-priced maintenance plan, keyed off the proposal's fixture count."""

    free_fixtures: int = Field(default=10, ge=0)
    tiers: list[CarePlanTier] = Field(default_factory=list)


class SavingsConfig(BaseModel):
    """First-year savings estimate inputs (per-fixture so they scale)."""

    per_visit_value: float = Field(default=179, ge=0)
    avoided_repair_per_fixture: float = Field(default=28, ge=0)
    assumed_repair_spend_per_fixture: float = Field(default=40, ge=0)


class BistroTier(BaseModel):
    """Install-difficulty tier for string lighting priced per linear foot."""

    key: str
    name: str
    desc: str | None = None
    per_ft: float = Field(default=0, ge=0)
    classic_per_ft: float = Field(default=0, ge=0)


class BistroProduct(BaseModel):
    """A bistro product (color-changing or classic) with its own hardware cost."""

    name: str
    subtitle: str | None = None
    hardware: float = Field(default=0, ge=0)
    strand_lengths: list[int] = Field(default_factory=list)
    min_footage: int = Field(default=0, ge=0)
    bulb_spacing_ft: float = Field(default=2, gt=0)


class BistroConfig(BaseModel):
    """Optional string-lighting add-on. A lighting brand may omit it entirely."""

    enabled: bool = False
    minimum: float = Field(default=0, ge=0)
    tiers: list[BistroTier] = Field(default_factory=list)
    color: BistroProduct | None = None
    classic: BistroProduct | None = None


# --------------------------------------------------------------------------- #
# Top-level pricing config
# --------------------------------------------------------------------------- #
class PricingSettings(BaseModel):
    """The full sales-pricing config for a workspace (read view, lenient).

    Mirrors the uploaded wizard's ``CONFIG`` minus the fixture catalog. Sensible
    lighting defaults so a brand-new workspace prices before customization; the
    seed script overwrites tiers/care-plan/savings/bistro with real data.
    """

    model_config = ConfigDict(extra="ignore")

    tax: TaxConfig = Field(default_factory=TaxConfig)
    financing: FinancingConfig = Field(default_factory=FinancingConfig)
    cash_discount: CashDiscountConfig = Field(default_factory=CashDiscountConfig)
    commission: CommissionConfig = Field(default_factory=CommissionConfig)
    tier_order: list[str] = Field(default_factory=list)
    tiers: list[TierConfig] = Field(default_factory=list)
    care_plan: CarePlanConfig = Field(default_factory=CarePlanConfig)
    savings: SavingsConfig = Field(default_factory=SavingsConfig)
    bistro: BistroConfig = Field(default_factory=BistroConfig)


# --------------------------------------------------------------------------- #
# Computed pricing results (outputs of app.services.quotes.proposal_pricing)
# --------------------------------------------------------------------------- #
# These live in the schema layer (not the service) so both the pricing service
# and the wizard payload schema can reference them without a schemas -> services
# import cycle.
class TierPricing(BaseModel):
    """Computed money for one tier, both financed and cash."""

    base: float  # sum of grossed fixture prices × qty
    additional: float  # grossed add-on charges included in every tier
    financed_total: float  # base + additional (the posted quote total)
    cash_total: float
    cash_savings: float
    monthly_payment: float  # at the default term
    monthly_by_term: dict[int, float] = Field(default_factory=dict)
    commission_financed: float
    commission_cash: float


class CarePlanPricing(BaseModel):
    """A priced Care Plan option for a given fixture count."""

    key: str
    name: str
    price: float
    savings: float
    visits: int
    repair_discount: float
    blurb: str | None = None
    popular: bool = False


class BistroLine(BaseModel):
    """One line in the bistro breakdown (a strand/case/pack or a note)."""

    label: str | None = None
    detail: str | None = None
    note: str | None = None
    sku: str | None = None
    qty: float | None = None
    description: str | None = None


class BistroPricing(BaseModel):
    """Computed bistro string-lighting price + component breakdown."""

    feet: float
    product: str
    tier: str
    per_ft: float
    hardware: float
    minimum: float
    lights_cost: float
    raw_total: float
    total: float
    min_applied: bool
    ordered_ft: float
    lines: list[BistroLine] = Field(default_factory=list)


class PricingSettingsUpdate(BaseModel):
    """Partial update of the pricing config (shallow top-level merge).

    Every block is optional; only provided top-level keys are written, so editing
    ``financing`` never clobbers ``tiers``. A provided block replaces that whole
    block (validated), matching how the seed/fork flow writes config wholesale.
    """

    tax: TaxConfig | None = None
    financing: FinancingConfig | None = None
    cash_discount: CashDiscountConfig | None = None
    commission: CommissionConfig | None = None
    tier_order: list[str] | None = None
    tiers: list[TierConfig] | None = None
    care_plan: CarePlanConfig | None = None
    savings: SavingsConfig | None = None
    bistro: BistroConfig | None = None
