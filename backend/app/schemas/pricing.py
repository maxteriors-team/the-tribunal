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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


class DepositConfig(BaseModel):
    """Workspace default upfront deposit applied to new quotes.

    When ``enabled`` a saved quote inherits this deposit unless the operator sets
    one explicitly. ``mode`` picks how ``value`` is read: ``percentage`` (0-100
    of the total) or ``fixed`` (a flat amount in major units). Disabled by
    default so nothing changes for a workspace that never configures a deposit.
    """

    enabled: bool = False
    mode: Literal["percentage", "fixed"] = "percentage"
    value: float = Field(default=50, ge=0)


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
# Permanent holiday lighting (per-linear-foot roofline + controller/channels)
# --------------------------------------------------------------------------- #
def _default_permanent_perks() -> list[str]:
    """Client-facing selling points for permanent lighting (operator-editable)."""
    return [
        "Installed once — never put up or take down lights again",
        "App-controlled colors, scenes, and schedules year-round",
        "Works for every holiday, game day, and party — not just Christmas",
        "No annual install or removal fees eating into your budget",
        "Professional-grade LEDs backed by a multi-year warranty",
        "Hidden when off — a clean roofline in daylight",
    ]


class PermanentConfig(BaseModel):
    """Permanent LED roofline priced per linear foot plus a controller/hub.

    Placeholder rates ship so a workspace prices before customization; the
    operator tunes ``per_ft`` / controller / channel rates in Settings → Pricing
    (the operator's standalone tool was not provided, so these are sane defaults).
    All values are *net*; the engine grosses them up like every other price.
    """

    enabled: bool = False
    per_ft: float = Field(default=32, ge=0)  # installed roofline, net $/linear ft
    controller_base: float = Field(default=299, ge=0)  # base controller/hub
    per_channel: float = Field(default=45, ge=0)  # each zone/channel over included
    included_channels: int = Field(default=1, ge=0)
    minimum: float = Field(default=0, ge=0)
    label: str = "Permanent Holiday Lighting"
    # Client-facing perks rendered on the comparison page (operator-editable).
    perks: list[str] = Field(default_factory=_default_permanent_perks)


# --------------------------------------------------------------------------- #
# Christmas (seasonal) — roofline + generic decor items (each / per-ft) + takedown
# --------------------------------------------------------------------------- #
class SizeRate(BaseModel):
    """A size/variant option (e.g. a tree size) with its own net install price."""

    key: str = Field(min_length=1, max_length=60)
    name: str
    price: float = Field(default=0, ge=0)


# ``each`` = priced per selected item (trees, bushes, wreaths); ``per_ft`` =
# priced per linear foot of the measured run (garland, like the roofline).
SeasonalUnit = Literal["each", "per_ft"]


class SeasonalItem(BaseModel):
    """One seasonal-decor category — the unit of standardization.

    Trees, bushes, wreaths, garland, and anything added later (bows, stakes,
    mini-trees) are all just a :class:`SeasonalItem`: a keyed category with a
    pricing ``unit`` and a list of priced ``options``. Adding a new add-on is a
    config edit, never a code change — the pricing loop and the wizard/estimator
    UI render every category the same way.
    """

    key: str = Field(min_length=1, max_length=60)  # "trees", "garland", …
    label: str  # "Trees", "Garland"
    unit: SeasonalUnit = "each"
    options: list[SizeRate] = Field(default_factory=list)


def _default_seasonal_items() -> list[SeasonalItem]:
    """Placeholder decor catalog: trees/bushes/wreaths per-item + garland per-ft."""
    return [
        SeasonalItem(
            key="trees",
            label="Trees",
            unit="each",
            options=[
                SizeRate(key="small", name="Small tree (up to 8 ft)", price=120),
                SizeRate(key="medium", name="Medium tree (8–15 ft)", price=260),
                SizeRate(key="large", name="Large tree (15–25 ft)", price=520),
            ],
        ),
        SeasonalItem(
            key="bushes",
            label="Bushes & Shrubs",
            unit="each",
            options=[
                SizeRate(key="small", name="Small bush / shrub", price=35),
                SizeRate(key="large", name="Large bush / shrub", price=65),
            ],
        ),
        SeasonalItem(
            key="wreaths",
            label="Wreaths",
            unit="each",
            options=[
                SizeRate(key="standard", name="Wreath (up to 36 in)", price=85),
                SizeRate(key="large", name="Large wreath (over 36 in)", price=150),
            ],
        ),
        # Mini lights wrapped on bushes/trees, priced per linear foot of run
        # (like garland) so the estimator's traced mini-light strands price.
        SeasonalItem(
            key="mini_lights",
            label="Mini Lights (bushes & trees)",
            unit="per_ft",
            options=[SizeRate(key="standard", name="Mini lights (installed)", price=5)],
        ),
        SeasonalItem(
            key="garland",
            label="Garland",
            unit="per_ft",
            options=[SizeRate(key="standard", name="Garland (installed)", price=8)],
        ),
    ]


# Legacy per-category rate keys (pre-standardization) → (item key, label). Old
# stored ``pricing.christmas`` blobs and in-flight wizard payloads used these
# three fixed lists; the ``mode="before"`` validator upgrades them to ``items``
# so nothing reprices.
_LEGACY_SEASONAL_RATE_KEYS: tuple[tuple[str, str, str], ...] = (
    ("tree_rates", "trees", "Trees"),
    ("bush_rates", "bushes", "Bushes & Shrubs"),
    ("wreath_rates", "wreaths", "Wreaths"),
)


