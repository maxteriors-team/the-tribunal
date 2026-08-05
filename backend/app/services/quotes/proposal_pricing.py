"""Server-side sales-proposal pricing math (pure, no I/O).

The single trustworthy home for every grossing/discount calculation the uploaded
landscape-lighting wizard did in JavaScript, ported 1:1 so the number the client
sees and the number stored can never drift. Driven entirely by a workspace's
:class:`~app.schemas.pricing.PricingSettings`, so a second lighting business gets
the identical engine with different config — no code fork.

Money is ``Decimal`` throughout (matches the ``Numeric`` columns on quotes /
invoices). Whole-dollar results use ``ROUND_HALF_UP`` to match JavaScript's
``Math.round`` for the positive amounts we deal with; per-unit/monthly figures
keep cents.

Ported reference (``Sales-tools/index.html``):
    priceBuffer / grossUpPrice / cashDiscountRate / cashPrice / commissionAmount
    monthlyPay / carePrice / careSavings / bistroCompute
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal

from app.schemas.pricing import (
    DEFAULT_FINANCING_DISCLAIMER,
    BistroConfig,
    BistroLine,
    BistroPricing,
    CarePlanPricing,
    CarePlanTier,
    CategoryLine,
    ChristmasPackage,
    ChristmasPackagePricing,
    ChristmasPricing,
    FinancingEstimate,
    PermanentPricing,
    PricingSettings,
    SeasonalItem,
    SeasonalItemCost,
    ServiceInclusionCost,
    ServicePackage,
    ServicePackageConfig,
    ServicePackagePricing,
    ServicePricing,
    TierPricing,
)

_ZERO = Decimal("0")
_ONE = Decimal("1")
_DOLLAR = Decimal("1")
_CENT = Decimal("0.01")
_MAX_BUFFER = Decimal("0.95")


def _d(value: float | int | Decimal | str) -> Decimal:
    """Coerce to ``Decimal`` via ``str`` so floats don't leak binary noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _round_dollar(value: Decimal) -> Decimal:
    """Round to a whole dollar (``Math.round`` parity for positive amounts)."""
    return value.quantize(_DOLLAR, rounding=ROUND_HALF_UP)


