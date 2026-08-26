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

from calendar import month_name, monthrange
from collections.abc import Mapping
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

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


DEFAULT_FINANCING_DISCLAIMER = (
    "Payment figures are estimates for illustration only and are not a financing offer. "
    "Financing is subject to application and approval by the provider; actual terms, APR, "
    "and payment may vary."
)


def _default_financing_category_minimums() -> dict[str, float]:
    """Service categories financed by default and their qualifying subtotals.

    Lighting categories retain the original zero-minimum behavior. Core exterior
    services require a meaningful project subtotal, so a small gutter cleaning does
    not get financing copy while a roof, siding, or replacement-gutter project does.
    Workspaces may add free-form catalog categories or remove a key to disable one.
    """
    return {
        "landscape": 0,
        "bistro": 0,
        "permanent": 0,
        "christmas": 0,
        "roof": 1000,
        "roofing": 1000,
        "siding": 1000,
        "gutters": 1000,
        "windows": 1000,
        "trim": 1000,
    }


class FinancingConfig(BaseModel):
    """Promotional financing shared across service categories.

    ``fee_buffer`` grosses every wizard price up by ``price / (1 - fee_buffer)``
    so a financed job never eats margin; cash pricing backs it out again while
    keeping the card reserve. Category eligibility only controls whether an
    estimate is presented — it never changes that margin-protection math.

    ``category_minimums`` maps normalized service-category keys to the minimum
    subtotal that qualifies. Presence enables a category; removing a key disables
    it. Lighting categories default to their historical zero minimum, while core
    exterior categories default to a $1,000 floor.
    """

    enabled: bool = True
    provider: str = "Wisetack"
    max_amount: float = Field(default=25000, ge=0)
    terms: list[int] = Field(default_factory=lambda: [6, 12, 24])
    default_term: int = 24
    apr: float = Field(default=0.0, ge=0, le=1)
    fee_buffer: float = Field(default=0.11, ge=0, lt=0.95)
    category_minimums: dict[str, Annotated[float, Field(ge=0)]] = Field(
        default_factory=_default_financing_category_minimums
    )
    headline: str | None = None
    body: str | None = None
    points: list[str] = Field(default_factory=list)
    disclaimer: str | None = DEFAULT_FINANCING_DISCLAIMER

    @field_validator("category_minimums", mode="before")
    @classmethod
    def _normalize_category_keys(cls, value: Any) -> Any:
        """Match free-form catalog categories case-insensitively."""
        if not isinstance(value, dict):
            return value
        return {
            str(category).strip().lower(): minimum
            for category, minimum in value.items()
            if str(category).strip()
        }


class FinancingEstimate(BaseModel):
    """Client-safe, server-computed monthly-payment estimate for one quote."""

    provider: str
    terms: list[int] = Field(default_factory=list)
    default_term: int
    apr: float = 0
    monthly_payment: float
    monthly_by_term: dict[int, float] = Field(default_factory=dict)
    headline: str | None = None
    body: str | None = None
    points: list[str] = Field(default_factory=list)
    disclaimer: str


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


class UpsellRankConfig(BaseModel):
    """One rung on the technician selling ladder.

    ``threshold`` is approved upsell revenue within the reporting month, in major
    units. ``reward`` is free text shown to the technician ("$150 bonus", "1 extra
    PTO day") — this codebase tracks progress and never pays anything, so the
    payout mechanism stays wherever payroll already lives.
    """

    key: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=60)
    threshold: float = Field(ge=0)
    reward: str | None = Field(default=None, max_length=120)


