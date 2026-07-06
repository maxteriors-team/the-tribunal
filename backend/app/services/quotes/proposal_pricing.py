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
from decimal import ROUND_HALF_UP, Decimal

from app.schemas.pricing import (
    BistroConfig,
    BistroLine,
    BistroPricing,
    CarePlanPricing,
    CarePlanTier,
    CategoryLine,
    ChristmasPricing,
    PermanentPricing,
    PricingSettings,
    SizeRate,
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
    """Estimated 0% APR monthly payment; 0 when disabled or over the cap."""
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
# Christmas (seasonal) — roofline + trees/bushes/wreaths + takedown/storage
# --------------------------------------------------------------------------- #
def _price_size_group(
    rates: list[SizeRate],
    counts: dict[str, float],
    config: PricingSettings,
) -> tuple[Decimal, Decimal, list[CategoryLine]]:
    """Gross each selected size line; return (net_subtotal, grossed_subtotal, lines)."""
    by_key = {r.key: r for r in rates}
    net = _ZERO
    gross = _ZERO
    lines: list[CategoryLine] = []
    for key, qty in counts.items():
        rate = by_key.get(key)
        q = max(0.0, float(qty or 0))
        if rate is None or q <= 0:
            continue
        net += _d(q) * _d(rate.price)
        line_total = gross_up_price(_d(q) * _d(rate.price), config)
        gross += line_total
        lines.append(_category_line(rate.name, q, line_total))
    return net, gross, lines


def price_christmas(
    config: PricingSettings,
    *,
    roofline_feet: float = 0,
    trees: dict[str, float] | None = None,
    bushes: dict[str, float] | None = None,
    wreaths: dict[str, float] | None = None,
    takedown: bool = False,
    storage: bool = False,
) -> ChristmasPricing:
    """Price a seasonal Christmas job.

    Roofline, each tree/bush/wreath size, takedown, and storage are grossed up
    individually so the display lines sum exactly to ``raw_total``. Takedown is a
    fraction of the *net* install subtotal (roofline + decor) then grossed.
    """
    c = config.christmas
    ft = max(0.0, roofline_feet or 0.0)
    gross_minimum = gross_up_price(_d(c.minimum), config)

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

    trees_net, trees_cost, tree_lines = _price_size_group(c.tree_rates, trees or {}, config)
    bushes_net, bushes_cost, bush_lines = _price_size_group(c.bush_rates, bushes or {}, config)
    wreaths_net, wreaths_cost, wreath_lines = _price_size_group(
        c.wreath_rates, wreaths or {}, config
    )
    lines.extend(tree_lines)
    lines.extend(bush_lines)
    lines.extend(wreath_lines)

    install_net = roofline_net + trees_net + bushes_net + wreaths_net
    takedown_net = install_net * _d(c.takedown_rate) if (takedown and c.takedown_enabled) else _ZERO
    takedown_cost = gross_up_price(takedown_net, config)
    if takedown_cost > 0:
        lines.append(_category_line("Post-season takedown", 1, takedown_cost))
    storage_cost = gross_up_price(_d(c.storage_price), config) if storage else _ZERO
    if storage_cost > 0:
        lines.append(_category_line("Off-season storage", 1, storage_cost))

    raw_total = (
        roofline_cost + trees_cost + bushes_cost + wreaths_cost + takedown_cost + storage_cost
    )
    total = max(raw_total, gross_minimum) if raw_total > 0 else _ZERO
    return ChristmasPricing(
        roofline_feet=ft,
        roofline_cost=float(roofline_cost),
        trees_cost=float(trees_cost),
        bushes_cost=float(bushes_cost),
        wreaths_cost=float(wreaths_cost),
        takedown_cost=float(takedown_cost),
        storage_cost=float(storage_cost),
        minimum=float(gross_minimum),
        raw_total=float(raw_total),
        total=float(total),
        min_applied=raw_total < gross_minimum,
        lines=lines,
    )
