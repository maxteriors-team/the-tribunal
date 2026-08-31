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

import base64
import binascii
import uuid
from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.pricing import (
    ChristmasPackagePricing,
    SeasonalItem,
    SeasonalItemCost,
)
from app.schemas.proposal_wizard import MAX_PROPOSAL_MOCKUP_IMAGE_CHARS

# --------------------------------------------------------------------------- #
# Rep estimate (authenticated)
# --------------------------------------------------------------------------- #


class EstimateCustomLine(BaseModel):
    """A standalone line the rep adds to an estimate, outside any package.

    The price book and the Good/Better/Best packages cover the work we sell every
    day; this covers the rest — a bucket-truck fee, hand-tying garland on a
    balcony, removing the last company's clips. By default it is **independent
    of packages**: the amount rides on top of whichever tier the customer picks
    (and on top of à la carte pricing), so a rep never has to fake it into a
    decor category or edit the workspace's pricing config to land one job.

    ``unit_price`` is the *client-facing* amount, not a net cost: unlike catalog
    and roofline pricing it is not grossed up, because the rep is typing what the
    homeowner will pay. That makes it the one figure on the estimate the server
    doesn't derive — it is quantity × price, rounded, and nothing more.

    ``side`` says which half of the comparison the line belongs to, since the two
    are paid on different clocks: ``permanent`` is one-time, ``seasonal`` recurs
    every season and is projected over the comparison horizon like the rest of
    the seasonal total. A line assigned to a side the workspace doesn't offer is
    priced into a total that stays zero — same as every other input for a
    disabled service — so the rep tool only ever offers the enabled sides.

    ``package_key`` optionally pins the line **inside one tier**, for the case the
    global default can't express: a bucket-truck day the Best install needs and
    Good doesn't. Three rules, and the default is the one that has always been:

    * ``None`` (default) — global. Rides on top of whichever tier the client
      picks, reported in that side's ``custom_total``, in no package card.
    * a priced package's key — priced **inside that card's own total** and
      nowhere else, so switching tiers re-prices and the line follows the tier it
      was sold with. Deliberately excluded from ``custom_total`` (which the
      client page adds *on top of* a package total) so it can't be billed twice.
    * a key no priced package matches — **dropped**, same as a line assigned to a
      disabled service. Quietly falling back to global would move money the rep
      never asked to move.
    """

    label: str = Field(min_length=1, max_length=120)
    quantity: float = Field(default=1, gt=0, le=10_000)
    unit_price: float = Field(ge=0, le=1_000_000)
    side: Literal["permanent", "seasonal"] = "seasonal"
    description: str | None = Field(default=None, max_length=300)
    package_key: str | None = Field(default=None, max_length=60)


class EstimateCustomLineCost(EstimateCustomLine):
    """A priced standalone line: the input plus its server-computed ``amount``."""

    amount: float


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
    proposal_side: Literal["permanent", "seasonal", "comparison"] = "comparison"
    discount_amount: float = Field(default=0, ge=0, le=1_000_000)
    # Percentage alternative to ``discount_amount``. Resolved to dollars during
    # pricing and returned as ``discount_amount``, so nothing downstream stores a
    # percentage and a later price change cannot re-scale a quoted discount.
    # Takes precedence when both are supplied.
    discount_percent: float | None = Field(default=None, ge=0, le=100)
    # Gable pitch is corrected into ``feet`` upstream (a sloped rake is simply
    # longer), so complexity here is purely the labor/COGS markup tier.
    permanent_complexity: Literal["easy", "standard", "complex"] = "standard"
    permanent_complexity_feet: dict[Literal["easy", "standard", "complex"], float] = Field(
        default_factory=dict
    )
    per_ft_override: float | None = Field(default=None, ge=0)  # deprecated, ignored
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
    # Standalone rep-entered lines, added on top of the priced side they belong
    # to. A line without a ``package_key`` is never folded into a package's own
    # total — that card shows exactly what the package costs, whatever else is
    # on the estimate; a line that names a tier is priced inside that card only.
    # Capped so one request can't carry an unbounded breakdown onto the public page.
    custom_lines: list[EstimateCustomLine] = Field(default_factory=list, max_length=20)


class PermanentEstimate(BaseModel):
    """Permanent-lighting estimate using the kit that covers measured footage."""

    enabled: bool
    total: float
    subtotal: float = 0
    package_feet: int = 0
    package_cogs: float = 0
    markup: float = 0
    # Deprecated response field retained for older estimator clients.
    per_ft: float = 0
    roofline_cost: float = 0
    custom_total: float = 0


class ChristmasEstimate(BaseModel):
    """Seasonal-lighting side of the estimate (rep view — includes per_ft).

    ``items`` is the priced decor breakdown (one entry per selected category) so
    the rep can see what makes up the seasonal total. ``roofline_cost`` is the
    roofline-only component of ``total`` (no decor, takedown, or storage) — the
    like-for-like counterpart to :attr:`PermanentEstimate.roofline_cost`.
    """

    enabled: bool
    total: float
    subtotal: float = 0
    per_ft: float
    roofline_cost: float = 0
    custom_total: float = 0
    items: list[SeasonalItemCost] = Field(default_factory=list)