class UpsellConfig(BaseModel):
    """Limits on what a crew lead may sell from the on-site upsell screen.

    ``field_proposal_limit`` caps the one-time total a ``lead_technician`` may
    put on a proposal, in major units. Office roles are exempt, and a plain
    ``technician`` cannot sell at all, so the crew lead is the only role this
    number governs: it separates "sell small add-ons" from "sell a full fixture
    package without the office seeing it first".

    ``None`` means **no cap**, which is the default: adding this block must not
    retroactively restrict a workspace that never asked for a limit. Owners opt
    in by setting a number.

    Compared against the *grossed-up* total the client is actually charged, not
    the net price-book figure, so the limit means what an owner thinks it means.
    Recurring care plans sit deliberately outside the cap: signing an existing
    system onto maintenance is retention every lead should be closing, and it is
    cancellable service rather than a capital purchase.
    """

    field_proposal_limit: float | None = Field(default=None, ge=0)
    # Selling ranks a technician climbs, lowest threshold first. Empty by
    # default and deliberately so: rank names, the revenue needed to reach them,
    # and what a technician earns there are an operator's compensation policy,
    # not something this codebase should invent. With no ranks configured the
    # technician still sees their own sold/approved/attach numbers — those are
    # facts — and simply sees no ladder.
    ranks: list[UpsellRankConfig] = Field(default_factory=list)

    @field_validator("ranks")
    @classmethod
    def _sort_ranks(cls, value: list[UpsellRankConfig]) -> list[UpsellRankConfig]:
        """Keep ranks in ascending threshold order however they were entered.

        Progress maths walks this list, so an operator listing Gold before Bronze
        must not produce a ladder that counts downwards.
        """
        return sorted(value, key=lambda rank: rank.threshold)


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


BistroInstallation = Literal["temporary", "permanent"]


class BistroTier(BaseModel):
    """Install-difficulty tier for legacy string lighting priced per linear foot."""

    key: str
    name: str
    desc: str | None = None
    per_ft: float = Field(default=0, ge=0)
    classic_per_ft: float = Field(default=0, ge=0)


class BistroProduct(BaseModel):
    """A legacy bistro product (color-changing or classic) and its hardware cost."""

    name: str
    subtitle: str | None = None
    hardware: float = Field(default=0, ge=0)
    strand_lengths: list[int] = Field(default_factory=list)
    min_footage: int = Field(default=0, ge=0)
    bulb_spacing_ft: float = Field(default=2, gt=0)


