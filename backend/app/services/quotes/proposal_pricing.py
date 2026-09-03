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
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.schemas.pricing import (
    DEFAULT_FINANCING_DISCLAIMER,
    GREEN_SKY_REQUIRED_DISCLOSURE,
    BistroConfig,
    BistroInstallation,
    BistroInstallationPricing,
    BistroLine,
    BistroPricing,
    CarePlanPricing,
    CarePlanTier,
    CategoryLine,
    ChristmasPackage,
    ChristmasPackagePricing,
    ChristmasPricing,
    FinancingEstimate,
    PermanentKitSelection,
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
_MARGIN = Decimal("0.0001")


@dataclass(frozen=True)
class PermanentProfitabilityCalculation:
    """Private Permanent Lighting contribution math for one payment method."""

    contract_price: Decimal
    merchant_fee: Decimal
    sales_commission: Decimal
    material_cogs: Decimal
    contribution_before_labor: Decimal
    contribution_margin: Decimal


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
# Legacy pricing adapters (all configured amounts are direct selling prices)
# --------------------------------------------------------------------------- #
def commission_in_price(config: PricingSettings) -> bool:
    """Legacy adapter retained for callers; configured amounts are selling prices."""
    del config
    return False


def price_buffer(config: PricingSettings) -> Decimal:
    """Legacy adapter: financing fees no longer increase any customer price."""
    del config
    return _ZERO


def gross_up_price(amount: float | Decimal, config: PricingSettings) -> Decimal:
    """Return the configured selling price without legacy fee or commission buffers."""
    del config
    return _d(amount)


# --------------------------------------------------------------------------- #
# Cash / check pricing (cashDiscountRate / cashPrice)
# --------------------------------------------------------------------------- #
def cash_reserve_rate(config: PricingSettings) -> Decimal:
    """Legacy adapter: one-price quotes do not reserve card costs in cash pricing."""
    del config
    return _ZERO


def cash_discount_rate(config: PricingSettings) -> Decimal:
    """Legacy adapter: cash/check uses the same configured selling price."""
    del config
    return _ZERO


def cash_price(total: float | Decimal, config: PricingSettings) -> Decimal:
    del config
    return _d(total)


def cash_savings(total: float | Decimal, config: PricingSettings) -> Decimal:
    del total, config
    return _ZERO


# --------------------------------------------------------------------------- #
# Commission (internal only)
# --------------------------------------------------------------------------- #
def commission_rate(config: PricingSettings) -> Decimal:
    """Legacy adapter; Permanent commission comes from its snapshotted settings."""
    del config
    return _ZERO


def commission_amount(total: float | Decimal, config: PricingSettings) -> Decimal:
    del total, config
    return _ZERO


# --------------------------------------------------------------------------- #
# Financing (monthlyPay)
# --------------------------------------------------------------------------- #
def finance_terms(config: PricingSettings) -> list[int]:
    terms = config.financing.terms
    return list(terms) if terms else [24]


def amortized_monthly_payment(
    total: float | Decimal,
    *,
    apr: float | Decimal,
    term_months: int,
) -> Decimal:
    """Calculate a cent-rounded payment with Decimal, including nonzero APR."""
    if term_months < 1:
        raise ValueError("Financing term must be at least one month")
    principal = _d(total)
    if principal <= 0:
        return _ZERO
    monthly_rate = _d(apr) / 12
    if monthly_rate < 0:
        raise ValueError("APR cannot be negative")
    if monthly_rate == 0:
        return _round_cent(principal / term_months)
    denominator = _ONE - (_ONE + monthly_rate) ** -term_months
    if denominator == 0:
        return _ZERO
    return _round_cent(principal * monthly_rate / denominator)


def monthly_payment(
    total: float | Decimal,
    config: PricingSettings,
    term: int | None = None,
) -> Decimal:
    """Legacy top-level financing calculation retained for stored compatibility."""
    financing = config.financing
    principal = _d(total)
    if not financing.enabled or principal <= 0 or principal > _d(financing.max_amount):
        return _ZERO
    return amortized_monthly_payment(
        principal,
        apr=financing.apr,
        term_months=term or financing.default_term or finance_terms(config)[-1],
    )


def permanent_financing_estimate(
    total: float | Decimal, config: PricingSettings
) -> FinancingEstimate | None:
    """Build the sole customer financing estimate, for Permanent Lighting."""
    financing = config.permanent.financing
    payment = amortized_monthly_payment(total, apr=financing.apr, term_months=financing.term_months)
    if payment <= 0:
        return None
    return FinancingEstimate(
        provider=financing.provider,
        plan_number=financing.plan_number,
        terms=[financing.term_months],
        default_term=financing.term_months,
        apr=financing.apr,
        monthly_payment=float(payment),
        monthly_by_term={financing.term_months: float(payment)},
        disclaimer=GREEN_SKY_REQUIRED_DISCLOSURE,
    )


def permanent_profitability(
    contract_price: float | Decimal,
    *,
    material_cogs: float | Decimal,
    merchant_fee_rate: float | Decimal,
    sales_commission_rate: float | Decimal,
    financed: bool,
) -> PermanentProfitabilityCalculation:
    """Calculate private contribution before labor from snapshottable inputs."""
    price = _round_cent(_d(contract_price))
    cogs = _round_cent(_d(material_cogs))
    merchant_rate = _d(merchant_fee_rate)
    commission_rate_value = _d(sales_commission_rate)
    if price < 0 or cogs < 0:
        raise ValueError("Contract price and material COGS cannot be negative")
    if not _ZERO <= merchant_rate < _ONE:
        raise ValueError("Merchant fee rate must be between zero and one")
    if not _ZERO <= commission_rate_value < _ONE:
        raise ValueError("Sales commission rate must be between zero and one")
    merchant_fee = _round_cent(price * merchant_rate) if financed else _round_cent(_ZERO)
    sales_commission = _round_cent(price * commission_rate_value)
    contribution = _round_cent(price - merchant_fee - cogs - sales_commission)
    margin = (contribution / price).quantize(_MARGIN, rounding=ROUND_HALF_UP) if price else _ZERO
    return PermanentProfitabilityCalculation(
        contract_price=price,
        merchant_fee=merchant_fee,
        sales_commission=sales_commission,
        material_cogs=cogs,
        contribution_before_labor=contribution,
        contribution_margin=margin,
    )


def financing_is_offered(config: PricingSettings) -> bool:
    """Legacy global financing is never offered; Permanent uses its own terms."""
    del config
    return False


def financing_is_eligible(
    total: float | Decimal,
    category_totals: Mapping[str, float | Decimal],
    config: PricingSettings,
) -> bool:
    """Legacy category financing is disabled for every service."""
    del total, category_totals, config
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
    """Aggregate direct selling-price fields without legacy financing derivations."""
    del config, term
    base_d = _d(base)
    additional_d = _d(additional)
    total = base_d + additional_d if base_d > 0 else base_d
    return TierPricing(
        base=float(base_d),
        additional=float(additional_d),
        financed_total=float(total),
        cash_total=float(total),
        cash_savings=0,
        monthly_payment=0,
        monthly_by_term={},
        commission_financed=0,
        commission_cash=0,
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
class BistroPricingConfigurationError(ValueError):
    """Requested Bistro work cannot be priced from the workspace settings."""


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
    """Port of ``bistroCompute`` — direct bistro price with breakdown."""
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


def price_bistro_installations(
    config: PricingSettings,
    runs: Mapping[BistroInstallation, float],
    pole_counts: Mapping[BistroInstallation, int] | None = None,
) -> BistroPricing:
    """Price measured runs and explicitly marked poles from configured rates.

    Every requested installation must have both rates configured before any money
    is returned. Each component uses its configured selling price, and the Bistro
    minimum is applied once after every installation is summed.
    """
    bistro = config.bistro
    requested = {
        installation: max(0.0, feet)
        for installation, feet in runs.items()
        if installation in ("temporary", "permanent") and feet > 0
    }
    if not requested:
        return BistroPricing(
            pricing_mode="installation",
            feet=0,
            product="installation",
            tier="",
            per_ft=0,
            hardware=0,
            minimum=float(gross_up_price(bistro.minimum, config)),
            lights_cost=0,
            poles_cost=0,
            raw_total=0,
            total=0,
            min_applied=False,
            ordered_ft=0,
        )
    if not bistro.enabled:
        raise BistroPricingConfigurationError(
            "Bistro pricing is disabled. Enable it in Settings → Pricing before quoting "
            "measured Bistro runs."
        )

    installations: list[BistroInstallationPricing] = []
    lights_total = _ZERO
    poles_total = _ZERO
    for installation in ("temporary", "permanent"):
        feet = requested.get(installation)
        if feet is None:
            continue
        rates = getattr(bistro, installation)
        missing = [
            label
            for label, rate in (
                ("lights per foot", rates.lights_per_ft),
                ("poles/supports each", rates.poles_each),
            )
            if rate <= 0
        ]
        if missing:
            raise BistroPricingConfigurationError(
                f"{rates.label} is missing {', '.join(missing)}. Configure Bistro Pricing "
                "in Settings before creating this quote."
            )

        pole_count = max(0, int((pole_counts or {}).get(installation, 0)))
        lights_cost = gross_up_price(_d(feet) * _d(rates.lights_per_ft), config)
        poles_cost = gross_up_price(_d(pole_count) * _d(rates.poles_each), config)
        lights_total += lights_cost
        poles_total += poles_cost
        installations.append(
            BistroInstallationPricing(
                installation=installation,
                label=rates.label,
                feet=feet,
                pole_count=pole_count,
                lights_per_ft=rates.lights_per_ft,
                poles_each=rates.poles_each,
                lights_cost=float(lights_cost),
                poles_cost=float(poles_cost),
                total=float(lights_cost + poles_cost),
            )
        )

    raw_total = lights_total + poles_total
    gross_minimum = gross_up_price(bistro.minimum, config)
    total = max(raw_total, gross_minimum)
    feet_total = sum(requested.values())
    return BistroPricing(
        pricing_mode="installation",
        feet=feet_total,
        product="installation",
        tier="",
        per_ft=0,
        hardware=0,
        minimum=float(gross_minimum),
        lights_cost=float(lights_total),
        poles_cost=float(poles_total),
        raw_total=float(raw_total),
        total=float(total),
        min_applied=raw_total < gross_minimum,
        ordered_ft=feet_total,
        installations=installations,
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
    """A direct-price line; unit price is total/qty (cents) for presentation."""
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
    complexity: str = "standard",
    complexity_feet: Mapping[Any, float] | None = None,
) -> PermanentPricing:
    """Round footage to kits and weight COGS markup by measured run type."""
    p = config.permanent
    # Preserve field identity exactly: operators may intentionally price an Easy
    # run above a Complex run. Reordering configured values silently applies one
    # named tier's multiplier to another tier.
    #
    # Gable pitch is deliberately absent here. A steep rake is longer, not more
    # marked up, so the designer applies the Pythagorean correction to measured
    # feet before pricing. A former "aerial" tier hardcoded 1.5 in this map,
    # which *replaced* the 3.0 standard markup and halved every gable quote.
    markups = {
        "easy": p.easy_markup,
        "standard": p.standard_markup,
        "complex": p.complex_markup,
    }
    markup = markups.get(complexity, p.standard_markup)
    measured_complexity_feet = {
        key: max(0.0, float(value))
        for key, value in (complexity_feet or {}).items()
        if key in markups
    }
    allocated_feet = sum(measured_complexity_feet.values())
    if allocated_feet > 0:
        markup = (
            sum(
                measured_feet * markups[key]
                for key, measured_feet in measured_complexity_feet.items()
            )
            / allocated_feet
        )
    ft = max(0.0, feet or 0.0)
    ch = max(0, int(channels or 0))
    gross_minimum = gross_up_price(_d(p.minimum), config)

    if ft <= 0:
        return PermanentPricing(
            feet=0,
            channels=ch,
            package_feet=0,
            package_cogs=0,
            markup=markup,
            minimum=float(gross_minimum),
            raw_total=0,
            total=0,
            min_applied=False,
            lines=[],
        )

    packages = sorted(p.packages, key=lambda package: package.feet)
    if not packages:
        raise ValueError("Permanent lighting requires at least one package")

    selected = []
    remaining = ft
    largest = packages[-1]
    while remaining > largest.feet:
        selected.append(largest)
        remaining -= largest.feet
    if remaining > 0:
        selected.append(next(package for package in packages if package.feet >= remaining))

    package_feet = sum(package.feet for package in selected)
    package_cogs = sum((_d(package.cost) for package in selected), _ZERO)
    raw_total = gross_up_price(package_cogs * _d(markup), config)
    total = max(raw_total, gross_minimum)
    counts: dict[int, int] = {}
    for package in selected:
        counts[package.feet] = counts.get(package.feet, 0) + 1
    selected_kits = [
        PermanentKitSelection(feet=size, quantity=count)
        for size, count in sorted(counts.items(), reverse=True)
    ]
    # Feet-free on purpose: this label and detail become the quote line item the
    # homeowner reads on their proposal, and the measurement is ours. It is not
    # lost -- ``feet``, ``package_feet`` and ``selected_kits`` below carry it
    # structurally for the rep, behind auth.
    lines = [_category_line("Permanent lighting package", 1, raw_total)]

    return PermanentPricing(
        feet=ft,
        channels=ch,
        package_feet=package_feet,
        package_cogs=float(package_cogs),
        markup=markup,
        selected_kits=selected_kits,
        roofline_cost=float(raw_total),
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
    """Price each selected option of one decor category.

    ``each`` options price per selected item (value = quantity); ``per_ft``
    options price per linear foot of the measured run (value = feet). The two
    returned subtotals remain for compatibility and are equal under direct pricing.
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
        # That footage is material the customer receives, not the measurement we
        # took of their house -- the roofline line is the one that had to lose it.
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
    takedown, and storage use configured selling prices so display lines sum
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
                "Roofline",  # feet-free: customer-facing label
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
    else — direct pricing, takedown (a fraction of this package's install subtotal),
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

    Deliberately the same shape as :func:`price_christmas`: every component uses
    its configured selling price so display ``lines`` sum exactly to ``raw_total``,
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