class LinearFeetEstimateResult(BaseModel):
    """Full estimate for the rep tool. ``feet`` is INTERNAL and never shared.

    ``difference`` is the single-season price gap; the multi-year block projects
    seasonal (temporary) cost over ``years`` seasons against permanent's one-time
    cost, which is the real "pay once vs every season" savings pitch.
    """

    feet: float  # INTERNAL — rep tool only, never serialized to the client page
    proposal_side: Literal["permanent", "seasonal", "comparison"] = "comparison"
    discount_amount: float = Field(default=0, ge=0)
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
    #
    # A package total covers that package's own scope plus any standalone line
    # scoped to it: global lines are added to ``christmas.total`` (and reported
    # in ``custom_total``), never into a card, so switching tier changes exactly
    # one number — while a tier-scoped line moves with the tier that sold it.
    christmas_packages: list[ChristmasPackagePricing] = Field(default_factory=list)
    # The rep's standalone lines with their computed amounts, in request order.
    # Includes tier-scoped lines (each carrying its ``package_key``) so the rep
    # panel can read them under the card whose total already contains them.
    custom_lines: list[EstimateCustomLineCost] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# AI night render (authenticated) — turn a drawn design into a photoreal photo
# --------------------------------------------------------------------------- #


class EstimateRenderRequest(BaseModel):
    """A composited design image to turn into a photorealistic night render.

    ``image`` is the rep's drawn lighting design flattened over the customer
    photo, as a base64 ``data:`` URL (PNG/JPEG/WebP). ``mode`` picks the product
    line's prompt (seasonal, permanent, or landscape) so a landscape design is
    never rendered back to the homeowner as a holiday installation; ``prompt``
    optionally overrides it. This boundary carries
    **no dollars and no feet** — it only transforms an image via the workspace's
    OpenAI credential, server-side, so the browser never handles a key.
    """

    image: str = Field(min_length=1, description="base64 data URL of the composited design")
    mode: Literal["seasonal", "permanent", "landscape"] = "seasonal"
    prompt: str | None = Field(default=None, max_length=1000)


class EstimateRenderResult(BaseModel):
    """The photorealistic render as a base64 ``data:`` image URL."""

    image: str


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


class EstimateProposalPreview(BaseModel):
    """A bounded, rasterized customer-photo preview tied to one saved project shot."""

    shot_id: str = Field(min_length=1, max_length=100)
    image: str = Field(min_length=1, max_length=MAX_PROPOSAL_MOCKUP_IMAGE_CHARS)

    @field_validator("image")
    @classmethod
    def validate_raster_data_url(cls, value: str) -> str:
        header, separator, encoded = value.partition(",")
        if separator != "," or header not in {
            "data:image/jpeg;base64",
            "data:image/png;base64",
            "data:image/webp;base64",
        }:
            raise ValueError("Preview must be a JPEG, PNG, or WebP data URL")
        try:
            image = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Preview image must contain valid base64 data") from exc
        matches_declared_type = (
            header == "data:image/jpeg;base64"
            and image.startswith(b"\xff\xd8\xff")
            or header == "data:image/png;base64"
            and image.startswith(b"\x89PNG\r\n\x1a\n")
            or header == "data:image/webp;base64"
            and len(image) >= 12
            and image.startswith(b"RIFF")
            and image[8:12] == b"WEBP"
        )
        if not matches_declared_type:
            raise ValueError("Preview image bytes do not match the declared raster type")
        return value


class EstimateQuoteRequest(ComparisonShareRequest):
    """Convert a measured estimate into a real draft quote.

    Reuses the estimate inputs (feet, decor, internal per-foot overrides, and the
    optional seasonal package) plus the client details from the share request,
    and adds ``side`` to choose which priced option becomes the quote: the
    one-time ``permanent`` install or the ``seasonal`` (Christmas) job. Every line
    is recomputed server-side from the workspace pricing config — the rep's
    measurements are the only untrusted input, exactly like the estimate itself.
    """

    side: Literal["permanent", "seasonal"] = "seasonal"
    deposit_percentage: float | None = Field(default=None, ge=0.01, le=100)
    lighting_project_id: uuid.UUID | None = None
    proposal_preview: EstimateProposalPreview | None = None

    @model_validator(mode="after")
    def permanent_quote_fields_are_consistent(self) -> Self:
        if self.side != "permanent" and self.deposit_percentage is not None:
            raise ValueError("A deposit percentage can only be added to a permanent quote")
        if self.proposal_preview is not None:
            if self.side != "permanent":
                raise ValueError("A proposal preview can only be added to a permanent quote")
            if self.lighting_project_id is None:
                raise ValueError("A proposal preview requires a saved lighting project")
        return self


