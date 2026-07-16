"""Roofline linear-feet estimator + permanent-vs-temporary comparison schemas.

Two boundaries live here:

* **Rep estimate** (authenticated tool) — the rep measures a roofline in *linear
  feet* on a photo and asks the server what we'd charge for permanent vs seasonal
  (Christmas) lighting. Feet is the only untrusted input; every dollar is computed
  server-side from the workspace pricing config, matching the "client totals are
  never trusted" rule of :mod:`app.services.quotes.proposal_pricing`.
* **Client comparison** (no-auth, token-keyed) — the safe, shareable payload the
  homeowner sees. It deliberately **excludes linear feet, per-foot rate, and zone
  counts**: the client sees prices and savings, never the internal measurement.
  Same discipline as :class:`app.schemas.proposal.PublicProposal` excluding costs
  and margins. There is intentionally no ``feet`` field on the public models so a
  leak is structurally impossible, not just omitted.
"""

from pydantic import BaseModel, Field

from app.schemas.pricing import (
    ChristmasPackagePricing,
    SeasonalItem,
    SeasonalItemCost,
)

# --------------------------------------------------------------------------- #
# Rep estimate (authenticated)
# --------------------------------------------------------------------------- #


class LinearFeetEstimateRequest(BaseModel):
    """A rep's measured roofline plus optional per-service knobs.

    ``feet`` is the measured linear footage; the optional flags let the rep model
    a fuller quote (permanent zones, seasonal takedown/storage) without leaving
    the estimator.

    ``per_ft_override`` and ``christmas_per_ft_override`` are **internal-only**
    adjustments to the permanent and seasonal linear-foot rates for *this*
    estimate. They let a rep tune the $/ft for one job without editing the
    workspace's customer-facing pricing config, and are never serialized to the
    client comparison (the public schema has no per-foot field). ``None`` on
    either means "use the standard configured rate" for that side.
    """

    feet: float = Field(ge=0)
    channels: int = Field(default=0, ge=0)  # permanent zones
    takedown: bool = False  # christmas post-season takedown
    storage: bool = False  # christmas off-season storage
    per_ft_override: float | None = Field(default=None, ge=0)  # INTERNAL permanent rate
    christmas_per_ft_override: float | None = Field(default=None, ge=0)  # INTERNAL seasonal rate
    # Seasonal decor selection: category key -> {option key -> value}. Value is a
    # count for ``each`` items (trees/bushes/wreaths) and linear feet for
    # ``per_ft`` items (garland). Empty => roofline-only seasonal pricing.
    christmas_items: dict[str, dict[str, float]] = Field(default_factory=dict)
    # Optional seasonal package selection (a ``ChristmasPackage.key``). When the
    # workspace sells Christmas as Good/Better/Best packages, this records which
    # tier the client chose so the shared comparison echoes that package's total.
    # ``None`` => à la carte seasonal pricing (the standard roofline + decor flow).
    selected_package: str | None = None


class PermanentEstimate(BaseModel):
    """Permanent-lighting side of the estimate (rep view — includes per_ft)."""

    enabled: bool
    total: float
    per_ft: float


class ChristmasEstimate(BaseModel):
    """Seasonal-lighting side of the estimate (rep view — includes per_ft).

    ``items`` is the priced decor breakdown (one entry per selected category) so
    the rep can see what makes up the seasonal total.
    """

    enabled: bool
    total: float
    per_ft: float
    items: list[SeasonalItemCost] = Field(default_factory=list)


class LinearFeetEstimateResult(BaseModel):
    """Full estimate for the rep tool. ``feet`` is INTERNAL and never shared.

    ``difference`` is the single-season price gap; the multi-year block projects
    seasonal (temporary) cost over ``years`` seasons against permanent's one-time
    cost, which is the real "pay once vs every season" savings pitch.
    """

    feet: float  # INTERNAL — rep tool only, never serialized to the client page
    permanent: PermanentEstimate
    christmas: ChristmasEstimate
    difference: float
    years: int
    temporary_multi_year: float
    permanent_one_time: float
    multi_year_savings: float
    permanent_perks: list[str] = Field(default_factory=list)
    christmas_perks: list[str] = Field(default_factory=list)
    # The workspace's seasonal decor catalog (feet-free, safe) so the rep tool
    # can render add-on controls without a second request.
    christmas_catalog: list[SeasonalItem] = Field(default_factory=list)
    # Priced Good/Better/Best seasonal packages, populated only when the workspace
    # enables Christmas packages (``christmas.packages_enabled``). Feet-free like
    # the à la carte breakdown; the rep tool renders one tier card per package
    # from the shared engine's totals. Empty when packages are off.
    christmas_packages: list[ChristmasPackagePricing] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Share (persist a comparison, return a client link)
# --------------------------------------------------------------------------- #


class ComparisonShareRequest(LinearFeetEstimateRequest):
    """Persist an estimate behind a token so the homeowner can view the savings.

    ``client_email`` / ``client_phone`` are optional: when provided, the estimate
    is saved onto a CRM customer (resolve-or-create by phone/email, same dedupe
    rules as the sales wizard). Without a phone the estimate is still shared, just
    not attached to a contact — contacts in this CRM are phone-keyed.
    """

    client_name: str | None = Field(default=None, max_length=200)
    client_email: str | None = Field(default=None, max_length=320)
    client_phone: str | None = Field(default=None, max_length=40)
    label: str | None = Field(default=None, max_length=200)


class ComparisonShareResult(BaseModel):
    """The share token plus the ready-to-send client URL.

    ``contact_id`` is set when the estimate was saved onto a CRM customer;
    ``saved_to_customer`` is a convenience flag for the rep tool to confirm the
    link without inspecting the id.
    """

    token: str
    url: str
    contact_id: int | None = None
    saved_to_customer: bool = False


class ComparisonDeliverRequest(BaseModel):
    """Email a saved estimate's client link to the customer.

    ``to`` overrides the destination; otherwise the linked contact's email is
    used. Contacts are phone-keyed, so an estimate saved without a phone has no
    contact email — pass ``to`` explicitly in that case.
    """

    to: str | None = Field(default=None, max_length=320)


class ComparisonDeliverResult(BaseModel):
    """Outcome of emailing an estimate to the customer."""

    ok: bool
    to: str


# --------------------------------------------------------------------------- #
# Public client comparison (no-auth, token-keyed) — NO linear feet
# --------------------------------------------------------------------------- #


class PublicPermanentComparison(BaseModel):
    """Permanent side as the client sees it — price only, no per-foot rate."""

    enabled: bool
    total: float


class PublicChristmasComparison(BaseModel):
    """Seasonal side as the client sees it."""

    enabled: bool
    total: float


class PublicComparison(BaseModel):
    """Read-only, safe-fields-only comparison for the public token page.

    Intentionally carries **no** ``feet``, ``per_ft``, or ``channels`` — the client
    sees prices, the difference, the multi-year savings, and the perks of each
    option, never the internal measurement that produced them.
    """

    business_name: str
    brand_color: str
    accent_color: str
    logo_url: str | None = None
    client_name: str | None = None
    currency: str = "USD"
    permanent: PublicPermanentComparison
    christmas: PublicChristmasComparison
    difference: float
    years: int
    temporary_multi_year: float
    permanent_one_time: float
    multi_year_savings: float
    permanent_perks: list[str] = Field(default_factory=list)
    christmas_perks: list[str] = Field(default_factory=list)
