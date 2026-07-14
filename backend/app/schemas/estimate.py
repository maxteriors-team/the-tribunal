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

# --------------------------------------------------------------------------- #
# Rep estimate (authenticated)
# --------------------------------------------------------------------------- #


class LinearFeetEstimateRequest(BaseModel):
    """A rep's measured roofline plus optional per-service knobs.

    ``feet`` is the measured linear footage; the optional flags let the rep model
    a fuller quote (permanent zones, seasonal takedown/storage) without leaving
    the estimator.

    ``per_ft_override`` is an **internal-only** adjustment to the permanent
    linear-foot rate for *this* estimate. It lets a rep tune the $/ft for one job
    without editing the workspace's customer-facing pricing config, and it is
    never serialized to the client comparison (the public schema has no per-foot
    field). ``None`` means "use the standard configured rate".
    """

    feet: float = Field(ge=0)
    channels: int = Field(default=0, ge=0)  # permanent zones
    takedown: bool = False  # christmas post-season takedown
    storage: bool = False  # christmas off-season storage
    per_ft_override: float | None = Field(default=None, ge=0)  # INTERNAL rate tweak


class PermanentEstimate(BaseModel):
    """Permanent-lighting side of the estimate (rep view — includes per_ft)."""

    enabled: bool
    total: float
    per_ft: float


class ChristmasEstimate(BaseModel):
    """Seasonal-lighting side of the estimate."""

    enabled: bool
    total: float


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


# --------------------------------------------------------------------------- #
# Share (persist a comparison, return a client link)
# --------------------------------------------------------------------------- #


class ComparisonShareRequest(LinearFeetEstimateRequest):
    """Persist an estimate behind a token so the homeowner can view the savings."""

    client_name: str | None = Field(default=None, max_length=200)
    label: str | None = Field(default=None, max_length=200)


class ComparisonShareResult(BaseModel):
    """The share token plus the ready-to-send client URL."""

    token: str
    url: str


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