class ComparisonDeliverRequest(BaseModel):
    """Send a saved estimate's client link to the customer by email or SMS.

    ``to`` overrides the destination; otherwise the linked contact's email or
    phone is used. Contacts are phone-keyed, so an estimate saved without a
    phone has no contact at all — pass ``to`` explicitly in that case.

    ``channel`` defaults to ``email`` so callers that predate SMS delivery keep
    working unchanged.
    """

    channel: Literal["email", "sms"] = "email"
    to: str | None = Field(default=None, max_length=320)


class ComparisonDeliverResult(BaseModel):
    """Outcome of sending an estimate to the customer."""

    ok: bool
    channel: Literal["email", "sms"] = "email"
    to: str


# --------------------------------------------------------------------------- #
# Public client comparison (no-auth, token-keyed) — NO linear feet
# --------------------------------------------------------------------------- #


class PublicPermanentComparison(BaseModel):
    """Permanent side as the client sees it — price only, no per-foot rate."""

    enabled: bool
    total: float
    subtotal: float = 0


class PublicChristmasComparison(BaseModel):
    """Seasonal side as the client sees it."""

    enabled: bool
    total: float
    subtotal: float = 0


class PublicComparisonPackage(BaseModel):
    """One seasonal Good/Better/Best package as the client sees it — feet-free.

    The public analog of :class:`app.schemas.pricing.ChristmasPackagePricing`: it
    carries the card copy plus the single computed ``total`` only, and
    deliberately **omits** the full :class:`app.schemas.pricing.ChristmasPricing`
    breakdown (which includes ``roofline_feet`` / ``roofline_cost``). A
    measurement therefore cannot reach the homeowner — the same feet-privacy
    contract as the rest of this module, enforced by construction.

    ``recommended`` flags the package the rep is steering the client toward (their
    explicit pick, else the most-inclusive tier) so one card can be highlighted
    without gating the others.
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
    total: float
    recommended: bool = False


class PublicComparisonLine(BaseModel):
    """One standalone add-on as the client sees it — what it is and what it costs.

    Shown rather than folded silently into a headline: an unexplained bump in the
    price is the fastest way to lose a signature. Feet-free like every public
    model here — the label is the rep's own words, and ``amount`` is the computed
    line total, never a rate or a measurement.
    """

    label: str
    description: str | None = None
    quantity: float = 1
    amount: float
    side: Literal["permanent", "seasonal"] = "seasonal"


class PublicRooflineComparison(BaseModel):
    """Roofline-only, like-for-like cost comparison for the public page.

    The headline seasonal total can include decor (trees/bushes/wreaths), which
    makes it apples-to-oranges against permanent's roofline track. This block is
    the honest version: permanent's one-time roofline install cost vs the
    seasonal roofline cost per season, projected over the configured horizon.

    Feet-free by construction like every other public model here — costs only,
    never the measurement that produced them. Present only when the workspace
    enables ``roofline_comparison_enabled`` and both sides are offered.
    """

    permanent_total: float  # one-time roofline install
    seasonal_total: float  # roofline only, per season
    seasonal_multi_year: float  # seasonal_total × years
    savings: float  # seasonal_multi_year - permanent_total


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
    proposal_side: Literal["permanent", "seasonal", "comparison"] = "comparison"
    discount_amount: float = Field(default=0, ge=0)
    # True once the client has told us they are out, so the page can stop
    # offering a decision it already has. The reason they gave is deliberately
    # not echoed back: it is feedback for the rep, not copy for the client.
    is_declined: bool = False
    permanent: PublicPermanentComparison
    christmas: PublicChristmasComparison
    difference: float
    years: int
    temporary_multi_year: float
    permanent_one_time: float
    multi_year_savings: float
    permanent_perks: list[str] = Field(default_factory=list)
    christmas_perks: list[str] = Field(default_factory=list)
    # Priced Good/Better/Best seasonal packages the client can compare, present
    # only when the workspace sells Christmas as packages. Feet-free (``total``
    # per package, never the roofline breakdown); empty for à la carte seasonal.
    christmas_packages: list[PublicComparisonPackage] = Field(default_factory=list)
    # Roofline-only cost comparison, present only when the workspace turns on
    # ``roofline_comparison_enabled`` and both sides are offered. ``None``
    # otherwise, so the client page renders exactly as it does today by default.
    roofline: PublicRooflineComparison | None = None
    # Standalone add-ons the rep put on this estimate, already included in the
    # totals above and itemized here so the client can see what they're paying
    # for. Empty for every estimate that has none — i.e. every existing link.
    custom_lines: list[PublicComparisonLine] = Field(default_factory=list)


class PublicComparisonDecline(BaseModel):
    """Client's optional “why not” when declining a shared estimate."""

    # Bounded to the column width so an accidental paste is rejected at the
    # boundary instead of being silently truncated deeper in.
    reason: str | None = Field(default=None, max_length=1000)


class PublicComparisonDeclineResult(BaseModel):
    """Confirmation that a decline was recorded."""

    token: str
    is_declined: bool
    message: str