class BistroInstallationConfig(BaseModel):
    """Measured light and pole rates plus internal stock mappings."""

    label: str = Field(max_length=120)
    lights_per_ft: float = Field(default=0, ge=0)
    poles_each: float = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("poles_each", "poles_per_ft"),
    )
    lights_inventory_sku: str | None = Field(default=None, min_length=1, max_length=100)
    poles_inventory_sku: str | None = Field(default=None, min_length=1, max_length=100)
    stock_feet_per_light_unit: float = Field(default=1, gt=0, le=100_000)

    @field_validator("lights_inventory_sku", "poles_inventory_sku", mode="before")
    @classmethod
    def _normalize_inventory_sku(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class BistroConfig(BaseModel):
    """String-lighting rates plus legacy sales-wizard product configuration."""

    enabled: bool = False
    minimum: float = Field(default=0, ge=0)
    temporary: BistroInstallationConfig = Field(
        default_factory=lambda: BistroInstallationConfig(
            label="Temporary Bistro Lighting", stock_feet_per_light_unit=200
        )
    )
    permanent: BistroInstallationConfig = Field(
        default_factory=lambda: BistroInstallationConfig(
            label="Permanent Bistro Lighting", stock_feet_per_light_unit=1
        )
    )
    tiers: list[BistroTier] = Field(default_factory=list)
    color: BistroProduct | None = None
    classic: BistroProduct | None = None

    @model_validator(mode="after")
    def _default_stock_coverage_by_installation(self) -> "BistroConfig":
        """Keep old pricing blobs safe: temporary units are sets, permanent units are feet."""
        if "stock_feet_per_light_unit" not in self.temporary.model_fields_set:
            self.temporary.stock_feet_per_light_unit = 200
        if "stock_feet_per_light_unit" not in self.permanent.model_fields_set:
            self.permanent.stock_feet_per_light_unit = 1
        return self


# --------------------------------------------------------------------------- #
# Permanent holiday lighting (footage rounded up to stocked kits)
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


class PermanentPackage(BaseModel):
    """One supplier kit used to cover a measured roofline."""

    feet: int = Field(gt=0)
    cost: float = Field(ge=0)


def _default_permanent_packages() -> list[PermanentPackage]:
    """Current Minleon RGBW WEC Mini complete-kit costs (August 2026)."""
    return [
        PermanentPackage(feet=100, cost=1249),
        PermanentPackage(feet=150, cost=1649),
        PermanentPackage(feet=200, cost=2099),
        PermanentPackage(feet=400, cost=3999),
    ]


class PermanentConfig(BaseModel):
    """Permanent LED roofline priced by the smallest kit that covers the job.

    Package costs are COGS. ``markup`` converts COGS to the net installed sale
    price before the standard cash/financing gross-up is applied.
    """

    enabled: bool = False
    packages: list[PermanentPackage] = Field(
        default_factory=_default_permanent_packages, min_length=1
    )
    easy_markup: float = Field(default=2.5, gt=0)
    standard_markup: float = Field(default=3, gt=0)
    complex_markup: float = Field(default=3.5, gt=0)
    # Deprecated single multiplier retained for older saved settings and clients.
    markup: float = Field(default=3.5, gt=0)
    # Deprecated inputs retained so older saved settings and clients still parse.
    # They are intentionally ignored by package pricing.
    per_ft: float = Field(default=0, ge=0)
    controller_base: float = Field(default=0, ge=0)
    per_channel: float = Field(default=0, ge=0)
    included_channels: int = Field(default=0, ge=0)
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
            # Priced per diameter so a rep can add several sizes on one quote.
            options=[
                SizeRate(key="36in", name="Wreath (36 in)", price=85),
                SizeRate(key="48in", name="Wreath (48 in)", price=125),
                SizeRate(key="60in", name="Wreath (60 in)", price=165),
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


# Substituted into a :class:`ValueProp` body with the workspace's configured
# in-season maintenance cutoff ("December 23"). One token means the operator can
# reword the promise freely while the *date* stays owned by
# ``ChristmasConfig.maintenance_through_*`` -- so moving the cutoff can never
# leave a stale date sitting in the customer-facing copy of one proposal.
MAINTENANCE_THROUGH_TOKEN = "{maintenance_through}"


class ValueProp(BaseModel):
    """One titled selling point rendered on the client-facing proposal.

    Richer than the flat ``perks`` strings on the comparison page: the proposal
    needs a scannable title plus a sentence of substance, because it is the
    document a homeowner reads alone, at night, before deciding.
    """

    title: str
    body: str


def _default_christmas_value_props() -> list[ValueProp]:
    """Why a homeowner should buy seasonal lighting from this company.

    Operator-editable. Answers the four questions a homeowner actually asks:
    what happens when something breaks, what do I own, what does it cost, and
    what does my house look like when it is over.
    """
    return [
        ValueProp(
            title="A Worry-Free Christmas",
            body=(
                f"Maintenance is included through {MAINTENANCE_THROUGH_TOKEN}. "
                "If a bulb goes out or a strand comes loose, we come out and "
                "fix it at no charge."
            ),
        ),
        ValueProp(
            title="Every Light Is Ours",
            body=(
                "We own the bulbs, strands, and clips. You never buy the "
                "equipment, hunt for replacements, or find somewhere to store "
                "it in January."
            ),
        ),
        ValueProp(
            title="Everything Is Included",
            body=(
                "Design, installation, in-season maintenance, takedown, and "
                "off-season storage are all part of the price you see here."
            ),
        ),
        ValueProp(
            title="Your Neighbors Will Be Jealous",
            body=(
                "Strands are cut to fit your roofline, so the lines run "
                "straight and every peak and gable lands even."
            ),
        ),
        ValueProp(
            title="Affordable, Up-Front Pricing",
            body=(
                "One seasonal price, agreed before we start. No equipment to "
                "purchase and no surprise charges after the install."
            ),
        ),
        ValueProp(
            title="Nothing Permanent on Your Home",
            body=(
                "No drilling and no adhesive. Everything comes down clean in "
                "the new year and your home looks untouched."
            ),
        ),
    ]


class ChristmasPackage(BaseModel):
    """A seasonal-Christmas service tier (Good/Better/Best for holiday decor).

    The seasonal analog of :class:`TierConfig`: a named, presentable package that
    *includes a subset of the workspace's decor categories* plus (optionally) the
    roofline. One roofline+decor measurement prices every package by restricting
    the shared :class:`ChristmasConfig.items` selection to ``item_keys`` — so the
    same engine, gross-up, takedown, and job-minimum apply to each package subset
    (no separate pricing path). ``item_keys`` reference :class:`SeasonalItem`
    keys; ``includes_roofline`` gates the ``roofline_per_ft`` run because the
    roofline is not itself a decor item.
    """

    key: str = Field(min_length=1, max_length=60)  # "essential" | "middle" | "premier"
    label: str
    name: str | None = None
    marker: str | None = None
    card_tier: str | None = None
    experience: str | None = None
    warranty: str | None = None
    points: list[str] = Field(default_factory=list)
    value_tag: str | None = None
    popular: bool = False
    includes_roofline: bool = False
    item_keys: list[str] = Field(default_factory=list)  # SeasonalItem keys covered


def _default_christmas_packages() -> list[ChristmasPackage]:
    """Placeholder Good/Better/Best seasonal packages (operator tunes coverage).

    Coverage widens Essential → Middle → Premier so totals stay monotonic:
      * Essential — minimal decor: trees + bushes, no roofline.
      * Middle    — roofline plus trees + bushes.
      * Premier   — roofline plus trees, bushes, wreaths, and garland.
    Keys reference the default decor categories in ``_default_seasonal_items``.
    """
    return [
        ChristmasPackage(
            key="essential",
            label="Essential — Trees & Bushes",
            name="The Essential",
            marker="\u25cf",  # ●
            card_tier="Good",
            experience=(
                "A festive first impression. Your trees and bushes wrapped and "
                "glowing — a clean, cheerful look without the roofline."
            ),
            points=[
                "Trees and bushes professionally wrapped",
                "Warm, welcoming curb appeal",
                "Lowest-cost way to get a holiday look",
            ],
            includes_roofline=False,
            item_keys=["trees", "bushes"],
        ),
        ChristmasPackage(
            key="middle",
            label="Middle — Roofline + Trees & Bushes",
            name="The Classic",
            marker="\u25c6",  # ◆
            card_tier="Better",
            experience=(
                "The complete outline. A crisp roofline plus wrapped trees and "
                "bushes — the look most homes are known for."
            ),
            points=[
                "Full roofline outlined in seasonal lighting",
                "Trees and bushes wrapped to match",
                "The classic, balanced holiday display",
            ],
            popular=True,
            includes_roofline=True,
            item_keys=["trees", "bushes"],
        ),
        ChristmasPackage(
            key="premier",
            label="Premier — The Full Display",
            name="The Premier",
            marker="\u2605",  # ★
            card_tier="Best",
            experience=(
                "The whole property, transformed. Roofline, trees, bushes, "
                "wreaths, and garland — nothing left dark."
            ),
            points=[
                "Everything in Middle, fully dressed",
                "Wreaths and garland on entries and railings",
                "The magazine-cover holiday home",
            ],
            value_tag="\u2605 The Full Display",
            includes_roofline=True,
            item_keys=["trees", "bushes", "wreaths", "garland"],
        ),
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
    # Season anchors for the Service Plans a Christmas signup provisions: the
    # yearly install and takedown plans start on these calendar days (the year
    # is resolved at signup, always forward from the approval date). Defaults
    # mirror a typical mid-November install / early-January takedown season.
    season_install_month: int = Field(default=11, ge=1, le=12)
    season_install_day: int = Field(default=15, ge=1, le=31)
    season_takedown_month: int = Field(default=1, ge=1, le=12)
    season_takedown_day: int = Field(default=8, ge=1, le=31)
    # Last day of included in-season maintenance. The whole seasonal promise is
    # "we keep it lit until Christmas", so this date is quoted verbatim to the
    # customer on the proposal and must be operator-editable without a deploy.
    maintenance_through_month: int = Field(default=12, ge=1, le=12)
    maintenance_through_day: int = Field(default=23, ge=1, le=31)
    minimum: float = Field(default=0, ge=0)
    label: str = "Christmas Lighting"
    # Client-facing perks rendered on the comparison page (operator-editable).
    perks: list[str] = Field(default_factory=_default_christmas_perks)
    # Titled selling points rendered on the client-facing proposal page.
    value_props: list[ValueProp] = Field(default_factory=_default_christmas_value_props)
    # Seasonal service tiers (Good/Better/Best). When ``packages_enabled`` the
    # wizard/estimator sell Christmas as packages (a subset of ``items`` +
    # roofline priced by the shared engine); when False the current à la carte
    # decor flow is unchanged. ``package_order`` lists package keys low→high.
    packages_enabled: bool = False
    package_order: list[str] = Field(default_factory=list)
    packages: list[ChristmasPackage] = Field(default_factory=_default_christmas_packages)

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

    @model_validator(mode="after")
    def _clamp_season_days(self) -> "ChristmasConfig":
        """Clamp season anchor days to a day that exists in their month.

        Day is capped at 31 per-field, so a month/day pair like ``(2, 31)`` is
        individually valid but not a real date. Clamping (rather than raising)
        keeps the lenient-read contract: a hand-edited blob still yields a
        usable season anchor instead of 500ing every pricing read.
        """
        # 2001 is a non-leap year: February clamps to 28, the safe anchor for a
        # yearly plan that must land on a real date every year.
        self.season_install_day = min(
            self.season_install_day, monthrange(2001, self.season_install_month)[1]
        )
        self.season_takedown_day = min(
            self.season_takedown_day, monthrange(2001, self.season_takedown_month)[1]
        )
        self.maintenance_through_day = min(
            self.maintenance_through_day, monthrange(2001, self.maintenance_through_month)[1]
        )
        return self

    @property
    def maintenance_through_label(self) -> str:
        """The maintenance cutoff as customer-facing text (``"December 23"``).

        No year: the proposal promises a date within *this* season, and a year
        printed on a quote sent in late December reads as either stale or as a
        promise about next Christmas.
        """
        return f"{month_name[self.maintenance_through_month]} {self.maintenance_through_day}"


# --------------------------------------------------------------------------- #
# Top-level pricing config
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Landscape lighting (tier-based fixture design)
# --------------------------------------------------------------------------- #
def _default_landscape_perks() -> list[str]:
    """Client-facing selling points for landscape lighting (operator-editable)."""
    return [
        "Your home is the one people notice on the street after dark",
        "Safe, lit walkways, steps, and driveway every night of the year",
        "A lit house is a harder target — no dark corners to hide in",
        "Solid brass and copper fixtures that patina instead of corroding",
        "Low-voltage LED: pennies a night to run, decades of fixture life",
        "Designed on a photo of your home before a single fixture is installed",
    ]


class LandscapeConfig(BaseModel):
    """Client-facing framing for the landscape-lighting service.

    Pricing itself comes from the tiers + catalog; this only carries the value
    propositions the homeowner reads, so an operator can speak to their market
    without a code change.
    """

    model_config = ConfigDict(extra="ignore")

    perks: list[str] = Field(default_factory=_default_landscape_perks)


# --------------------------------------------------------------------------- #
# Service packages (Good / Better / Best for any service category)
# --------------------------------------------------------------------------- #
# How a category converts a measurement into money. ``per_unit`` bills the tier's
# rate against the measured quantity (roofing squares, siding sq ft, gutter feet);
# ``flat`` ignores the measurement and sells the tier at its base price.
ServicePricingBasis = Literal["flat", "per_unit"]


class ServiceInclusion(BaseModel):
    """One scope item a service package may include (the non-seasonal analog of
    :class:`SeasonalItem`).

    A category declares its scope items once — "Ice & water shield", "Ridge
    vent", "Gutter guards" — and each tier lists the ones it covers by ``key``.
    That is what makes a tier ladder *inclusive by construction*: Better is Good
    plus two more keys, so widening a tier is a config edit and the totals stay
    monotonic without a second pricing path.
    """

    key: str = Field(min_length=1, max_length=60)
    label: str
    # Net price added to any tier that includes this item. Grossed up by the
    # shared engine like every other price, never stored pre-grossed.
    price: float = Field(default=0, ge=0)
    # When True ``price`` is per measured unit rather than a flat add.
    per_unit: bool = False


class ServicePackage(BaseModel):
    """One tier of a non-seasonal service category (roof, siding, gutters, …).

    The category-agnostic sibling of :class:`ChristmasPackage`: same presentation
    fields (so one set of cards renders either), different pricing inputs —
    a measurement-driven ``per_unit_price`` plus a flat ``base_price`` instead of
    a roofline flag and decor keys.

    ``recommended`` is the tier the operator steers toward. Seasonal packages have
    no such flag and fall back to "most inclusive wins"; declaring it here lets a
    three-tier ladder anchor on its middle option, which is the whole point of
    good/better/best.
    """

    key: str = Field(min_length=1, max_length=60)  # "good" | "better" | "best"
    label: str
    name: str | None = None
    marker: str | None = None
    card_tier: str | None = None
    experience: str | None = None
    warranty: str | None = None
    points: list[str] = Field(default_factory=list)
    value_tag: str | None = None
    popular: bool = False
    recommended: bool = False
    # Net flat price for this tier (mobilization, permits, the base scope).
    base_price: float = Field(default=0, ge=0)
    # Net price per measured unit for this tier; ignored on a ``flat`` category.
    per_unit_price: float = Field(default=0, ge=0)
    # :class:`ServiceInclusion` keys this tier covers.
    inclusion_keys: list[str] = Field(default_factory=list)


def _default_service_packages() -> list[ServicePackage]:
    """Three tiers with the middle one steered — the default for a new category.

    Good / Better / Best with **Better flagged ``recommended``**: a three-tier
    ladder anchored on a middle option is the lever this whole module exists to
    give the core trades, and an operator who never opens the editor should still
    get it. Copy is deliberately service-neutral (the category could be roofing,
    siding, or gutters) and every price is 0 so a half-configured category can
    never quote a number the operator did not type.
    """
    return [
        ServicePackage(
            key="good",
            label="Good",
            name="Essential",
            marker="\u25cf",  # ●
            card_tier="Good",
            experience="The work done right, with the materials the job calls for.",
            points=["Everything needed to complete the job", "Workmanship warranty"],
        ),
        ServicePackage(
            key="better",
            label="Better",
            name="Preferred",
            marker="\u25c6",  # ◆
            card_tier="Better",
            experience="The upgrades most homeowners choose — the ones that pay for themselves.",
            points=["Everything in Essential", "Upgraded materials", "Extended warranty"],
            popular=True,
            recommended=True,
        ),
        ServicePackage(
            key="best",
            label="Best",
            name="Premier",
            marker="\u2605",  # ★
            card_tier="Best",
            experience="The complete job, nothing deferred to a future service call.",
            points=["Everything in Preferred", "Top-tier materials", "Longest warranty offered"],
        ),
    ]


class ServicePackageConfig(BaseModel):
    """A service category sold as tiers — the non-seasonal package set.

    One entry per ``service_category`` (matching
    :attr:`app.models.catalog.CatalogItem.service_category`, e.g. ``"roof"``), so
    the trades that pay the bills get the same good/better/best presentation the
    seasonal lighting side already has. Everything the presentation layer needs
    lives on the tiers; everything the engine needs — the measurement basis, the
    shared scope catalog, and the job minimum — lives here.

    Off by default and absent from every existing settings blob, so a workspace
    that never configures a category behaves exactly as it does today.
    """

    model_config = ConfigDict(extra="ignore")

    # Free-form like the catalog's own taxonomy: "roof", "siding", "Gutters".
    service_category: str = Field(min_length=1, max_length=60)
    label: str
    enabled: bool = False
    basis: ServicePricingBasis = "per_unit"
    # What the measured quantity is called on the rep tool ("sq ft", "squares").
    unit_label: str = "sq ft"
    # Client-facing note under each price ("One-time install", "Per season", …).
    price_note: str | None = None
    minimum: float = Field(default=0, ge=0)
    # Client-facing selling points for the category as a whole.
    perks: list[str] = Field(default_factory=list)
    # Shared scope catalog every tier draws its ``inclusion_keys`` from.
    inclusions: list[ServiceInclusion] = Field(default_factory=list)
    # Tier keys low→high; falls back to the declared ``packages`` order.
    package_order: list[str] = Field(default_factory=list)
    packages: list[ServicePackage] = Field(default_factory=_default_service_packages)


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
    upsell: UpsellConfig = Field(default_factory=UpsellConfig)
    tier_order: list[str] = Field(default_factory=list)
    tiers: list[TierConfig] = Field(default_factory=list)
    care_plan: CarePlanConfig = Field(default_factory=CarePlanConfig)
    savings: SavingsConfig = Field(default_factory=SavingsConfig)
    bistro: BistroConfig = Field(default_factory=BistroConfig)
    landscape: LandscapeConfig = Field(default_factory=LandscapeConfig)
    permanent: PermanentConfig = Field(default_factory=PermanentConfig)
    christmas: ChristmasConfig = Field(default_factory=ChristmasConfig)
    # Good/Better/Best ladders for the non-seasonal trades (roof, siding,
    # gutters, …), one entry per ``service_category``. Empty by default: an
    # existing settings blob has no such key, parses to ``[]``, and every
    # seasonal/landscape flow behaves exactly as it did before this existed.
    service_packages: list[ServicePackageConfig] = Field(default_factory=list)
    # Horizon (seasons) for the permanent-vs-temporary multi-year savings pitch.
    comparison_years: int = Field(default=5, ge=1, le=30)
    # Show the client a roofline-only cost comparison (permanent one-time install
    # vs seasonal roofline per season) on the public comparison page. Off by
    # default so existing workspaces and already-shared links are unchanged.
    roofline_comparison_enabled: bool = False
    # How long a quoted price holds. Stamped onto ``expiry_date`` when a quote is
    # first *sent* (not created), so a draft that sits a fortnight still reaches
    # the customer with the full window. An operator-set ``expiry_date`` always
    # wins; this only fills the blank.
    quote_validity_days: int = Field(default=30, ge=1, le=365)


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


class BistroInstallationPricing(BaseModel):
    """Server-priced light and pole allowances for one installation type."""

    installation: BistroInstallation
    label: str
    feet: float
    pole_count: int
    lights_per_ft: float
    poles_each: float
    lights_cost: float
    poles_cost: float
    total: float


class BistroPricing(BaseModel):
    """Computed bistro string-lighting price + component breakdown."""

    pricing_mode: Literal["legacy", "installation"] = "legacy"
    feet: float
    product: str
    tier: str
    per_ft: float
    hardware: float
    minimum: float
    lights_cost: float
    poles_cost: float = 0
    raw_total: float
    total: float
    min_applied: bool
    ordered_ft: float
    installations: list[BistroInstallationPricing] = Field(default_factory=list)
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


class PermanentKitSelection(BaseModel):
    """Procurement-safe permanent-light kit quantity selected by the pricer."""

    feet: int = Field(gt=0)
    quantity: int = Field(gt=0)


class PermanentPricing(BaseModel):
    """Computed kit-based permanent-lighting price + component breakdown."""

    feet: float
    channels: int
    package_feet: int
    package_cogs: float
    markup: float
    # Exact kit composition is structural procurement metadata, never parsed
    # back out of the customer-facing display line.
    selected_kits: list[PermanentKitSelection] = Field(default_factory=list)
    # Deprecated display fields retained for API compatibility; package pricing
    # never derives the sale from a per-foot or controller rate.
    per_ft: float = 0
    roofline_cost: float = 0
    controller_cost: float = 0
    channels_cost: float = 0
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


# --------------------------------------------------------------------------- #
# The presentation contract every priced package satisfies
# --------------------------------------------------------------------------- #
@runtime_checkable
class PackagePricing(Protocol):
    """Structural type of a priced package, as the *presentation layer* sees it.

    Everything a good/better/best card needs and nothing more. Seasonal
    (:class:`ChristmasPackagePricing`) and non-seasonal
    (:class:`ServicePackagePricing`) packages price through completely different
    engines but present identically, so the public mapping in
    :mod:`app.services.quotes.quote_service` is written once against this
    protocol rather than once per trade.

    Two members are deliberately *derived*, not raw fields:

    * ``total`` is the single money figure a homeowner may see. The full pricing
      breakdown behind it carries the measurement (``roofline_feet`` and
      friends) and is not part of this contract — a card built from a
      ``PackagePricing`` structurally cannot leak one.
    * ``includes`` is the category-agnostic form of the ``includes_*`` flags
      (seasonal: ``{"roofline": bool}``), so presentation can ask what a tier
      covers without knowing which trade it belongs to.

    Structural, not inherited: implementations stay plain Pydantic models whose
    serialized shape (and therefore every saved link) is unaffected by this
    protocol existing.
    """

    @property
    def key(self) -> str: ...

    @property
    def label(self) -> str: ...

    @property
    def name(self) -> str | None: ...

    @property
    def marker(self) -> str | None: ...

    @property
    def experience(self) -> str | None: ...

    @property
    def points(self) -> list[str]: ...

    @property
    def value_tag(self) -> str | None: ...

    @property
    def popular(self) -> bool: ...

    @property
    def recommended(self) -> bool: ...

    @property
    def total(self) -> float: ...

    @property
    def includes(self) -> Mapping[str, bool]: ...


class ChristmasPackagePricing(BaseModel):
    """One priced seasonal-Christmas package (a tier card + its computed price).

    ``pricing`` is the standard :class:`ChristmasPricing` breakdown for this
    package's included categories (+ roofline when ``includes_roofline``), so the
    display lines and totals reuse the same engine as the à la carte flow. The
    copy fields mirror :class:`ChristmasPackage` for the Good/Better/Best card.

    Implements :class:`PackagePricing` through the three derived members below.
    They are properties, not fields, so ``model_dump()`` — and therefore every
    already-shared seasonal link — is byte-for-byte what it was before.
    """

    key: str
    label: str
    name: str | None = None
    marker: str | None = None
    experience: str | None = None
    points: list[str] = Field(default_factory=list)
    value_tag: str | None = None
    popular: bool = False
    includes_roofline: bool = False
    pricing: ChristmasPricing

    @property
    def total(self) -> float:
        """The one figure that may cross to the homeowner (never the breakdown)."""
        return self.pricing.total

    @property
    def recommended(self) -> bool:
        """Seasonal tiers never self-declare; the resolver steers to the most
        inclusive one instead. Kept constant so the seasonal highlight is exactly
        what it has always been."""
        return False

    @property
    def includes(self) -> Mapping[str, bool]:
        """Seasonal coverage in category-agnostic form."""
        return {"roofline": self.includes_roofline}


class ServiceInclusionCost(BaseModel):
    """Grossed cost of one scope item inside a computed service price."""

    key: str  # matches the ServiceInclusion key ("ice_shield", "ridge_vent", …)
    label: str
    cost: float


class ServicePricing(BaseModel):
    """Computed price + component breakdown for one service tier.

    The non-seasonal counterpart of :class:`ChristmasPricing`: ``lines`` is the
    authoritative display breakdown that sums to ``raw_total``, ``total`` applies
    the category's job minimum, and ``units`` is the measurement — internal, the
    same way ``roofline_feet`` is.
    """

    units: float
    unit_label: str
    base_cost: float
    units_cost: float
    inclusions: list[ServiceInclusionCost] = Field(default_factory=list)
    minimum: float
    raw_total: float
    total: float
    min_applied: bool
    lines: list[CategoryLine] = Field(default_factory=list)


class ServicePackagePricing(BaseModel):
    """One priced service tier (a card + its computed price).

    Implements :class:`PackagePricing`, so it renders through the exact same
    public mapping and the exact same cards as a seasonal package — that
    equivalence is the point of this module's refactor.
    """

    key: str
    label: str
    name: str | None = None
    marker: str | None = None
    experience: str | None = None
    points: list[str] = Field(default_factory=list)
    value_tag: str | None = None
    popular: bool = False
    recommended: bool = False
    service_category: str
    inclusion_keys: list[str] = Field(default_factory=list)
    pricing: ServicePricing

    @property
    def total(self) -> float:
        """The one figure that may cross to the homeowner (never the breakdown)."""
        return self.pricing.total

    @property
    def includes(self) -> Mapping[str, bool]:
        """Which scope items this tier covers, keyed by inclusion key."""
        return dict.fromkeys(self.inclusion_keys, True)


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
    upsell: UpsellConfig | None = None
    tier_order: list[str] | None = None
    tiers: list[TierConfig] | None = None
    care_plan: CarePlanConfig | None = None
    savings: SavingsConfig | None = None
    bistro: BistroConfig | None = None
    landscape: LandscapeConfig | None = None
    permanent: PermanentConfig | None = None
    christmas: ChristmasConfig | None = None
    service_packages: list[ServicePackageConfig] | None = None
    comparison_years: int | None = Field(default=None, ge=1, le=30)
    roofline_comparison_enabled: bool | None = None
    quote_validity_days: int | None = Field(default=None, ge=1, le=365)