def _round_cent(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Back-end buffer + gross-up (priceBuffer / grossUpPrice)
# --------------------------------------------------------------------------- #
def commission_in_price(config: PricingSettings) -> bool:
    """Whether the rep commission is baked into every client price."""
    c = config.commission
    return bool(c.enabled and c.in_price and c.rate > 0)


def price_buffer(config: PricingSettings) -> Decimal:
    """Combined back-end buffer recovered from every financed price.

    The ~11% Wisetack dealer fee plus, when ``commission.in_price`` is on, the
    commission rate — clamped to ``[0, 0.95]``. Never shown to the client.
    """
    f = config.financing
    buf = _d(f.fee_buffer) if f.enabled else _ZERO
    com = _d(config.commission.rate) if commission_in_price(config) else _ZERO
    return max(_ZERO, min(_MAX_BUFFER, buf + com))


def gross_up_price(amount: float | Decimal, config: PricingSettings) -> Decimal:
    """Gross a net price up so the buffer is pre-absorbed: ``round(n / (1 - b))``.

    Returns the amount unchanged (no rounding) when the buffer is zero, matching
    the wizard's ``grossUpPrice``.
    """
    b = price_buffer(config)
    a = _d(amount)
    if b > 0:
        return _round_dollar(a / (_ONE - b))
    return a


# --------------------------------------------------------------------------- #
# Cash / check pricing (cashDiscountRate / cashPrice)
# --------------------------------------------------------------------------- #
def cash_reserve_rate(config: PricingSettings) -> Decimal:
    c = config.cash_discount
    return _d(c.card_reserve_rate) if (c.enabled and c.card_reserve_rate > 0) else _ZERO


def cash_discount_rate(config: PricingSettings) -> Decimal:
    """Discount off the posted (financed) price for cash/check.

    Backs out the Wisetack fee buffer while privately keeping the card reserve and
    (when baked in) the commission recovery:
        ``1 - (1 + reserve) * (1 - buf - com) / (1 - com)``
    """
    c = config.cash_discount
    if not c.enabled:
        return _ZERO
    f = config.financing
    buf = _d(f.fee_buffer) if f.enabled else _ZERO
    reserve = cash_reserve_rate(config)
    com = _d(config.commission.rate) if commission_in_price(config) else _ZERO
    rate = _ONE - ((_ONE + reserve) * (_ONE - buf - com) / (_ONE - com))
    return max(_ZERO, min(_ONE, rate))


def cash_price(total: float | Decimal, config: PricingSettings) -> Decimal:
    return _round_dollar(_d(total) * (_ONE - cash_discount_rate(config)))


def cash_savings(total: float | Decimal, config: PricingSettings) -> Decimal:
    return _round_dollar(_d(total) * cash_discount_rate(config))


# --------------------------------------------------------------------------- #
# Commission (internal only)
# --------------------------------------------------------------------------- #
def commission_rate(config: PricingSettings) -> Decimal:
    c = config.commission
    return _d(c.rate) if (c.enabled and c.rate > 0) else _ZERO


def commission_amount(total: float | Decimal, config: PricingSettings) -> Decimal:
    return _round_dollar(_d(total) * commission_rate(config))


# --------------------------------------------------------------------------- #
# Financing (monthlyPay)
# --------------------------------------------------------------------------- #
def finance_terms(config: PricingSettings) -> list[int]:
    terms = config.financing.terms
    return list(terms) if terms else [24]


def monthly_payment(
    total: float | Decimal,
    config: PricingSettings,
    term: int | None = None,
) -> Decimal:
    """Estimated monthly payment; 0 when financing is disabled or over the cap."""
    f = config.financing
    t = _d(total)
    if not f.enabled or t <= 0:
        return _ZERO
    if t > _d(f.max_amount):
        return _ZERO
    n = term or f.default_term or finance_terms(config)[-1]
    r = _d(f.apr) / 12
    if r > 0:
        denom = _ONE - _d(math.pow(1 + float(r), -n))
        if denom == 0:
            return _ZERO
        return _round_cent(t * r / denom)
    return _round_cent(t / _d(n))


def financing_is_offered(config: PricingSettings) -> bool:
    """Whether this workspace offers financing on anything at all.

    Quote-independent counterpart to :func:`financing_is_eligible`, for copy that
    has to decide *before* there are line items to price — e.g. telling an
    operator to walk a customer through payment options. Clearing every category
    is how a workspace stops offering financing without touching
    :func:`price_buffer`, so an empty ``category_minimums`` reads as "not
    offered" even while ``enabled`` stays true to preserve the fee gross-up.
    """
    financing = config.financing
    return bool(financing.enabled and financing.category_minimums)


def financing_is_eligible(
    total: float | Decimal,
    category_totals: Mapping[str, float | Decimal],
    config: PricingSettings,
) -> bool:
    """Whether a quote qualifies for an estimated financing presentation.

    A category qualifies when its own subtotal reaches that category's
    configured minimum *and* the quote total clears the same floor. The overall
    total must also fit beneath the provider cap. This presentation gate is
    intentionally separate from :func:`price_buffer`: category settings can hide
    a noisy payment estimate, but can never silently remove the
    margin-protecting fee gross-up.

    A minimum of ``0`` means "no floor", which is what preserves the historical
    lighting behavior exactly: before financing was category-aware, every quote
    on a financing-enabled workspace showed an estimate, including a landscape
    package with no priced fixtures sold purely through add-on charges. Those
    categories ship with a zero minimum, so they still qualify on a subtotal of
    ``0``; only a category with a *positive* floor has to earn its estimate.
    """
    financing = config.financing
    total_d = _d(total)
    if not financing.enabled or total_d <= 0 or total_d > _d(financing.max_amount):
        return False

    minimums = financing.category_minimums
    for raw_category, raw_subtotal in category_totals.items():
        category = str(raw_category).strip().lower()
        if category not in minimums:
            continue
        minimum_d = _d(minimums[category])
        if _d(raw_subtotal) >= minimum_d and total_d >= minimum_d:
            return True
    return False


def financing_estimate(
    total: float | Decimal,
    category_totals: Mapping[str, float | Decimal],
    config: PricingSettings,
) -> FinancingEstimate | None:
    """Build client-safe, server-computed payment estimates when eligible."""
    if not financing_is_eligible(total, category_totals, config):
        return None

    financing = config.financing
    terms = finance_terms(config)
    monthly_by_term = {term: float(monthly_payment(total, config, term=term)) for term in terms}
    default_payment = float(monthly_payment(total, config, term=financing.default_term))
    if default_payment <= 0:
        return None

    return FinancingEstimate(
        provider=financing.provider,
        terms=terms,
        default_term=financing.default_term,
        apr=financing.apr,
        monthly_payment=default_payment,
        monthly_by_term=monthly_by_term,
        headline=financing.headline,
        body=financing.body,
        points=list(financing.points),
        disclaimer=(financing.disclaimer or DEFAULT_FINANCING_DISCLAIMER),
    )


# --------------------------------------------------------------------------- #
# Tax (apply_tax)
# --------------------------------------------------------------------------- #
def tax_amount(subtotal: float | Decimal, config: PricingSettings) -> Decimal:
    """Tax on a subtotal per the configured method (0 when disabled).

    ``Exclusive`` adds tax on top; ``Inclusive`` extracts the tax already baked
    into the price.
    """
    tax = config.tax
    s = _d(subtotal)
    if not tax.enabled or tax.rate <= 0 or s <= 0:
        return _ZERO
    rate = _d(tax.rate)
    if tax.method == "Inclusive":
        return _round_cent(s - (s / (_ONE + rate)))
    return _round_cent(s * rate)


# --------------------------------------------------------------------------- #
# Tier pricing aggregate (updateTotals / renderPackages)
# --------------------------------------------------------------------------- #
def price_tier(
    base: float | Decimal,
    additional: float | Decimal,
    config: PricingSettings,
    *,
    term: int | None = None,
) -> TierPricing:
    """Aggregate one tier's financed/cash/monthly/commission figures.

    ``base`` and ``additional`` must already be grossed-up (fixture prices come
    from :func:`gross_up_price`); this only combines and discounts them.
    """
    base_d = _d(base)
    add_d = _d(additional)
    financed = base_d + add_d if base_d > 0 else base_d
    cash = cash_price(financed, config) if financed > 0 else _ZERO
    monthly_terms = {
        t: float(monthly_payment(financed, config, term=t)) for t in finance_terms(config)
    }
    default_term = term or config.financing.default_term
    return TierPricing(
        base=float(base_d),
        additional=float(add_d),
        financed_total=float(financed),
        cash_total=float(cash),
        cash_savings=float(cash_savings(financed, config) if financed > 0 else _ZERO),
        monthly_payment=float(monthly_payment(financed, config, term=default_term)),
        monthly_by_term=monthly_terms,
        commission_financed=float(commission_amount(financed, config)),
        commission_cash=float(commission_amount(cash, config)),
    )


# --------------------------------------------------------------------------- #
# Care Plan (carePrice / careSavings)
# --------------------------------------------------------------------------- #
def care_plan_price(tier: CarePlanTier, count: int, config: PricingSettings) -> Decimal:
    """``base + perFixture × max(0, count - freeFixtures)``."""
    free = config.care_plan.free_fixtures
    extra = max(0, count - free)
    return _d(tier.base) + _d(tier.per_fixture) * _d(extra)


def avoided_repair(count: int, config: PricingSettings) -> Decimal:
    return _round_dollar(_d(count) * _d(config.savings.avoided_repair_per_fixture))


def repair_spend(count: int, config: PricingSettings) -> Decimal:
    return _d(count) * _d(config.savings.assumed_repair_spend_per_fixture)


def care_plan_savings(tier: CarePlanTier, count: int, config: PricingSettings) -> Decimal:
    """First-year savings estimate for a Care Plan tier."""
    visits_value = _d(tier.visits) * _d(config.savings.per_visit_value)
    repair_part = _round_dollar(repair_spend(count, config) * _d(tier.repair_discount))
    return visits_value + avoided_repair(count, config) + repair_part


def price_care_plan(count: int, config: PricingSettings) -> list[CarePlanPricing]:
    """Price every Care Plan tier for a fixture count."""
    out: list[CarePlanPricing] = []
    for tier in config.care_plan.tiers:
        out.append(
            CarePlanPricing(
                key=tier.key,
                name=tier.name,
                price=float(care_plan_price(tier, count, config)),
                savings=float(care_plan_savings(tier, count, config)),
                visits=tier.visits,
                repair_discount=tier.repair_discount,
                blurb=tier.blurb,
                popular=tier.popular,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Bistro / string lighting (bistroCompute)
# --------------------------------------------------------------------------- #
def _bistro_strand_breakdown(feet: float, strand_lengths: list[int]) -> dict[int, int]:
    """Fill the run largest-first from pre-cut strands, top up the gap."""
    lengths = sorted(strand_lengths, reverse=True)
    counts: dict[int, int] = dict.fromkeys(lengths, 0)
    remaining = feet
    for length in lengths:
        if remaining <= 0:
            break
        n = math.floor(remaining / length)
        counts[length] = n
        remaining -= n * length
    if remaining > 0 and lengths:
        counts[lengths[-1]] += 1
    return counts


def price_bistro(
    config: PricingSettings,
    product: str,
    tier_key: str,
    feet: float,
) -> BistroPricing:
    """Port of ``bistroCompute`` — grossed-up bistro price with breakdown."""
    b: BistroConfig = config.bistro
    cfg = b.color if product == "color" else b.classic
    tier = next((t for t in b.tiers if t.key == tier_key), b.tiers[0] if b.tiers else None)
    per_ft = _ZERO
    if tier is not None:
        per_ft = _d(tier.classic_per_ft if product == "classic" else tier.per_ft)
    ft = max(0.0, feet or 0.0)
    hardware_net = _d(cfg.hardware) if cfg else _ZERO
    hardware = gross_up_price(hardware_net, config)
    gross_minimum = gross_up_price(_d(b.minimum), config)

    if cfg is None or ft <= 0:
        return BistroPricing(
            feet=0,
            product=product,
            tier=tier_key,
            per_ft=float(per_ft),
            hardware=float(hardware),
            minimum=float(gross_minimum),
            lights_cost=0,
            raw_total=0,
            total=0,
            min_applied=False,
            ordered_ft=0,
            lines=[],
        )

    lines: list[BistroLine] = []
    ordered_ft = ft
    if product == "color":
        strands = _bistro_strand_breakdown(ft, cfg.strand_lengths)
        ordered_ft = sum(length * strands[length] for length in cfg.strand_lengths)
        lights_cost_net = _d(ordered_ft) * per_ft
        for length in cfg.strand_lengths:
            if strands.get(length, 0) <= 0:
                continue
            lights = length // 2
            lines.append(
                BistroLine(
                    label=f"{length} ft strand ({lights} light{'s' if lights > 1 else ''})",
                    detail=(
                        f"{strands[length]} strand{'s' if strands[length] > 1 else ''} · "
                        f"{length * strands[length]} ft"
                    ),
                    qty=strands[length],
                    description=f"Minleon RGBW+2 {length} ft strand",
                )
            )
        if ordered_ft > ft:
            lines.append(
                BistroLine(
                    note=(
                        f"{ft:g} ft needed · {ordered_ft:g} ft in pre-cut strands · "
                        f"{ordered_ft - ft:g} ft buffer"
                    )
                )
            )
    else:
        min_footage = cfg.min_footage or 0
        eff_ft = max(ft, min_footage)
        ordered_ft = eff_ft
        lights_cost_net = _d(eff_ft) * per_ft
        spacing = cfg.bulb_spacing_ft or 2
        bulbs = round(eff_ft / spacing)
        lines.append(
            BistroLine(
                label=f"{eff_ft:g} linear ft · {bulbs} bulbs",
                detail=f"{min_footage} ft minimum applied" if eff_ft > ft else None,
            )
        )

    lights_cost = gross_up_price(lights_cost_net, config)
    raw_total = lights_cost + hardware
    total = max(raw_total, gross_minimum)
    return BistroPricing(
        feet=ft,
        product=product,
        tier=tier_key,
        per_ft=float(per_ft),
        hardware=float(hardware),
        minimum=float(gross_minimum),
        lights_cost=float(lights_cost),
        raw_total=float(raw_total),
        total=float(total),
        min_applied=raw_total < gross_minimum,
        ordered_ft=float(ordered_ft),
        lines=lines,
    )


# --------------------------------------------------------------------------- #
# Permanent holiday lighting (per-linear-ft roofline + controller/channels)
# --------------------------------------------------------------------------- #
def _category_line(
    label: str,
    quantity: float | Decimal,
    line_total: Decimal,
    *,
    detail: str | None = None,
) -> CategoryLine:
    """A grossed display line; unit price is total/qty (cents) for presentation."""
    q = _d(quantity)
    unit = _round_cent(line_total / q) if q > 0 else line_total
    return CategoryLine(
        label=label,
        detail=detail,
        quantity=float(q),
        unit_price=float(unit),
        line_total=float(line_total),
    )


def price_permanent(
    config: PricingSettings,
    *,
    feet: float,
    channels: int = 0,
) -> PermanentPricing:
    """Price a permanent-roofline job: grossed per-ft footage + controller + zones.

    Each component is grossed up individually (like bistro) so every displayed
    line total is authoritative and the lines sum exactly to ``raw_total``.
    """
    p = config.permanent
    per_ft = _d(p.per_ft)
    ft = max(0.0, feet or 0.0)
    ch = max(0, int(channels or 0))
    extra = max(0, ch - int(p.included_channels))
    gross_minimum = gross_up_price(_d(p.minimum), config)

    if ft <= 0:
        return PermanentPricing(
            feet=0,
            channels=ch,
            per_ft=float(per_ft),
            roofline_cost=0,
            controller_cost=0,
            channels_cost=0,
            minimum=float(gross_minimum),
            raw_total=0,
            total=0,
            min_applied=False,
            lines=[],
        )

    roofline_cost = gross_up_price(_d(ft) * per_ft, config)
    controller_cost = gross_up_price(_d(p.controller_base), config)
    channels_cost = gross_up_price(_d(extra) * _d(p.per_channel), config)

    lines: list[CategoryLine] = [
        _category_line(
            f"{ft:g} ft permanent roofline",
            ft,
            roofline_cost,
            detail="Permanent LED track, installed",
        )
    ]
    if controller_cost > 0:
        lines.append(
            _category_line(
                "Controller & app control",
                1,
                controller_cost,
                detail=f"Includes {p.included_channels} zone(s)" if p.included_channels else None,
            )
        )
    if extra > 0 and channels_cost > 0:
        lines.append(_category_line(f"{extra} additional zone(s)", extra, channels_cost))

    raw_total = roofline_cost + controller_cost + channels_cost
    total = max(raw_total, gross_minimum) if raw_total > 0 else _ZERO
    return PermanentPricing(
        feet=ft,
        channels=ch,
        per_ft=float(per_ft),
        roofline_cost=float(roofline_cost),
        controller_cost=float(controller_cost),
        channels_cost=float(channels_cost),
        minimum=float(gross_minimum),
        raw_total=float(raw_total),
        total=float(total),
        min_applied=raw_total < gross_minimum,
        lines=lines,
    )


# --------------------------------------------------------------------------- #
# Christmas (seasonal) — roofline + generic decor items + takedown/storage
# --------------------------------------------------------------------------- #
def _price_seasonal_item(
    item: SeasonalItem,
    selection: Mapping[str, float],
    config: PricingSettings,
) -> tuple[Decimal, Decimal, list[CategoryLine]]:
    """Gross each selected option of one decor category.

    ``each`` options price per selected item (value = quantity); ``per_ft``
    options price per linear foot of the measured run (value = feet). Returns
    ``(net_subtotal, grossed_subtotal, lines)`` so the caller can fold the net
    into the takedown base and the gross into the total.
    """
    by_key = {o.key: o for o in item.options}
    net = _ZERO
    gross = _ZERO
    lines: list[CategoryLine] = []
    for key, value in selection.items():
        option = by_key.get(key)
        v = max(0.0, float(value or 0))
        if option is None or v <= 0:
            continue
        line_net = _d(v) * _d(option.price)
        net += line_net
        line_total = gross_up_price(line_net, config)
        gross += line_total
        # per-ft categories read as "80 ft Garland"; each categories as the option name.
        label = f"{v:g} ft {option.name}" if item.unit == "per_ft" else option.name
        lines.append(_category_line(label, v, line_total))
    return net, gross, lines


def price_christmas(
    config: PricingSettings,
    *,
    roofline_feet: float = 0,
    items: Mapping[str, Mapping[str, float]] | None = None,
    takedown: bool = False,
    storage: bool = False,
) -> ChristmasPricing:
    """Price a seasonal Christmas job.

    Roofline, every configured decor category (trees/bushes/wreaths/garland/…),
    takedown, and storage are grossed up individually so the display lines sum
    exactly to ``raw_total``. ``items`` maps a category key to its selection
    (option key → quantity for ``each`` items, → linear feet for ``per_ft``).
    Takedown is a fraction of the *net* install subtotal (roofline + decor).
    """
    c = config.christmas
    ft = max(0.0, roofline_feet or 0.0)
    gross_minimum = gross_up_price(_d(c.minimum), config)
    selections = items or {}

    lines: list[CategoryLine] = []
    roofline_net = _d(ft) * _d(c.roofline_per_ft)
    roofline_cost = gross_up_price(roofline_net, config) if ft > 0 else _ZERO
    if roofline_cost > 0:
        lines.append(
            _category_line(
                f"{ft:g} ft roofline",
                ft,
                roofline_cost,
                detail="Seasonal C9/mini install",
            )
        )

    item_costs: list[SeasonalItemCost] = []
    decor_net = _ZERO
    decor_gross = _ZERO
    for item in c.items:
        net, gross, item_lines = _price_seasonal_item(item, selections.get(item.key) or {}, config)
        lines.extend(item_lines)
        decor_net += net
        decor_gross += gross
        if gross > 0:
            item_costs.append(
                SeasonalItemCost(key=item.key, label=item.label, unit=item.unit, cost=float(gross))
            )

    install_net = roofline_net + decor_net
    takedown_net = install_net * _d(c.takedown_rate) if (takedown and c.takedown_enabled) else _ZERO
    takedown_cost = gross_up_price(takedown_net, config)
    if takedown_cost > 0:
        lines.append(_category_line("Post-season takedown", 1, takedown_cost))
    storage_cost = gross_up_price(_d(c.storage_price), config) if storage else _ZERO
    if storage_cost > 0:
        lines.append(_category_line("Off-season storage", 1, storage_cost))

    raw_total = roofline_cost + decor_gross + takedown_cost + storage_cost
    total = max(raw_total, gross_minimum) if raw_total > 0 else _ZERO
    return ChristmasPricing(
        roofline_feet=ft,
        roofline_cost=float(roofline_cost),
        items=item_costs,
        takedown_cost=float(takedown_cost),
        storage_cost=float(storage_cost),
        minimum=float(gross_minimum),
        raw_total=float(raw_total),
        total=float(total),
        min_applied=raw_total < gross_minimum,
        lines=lines,
    )


# --------------------------------------------------------------------------- #
# Christmas packages (Good/Better/Best seasonal service tiers)
# --------------------------------------------------------------------------- #
def price_christmas_package(
    config: PricingSettings,
    package: ChristmasPackage,
    *,
    roofline_feet: float = 0,
    items: Mapping[str, Mapping[str, float]] | None = None,
    takedown: bool = False,
    storage: bool = False,
) -> ChristmasPricing:
    """Price one seasonal package: the shared engine restricted to its coverage.

    Only the decor categories in ``package.item_keys`` are priced, and the
    roofline run is included only when ``package.includes_roofline``. Everything
    else — gross-up, takedown (a fraction of *this package's* install subtotal),
    storage, and the job minimum — is delegated to :func:`price_christmas`, so a
    package is simply the à la carte price of its covered subset. No new math.
    """
    allowed = set(package.item_keys)
    selections = items or {}
    scoped = {k: v for k, v in selections.items() if k in allowed}
    feet = roofline_feet if package.includes_roofline else 0
    return price_christmas(
        config,
        roofline_feet=feet,
        items=scoped,
        takedown=takedown,
        storage=storage,
    )


def price_christmas_packages(
    config: PricingSettings,
    *,
    roofline_feet: float = 0,
    items: Mapping[str, Mapping[str, float]] | None = None,
    takedown: bool = False,
    storage: bool = False,
) -> list[ChristmasPackagePricing]:
    """Price every configured seasonal package in ``package_order`` (low→high).

    One roofline+decor measurement prices all packages; each card carries its own
    :class:`ChristmasPricing` for the covered subset. Falls back to the declared
    ``packages`` order when ``package_order`` is empty or partial.
    """
    c = config.christmas
    by_key = {p.key: p for p in c.packages}
    ordered_keys = [k for k in c.package_order if k in by_key]
    ordered_keys += [p.key for p in c.packages if p.key not in ordered_keys]
    out: list[ChristmasPackagePricing] = []
    for key in ordered_keys:
        package = by_key[key]
        pricing = price_christmas_package(
            config,
            package,
            roofline_feet=roofline_feet,
            items=items,
            takedown=takedown,
            storage=storage,
        )
        out.append(
            ChristmasPackagePricing(
                key=package.key,
                label=package.label,
                name=package.name,
                marker=package.marker,
                experience=package.experience,
                points=list(package.points),
                value_tag=package.value_tag,
                popular=package.popular,
                includes_roofline=package.includes_roofline,
                pricing=pricing,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Service packages (Good/Better/Best for roof, siding, gutters, …)
# --------------------------------------------------------------------------- #
def price_service_package(
    config: PricingSettings,
    category: ServicePackageConfig,
    package: ServicePackage,
    *,
    units: float = 0,
) -> ServicePricing:
    """Price one non-seasonal tier from the category's measurement basis.

    Deliberately the same shape as :func:`price_christmas`: every component is
    grossed up individually so the display ``lines`` sum exactly to ``raw_total``,
    and the category's job minimum lifts the final ``total`` the same way. What
    differs is only the *inputs* — a measured quantity and a tier rate instead of
    a roofline and decor selections.

    On a ``flat`` category the measurement is ignored entirely (the tier sells at
    ``base_price`` plus its flat inclusions), so an operator who prices whole jobs
    rather than by the square never has to invent a unit count.
    """
    per_unit_basis = category.basis == "per_unit"
    qty = max(0.0, units or 0.0) if per_unit_basis else 0.0
    gross_minimum = gross_up_price(_d(category.minimum), config)

    lines: list[CategoryLine] = []
    base_cost = gross_up_price(_d(package.base_price), config) if package.base_price > 0 else _ZERO
    if base_cost > 0:
        lines.append(_category_line(package.label, 1, base_cost, detail=category.label))

    units_net = _d(qty) * _d(package.per_unit_price)
    units_cost = gross_up_price(units_net, config) if units_net > 0 else _ZERO
    if units_cost > 0:
        lines.append(_category_line(f"{qty:g} {category.unit_label}", qty, units_cost))

    covered = set(package.inclusion_keys)
    inclusion_costs: list[ServiceInclusionCost] = []
    inclusions_gross = _ZERO
    for inclusion in category.inclusions:
        if inclusion.key not in covered:
            continue
        # A per-unit scope item on a flat category contributes nothing rather
        # than silently billing against a measurement the operator never took.
        quantity = qty if inclusion.per_unit else 1.0
        net = _d(quantity) * _d(inclusion.price)
        if net <= 0:
            continue
        cost = gross_up_price(net, config)
        inclusions_gross += cost
        label = (
            f"{quantity:g} {category.unit_label} {inclusion.label}"
            if inclusion.per_unit
            else inclusion.label
        )
        lines.append(_category_line(label, quantity, cost))
        inclusion_costs.append(
            ServiceInclusionCost(key=inclusion.key, label=inclusion.label, cost=float(cost))
        )

    raw_total = base_cost + units_cost + inclusions_gross
    total = max(raw_total, gross_minimum) if raw_total > 0 else _ZERO
    return ServicePricing(
        units=qty,
        unit_label=category.unit_label,
        base_cost=float(base_cost),
        units_cost=float(units_cost),
        inclusions=inclusion_costs,
        minimum=float(gross_minimum),
        raw_total=float(raw_total),
        total=float(total),
        min_applied=raw_total < gross_minimum,
        lines=lines,
    )


def price_service_packages(
    config: PricingSettings,
    service_category: str,
    *,
    units: float = 0,
) -> list[ServicePackagePricing]:
    """Price every tier of one service category in ``package_order`` (low→high).

    Returns ``[]`` for an unknown or disabled category, which is what every
    workspace that has not configured one gets — the same "empty ladder means à
    la carte" contract :func:`price_christmas_packages` already has. Category
    lookup is case-insensitive because ``service_category`` is free-form text an
    operator types (``"Gutters"`` and ``"gutters"`` are one category).
    """
    wanted = (service_category or "").strip().casefold()
    category = next(
        (
            c
            for c in config.service_packages
            if c.enabled and c.service_category.strip().casefold() == wanted
        ),
        None,
    )
    if category is None or not wanted:
        return []

    by_key = {p.key: p for p in category.packages}
    ordered_keys = [k for k in category.package_order if k in by_key]
    ordered_keys += [p.key for p in category.packages if p.key not in ordered_keys]
    return [
        ServicePackagePricing(
            key=by_key[key].key,
            label=by_key[key].label,
            name=by_key[key].name,
            marker=by_key[key].marker,
            experience=by_key[key].experience,
            points=list(by_key[key].points),
            value_tag=by_key[key].value_tag,
            popular=by_key[key].popular,
            recommended=by_key[key].recommended,
            service_category=category.service_category,
            inclusion_keys=list(by_key[key].inclusion_keys),
            pricing=price_service_package(config, category, by_key[key], units=units),
        )
        for key in ordered_keys
    ]