def _default_christmas_perks() -> list[str]:
    """Client-facing selling points for temporary lighting (operator-editable)."""
    return [
        "Lower upfront cost to get a festive look this season",
        "Professional install, takedown, and off-season storage handled for you",
        "Switch up the design or colors from year to year",
        "Nothing permanently attached to your home",
        "Great way to try holiday lighting before committing to permanent",
    ]


class ChristmasConfig(BaseModel):
    """Seasonal Christmas lighting: roofline + generic decor items + takedown.

    Rates are *net* placeholders (operator's tool not provided) tuned later in
    Settings → Pricing. ``takedown_rate`` is a fraction of the install subtotal
    added when the client opts into post-season takedown; ``storage_price`` is a
    flat fee for off-season storage. ``items`` is the standardized decor catalog
    (trees/bushes/wreaths/garland/…); adding an add-on is a config edit only.
    """

    enabled: bool = False
    roofline_per_ft: float = Field(default=6, ge=0)  # net $/linear ft installed
    items: list[SeasonalItem] = Field(default_factory=_default_seasonal_items)
    takedown_enabled: bool = True
    takedown_rate: float = Field(default=0.25, ge=0, le=1)  # of install subtotal
    storage_price: float = Field(default=0, ge=0)  # flat off-season storage fee
    minimum: float = Field(default=0, ge=0)
    label: str = "Christmas Lighting"
    # Client-facing perks rendered on the comparison page (operator-editable).
    perks: list[str] = Field(default_factory=_default_christmas_perks)

    @model_validator(mode="before")
    @classmethod
    def _upgrade_legacy_rate_lists(cls, data: Any) -> Any:
        """Build ``items`` from legacy ``tree_rates``/``bush_rates``/``wreath_rates``.

        A workspace persisted before decor was standardized stores the three
        fixed rate lists instead of ``items``. When ``items`` is absent but any
        legacy list is present, synthesize an equivalent ``each`` catalog so old
        blobs (and any in-flight wizard payloads) price identically.
        """
        if not isinstance(data, dict) or data.get("items") is not None:
            return data
        legacy = [
            SeasonalItem(key=item_key, label=label, unit="each", options=data[rate_key])
            for rate_key, item_key, label in _LEGACY_SEASONAL_RATE_KEYS
            if data.get(rate_key)
        ]
        if legacy:
            legacy_keys = {rate_key for rate_key, _, _ in _LEGACY_SEASONAL_RATE_KEYS}
            data = {k: v for k, v in data.items() if k not in legacy_keys}
            data["items"] = [i.model_dump() for i in legacy]
        return data


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
    deposit: DepositConfig = Field(default_factory=DepositConfig)
    tier_order: list[str] = Field(default_factory=list)
    tiers: list[TierConfig] = Field(default_factory=list)
    care_plan: CarePlanConfig = Field(default_factory=CarePlanConfig)
    savings: SavingsConfig = Field(default_factory=SavingsConfig)
    bistro: BistroConfig = Field(default_factory=BistroConfig)
    permanent: PermanentConfig = Field(default_factory=PermanentConfig)
    christmas: ChristmasConfig = Field(default_factory=ChristmasConfig)
    # Horizon (seasons) for the permanent-vs-temporary multi-year savings pitch.
    comparison_years: int = Field(default=5, ge=1, le=30)


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


class CategoryLine(BaseModel):
    """One grossed-up line in a permanent/christmas breakdown (display only).

    ``line_total`` is the authoritative grossed component cost; ``unit_price`` is
    a per-unit display figure and may not exactly divide the total after rounding.
    """

    label: str
    detail: str | None = None
    quantity: float = 1
    unit_price: float = 0
    line_total: float = 0


class PermanentPricing(BaseModel):
    """Computed permanent-holiday-lighting price + component breakdown."""

    feet: float
    channels: int
    per_ft: float
    roofline_cost: float
    controller_cost: float
    channels_cost: float
    minimum: float
    raw_total: float
    total: float
    min_applied: bool
    lines: list[CategoryLine] = Field(default_factory=list)


class SeasonalItemCost(BaseModel):
    """Grossed cost of one seasonal-decor category in a computed christmas price."""

    key: str  # matches the SeasonalItem key ("trees", "garland", …)
    label: str
    unit: SeasonalUnit
    cost: float


class ChristmasPricing(BaseModel):
    """Computed seasonal-Christmas price + component breakdown.

    Per-category decor costs live in ``items`` (one :class:`SeasonalItemCost`
    each) so trees/bushes/wreaths/garland/… are uniform; ``lines`` remains the
    authoritative display breakdown that sums to ``raw_total``.
    """

    roofline_feet: float
    roofline_cost: float
    items: list[SeasonalItemCost] = Field(default_factory=list)
    takedown_cost: float
    storage_cost: float
    minimum: float
    raw_total: float
    total: float
    min_applied: bool
    lines: list[CategoryLine] = Field(default_factory=list)


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
    deposit: DepositConfig | None = None
    tier_order: list[str] | None = None
    tiers: list[TierConfig] | None = None
    care_plan: CarePlanConfig | None = None
    savings: SavingsConfig | None = None
    bistro: BistroConfig | None = None
    permanent: PermanentConfig | None = None
    christmas: ChristmasConfig | None = None
    comparison_years: int | None = Field(default=None, ge=1, le=30)
