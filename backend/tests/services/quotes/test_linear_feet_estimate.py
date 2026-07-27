"""Unit tests for the roofline permanent-vs-temporary comparison math.

Pure (no DB / no marker, so they run in the default suite). Exercises
``QuoteService._compute_comparison`` directly with hand-built pricing configs so
the estimator's dollar math, multi-year projection, disabled-service handling,
and feet-privacy contract are all locked down without touching Postgres.
"""

from __future__ import annotations

import pytest

from app.schemas.estimate import (
    EstimateQuoteRequest,
    LinearFeetEstimateRequest,
    PublicChristmasComparison,
    PublicComparison,
    PublicPermanentComparison,
)
from app.schemas.pricing import (
    ChristmasConfig,
    FinancingConfig,
    PermanentConfig,
    PricingSettings,
)
from app.services.exceptions import ValidationError
from app.services.quotes.quote_service import (
    QuoteService,
    _resolve_recommended_package,
    build_public_comparison_packages,
    build_public_roofline_comparison,
)


def _config(**overrides) -> PricingSettings:
    """A pricing config with both holiday services enabled and no gross-up buffer.

    ``fee_buffer=0`` keeps the arithmetic exact so expected dollars are obvious.
    """
    base = {
        # Zero buffer + no cash/commission adjustments -> net == displayed.
        "financing": FinancingConfig(enabled=True, fee_buffer=0.0),
        "permanent": PermanentConfig(
            enabled=True,
            per_ft=30,
            controller_base=300,
            per_channel=0,
            included_channels=1,
            minimum=0,
        ),
        "christmas": ChristmasConfig(
            enabled=True,
            roofline_per_ft=6,
            takedown_enabled=True,
            takedown_rate=0.25,
            storage_price=0,
            minimum=0,
        ),
        "comparison_years": 5,
    }
    base.update(overrides)
    return PricingSettings(**base)


def _estimate(config: PricingSettings, feet: float, **kw):
    req = LinearFeetEstimateRequest(feet=feet, **kw)
    return QuoteService._compute_comparison(config, req)


def test_both_services_priced_from_feet() -> None:
    result = _estimate(_config(), 100)

    # Permanent: 100ft * $30 + $300 controller = $3,300.
    assert result.permanent.enabled is True
    assert result.permanent.total == 3300
    assert result.permanent.per_ft == 30
    # Christmas: 100ft * $6 = $600.
    assert result.christmas.enabled is True
    assert result.christmas.total == 600
    # Single-season difference is absolute.
    assert result.difference == 2700
    assert result.feet == 100


def test_multi_year_savings_projection() -> None:
    result = _estimate(_config(), 100)

    # Temporary recurs every season: $600 * 5 = $3,000. Permanent one-time $3,300.
    assert result.years == 5
    assert result.temporary_multi_year == 3000
    assert result.permanent_one_time == 3300
    # Over 5 seasons permanent costs $300 more (negative "savings" here) — sign is
    # honest so the UI can frame it correctly.
    assert result.multi_year_savings == -300


def test_multi_year_savings_favors_permanent_over_longer_horizon() -> None:
    result = _estimate(_config(comparison_years=10), 100)

    assert result.years == 10
    assert result.temporary_multi_year == 6000
    assert result.multi_year_savings == 2700  # 6000 - 3300


def test_takedown_increases_temporary_cost() -> None:
    with_takedown = _estimate(_config(), 100, takedown=True)
    # 25% of the $600 net install added: $600 + $150 = $750.
    assert with_takedown.christmas.total == 750


def test_permanent_disabled_zeros_that_side_and_skips_savings() -> None:
    config = _config(permanent=PermanentConfig(enabled=False))
    result = _estimate(config, 100)

    assert result.permanent.enabled is False
    assert result.permanent.total == 0
    assert result.christmas.total == 600
    # With only one option offered, comparison figures are not asserted as savings.
    assert result.difference == 0
    assert result.multi_year_savings == 0


def test_christmas_disabled_zeros_that_side() -> None:
    config = _config(christmas=ChristmasConfig(enabled=False))
    result = _estimate(config, 100)

    assert result.christmas.enabled is False
    assert result.christmas.total == 0
    assert result.permanent.total == 3300
    assert result.difference == 0


def test_seasonal_decor_adds_to_christmas_total() -> None:
    # Default config ships trees/bushes/wreaths (each) + garland (per_ft).
    result = _estimate(
        _config(),
        100,
        christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
    )
    # roofline 100*6=600; trees 2*260=520; garland 50*8=400 -> 1520.
    assert result.christmas.total == 1520
    costs = {i.key: i.cost for i in result.christmas.items}
    assert costs["trees"] == 520
    assert costs["garland"] == 400


def test_estimate_exposes_seasonal_catalog() -> None:
    result = _estimate(_config(), 100)
    catalog = {i.key: i.unit for i in result.christmas_catalog}
    # The rep tool renders decor controls from this catalog.
    assert catalog["trees"] == "each"
    assert catalog["garland"] == "per_ft"
    # No decor selected -> empty priced breakdown, roofline-only total.
    assert result.christmas.items == []
    assert result.christmas.total == 600


def test_permanent_minimum_applied() -> None:
    config = _config(
        permanent=PermanentConfig(enabled=True, per_ft=30, controller_base=0, minimum=5000)
    )
    result = _estimate(config, 100)
    # 100 * 30 = 3000 -> lifted to the $5,000 minimum.
    assert result.permanent.total == 5000


def test_internal_per_ft_override_adjusts_permanent_only() -> None:
    config = _config()
    standard = _estimate(config, 100)
    overridden = _estimate(config, 100, per_ft_override=45)

    # Permanent bills the internal rate: 100ft * $45 + $300 controller = $4,800.
    assert overridden.permanent.per_ft == 45
    assert overridden.permanent.total == 4800
    # Seasonal roofline is untouched by the permanent linear-ft override.
    assert overridden.christmas.total == standard.christmas.total == 600
    # The workspace's customer-facing rate is never mutated by the override.
    assert config.permanent.per_ft == 30
    assert standard.permanent.total == 3300


def test_per_ft_override_none_uses_configured_rate() -> None:
    config = _config()
    assert _estimate(config, 100, per_ft_override=None).permanent.total == 3300


def test_internal_christmas_per_ft_override_adjusts_seasonal_only() -> None:
    config = _config()
    standard = _estimate(config, 100)
    overridden = _estimate(config, 100, christmas_per_ft_override=9)

    # Seasonal bills the internal rate: 100ft * $9 = $900.
    assert overridden.christmas.per_ft == 9
    assert overridden.christmas.total == 900
    # Permanent is untouched by the seasonal override.
    assert overridden.permanent.total == standard.permanent.total == 3300
    # The workspace's customer-facing rate is never mutated.
    assert config.christmas.roofline_per_ft == 6
    assert standard.christmas.total == 600


def test_both_per_ft_overrides_apply_independently() -> None:
    result = _estimate(_config(), 100, per_ft_override=45, christmas_per_ft_override=9)
    assert result.permanent.total == 4800  # 100*45 + 300
    assert result.christmas.total == 900  # 100*9
    assert result.permanent.per_ft == 45
    assert result.christmas.per_ft == 9


def test_perks_default_copy_present() -> None:
    result = _estimate(_config(), 50)
    assert len(result.permanent_perks) >= 3
    assert len(result.christmas_perks) >= 3
    assert all(isinstance(p, str) and p for p in result.permanent_perks)


def test_zero_feet_yields_zero_totals() -> None:
    result = _estimate(_config(), 0)
    # No measured roofline -> no job on either side (permanent short-circuits to
    # $0 rather than billing a bare controller).
    assert result.christmas.total == 0
    assert result.permanent.total == 0
    assert result.difference == 0
    assert result.multi_year_savings == 0


def _packages_config() -> PricingSettings:
    """Base config with Good/Better/Best seasonal packages turned on."""
    return _config(
        christmas=ChristmasConfig(
            enabled=True,
            roofline_per_ft=6,
            minimum=0,
            packages_enabled=True,
        )
    )


def test_packages_priced_from_one_measurement_when_enabled() -> None:
    # One roofline+decor measurement prices every package by restricting each to
    # its covered decor subset (+ roofline when included). trees medium=$260,
    # garland=$8/ft, roofline=$6/ft, no gross-up buffer.
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
    )
    totals = {p.key: p.pricing.total for p in result.christmas_packages}
    assert totals == {
        "essential": 520,  # trees 2*260, no roofline
        "middle": 1120,  # roofline 600 + trees 520
        "premier": 1520,  # roofline 600 + trees 520 + garland 50*8
    }
    # Cards render low -> high; declared order applies when package_order is empty.
    assert [p.key for p in result.christmas_packages] == ["essential", "middle", "premier"]
    # Package cards carry copy for the tier presentation.
    middle = next(p for p in result.christmas_packages if p.key == "middle")
    assert middle.includes_roofline is True
    assert middle.popular is True


def test_packages_absent_when_disabled() -> None:
    # packages_enabled defaults False -> the à la carte flow is unchanged.
    result = _estimate(_config(), 100)
    assert result.christmas_packages == []


def test_selected_package_total_differs_from_a_la_carte() -> None:
    # ``selected_package`` is echoed on the request, but the rep-facing result
    # still exposes the full à la carte seasonal total and every package price —
    # only the public page (``get_public_comparison``) swaps in the selected
    # package's total. Here à la carte prices everything selected ($1,520) while
    # the "middle" package (roofline + trees only) is $1,120, the figure the
    # public page would show, so the selection genuinely changes what the client
    # sees for the seasonal side.
    result = _estimate(
        _packages_config(),
        100,
        selected_package="middle",
        christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
    )
    # Rep view is unchanged by the selection: full à la carte seasonal total.
    assert result.christmas.total == 1520
    # The middle package's total is what the public comparison substitutes.
    selected = next(p for p in result.christmas_packages if p.key == "middle")
    assert selected.pricing.total == 1120


# --------------------------------------------------------------------------- #
# Public comparison package mapping (feet-free client ladder)
# --------------------------------------------------------------------------- #
def test_public_packages_carry_totals_and_copy_but_no_feet() -> None:
    # The public payload exposes every priced package as a card, but only the
    # ``total`` crosses over — the ChristmasPricing breakdown (roofline_feet /
    # roofline_cost) must never reach the homeowner.
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
    )
    public = build_public_comparison_packages(result.christmas_packages, None)

    assert [p.key for p in public] == ["essential", "middle", "premier"]
    assert {p.key: p.total for p in public} == {
        "essential": 520,
        "middle": 1120,
        "premier": 1520,
    }
    # Card copy survives so the client sees a real tier ladder.
    middle = next(p for p in public if p.key == "middle")
    assert middle.includes_roofline is True
    assert middle.popular is True

    # Feet-privacy contract: the serialized card carries no measurement field and
    # not the nested pricing breakdown that would smuggle one in.
    forbidden = {"pricing", "roofline_feet", "roofline_cost", "feet", "per_ft", "lines"}
    for card in public:
        assert forbidden.isdisjoint(card.model_dump().keys())


def test_public_packages_recommend_explicit_pick_else_most_inclusive() -> None:
    result = _estimate(_packages_config(), 100, christmas_items={"trees": {"medium": 1}})
    packages = result.christmas_packages

    # Explicit pick -> that package is the recommended (highlighted) one.
    picked = build_public_comparison_packages(packages, "middle")
    assert [p.key for p in picked if p.recommended] == ["middle"]

    # No pick -> the most-inclusive tier (last, low→high) is recommended, matching
    # the frontend resolver so the preview and the shared page agree.
    default = build_public_comparison_packages(packages, None)
    assert [p.key for p in default if p.recommended] == ["premier"]

    # A stale/unknown key falls back to the most-inclusive default, never crashes.
    stale = build_public_comparison_packages(packages, "nope")
    assert [p.key for p in stale if p.recommended] == ["premier"]
    assert _resolve_recommended_package([], "middle") is None


def test_public_packages_empty_when_workspace_sells_a_la_carte() -> None:
    # packages_enabled defaults False -> no ladder crosses to the client.
    result = _estimate(_config(), 100)
    assert build_public_comparison_packages(result.christmas_packages, None) == []


# --------------------------------------------------------------------------- #
# Public roofline-only cost comparison (opt-in, feet-free)
# --------------------------------------------------------------------------- #
def test_roofline_comparison_absent_by_default() -> None:
    # Flag defaults off -> every existing workspace and already-shared link keeps
    # rendering exactly as it does today.
    config = _config()
    assert config.roofline_comparison_enabled is False
    assert build_public_roofline_comparison(config, _estimate(config, 100)) is None


def test_roofline_comparison_compares_roofline_to_roofline_when_enabled() -> None:
    config = _config(roofline_comparison_enabled=True)
    # Decor is selected on purpose: the roofline block must ignore it, otherwise
    # it's the same apples-to-oranges comparison as the headline totals.
    computed = _estimate(config, 100, christmas_items={"trees": {"medium": 2}})
    block = build_public_roofline_comparison(config, computed)

    assert block is not None
    # Permanent roofline track only: 100ft * $30 = $3,000 (no $300 controller).
    assert block.permanent_total == 3000
    # Seasonal roofline only: 100ft * $6 = $600 (the $520 of trees is excluded).
    assert block.seasonal_total == 600
    assert computed.christmas.total == 1120  # headline still includes the decor
    # Projected over the configured horizon: $600 * 5 = $3,000, dead even here.
    assert block.seasonal_multi_year == 3000
    assert block.savings == 0


def test_roofline_comparison_savings_follow_the_horizon() -> None:
    config = _config(roofline_comparison_enabled=True, comparison_years=10)
    block = build_public_roofline_comparison(config, _estimate(config, 100))

    assert block is not None
    assert block.seasonal_multi_year == 6000  # 600 * 10
    assert block.savings == 3000  # 6000 - 3000 permanent roofline


def test_roofline_comparison_uses_a_la_carte_not_the_package_roofline() -> None:
    # "essential" has includes_roofline=False, so its priced roofline_cost is $0.
    # Sourcing the block from a package would show a misleading $0 per season;
    # the à la carte roofline cost is the honest, always-defined figure.
    config = _config(
        roofline_comparison_enabled=True,
        christmas=ChristmasConfig(
            enabled=True, roofline_per_ft=6, minimum=0, packages_enabled=True
        ),
    )
    computed = _estimate(config, 100, selected_package="essential")
    essential = next(p for p in computed.christmas_packages if p.key == "essential")
    assert essential.pricing.roofline_cost == 0

    block = build_public_roofline_comparison(config, computed)
    assert block is not None
    assert block.seasonal_total == 600


@pytest.mark.parametrize(
    "disabled",
    [
        {"permanent": PermanentConfig(enabled=False)},
        {"christmas": ChristmasConfig(enabled=False)},
    ],
)
def test_roofline_comparison_needs_both_sides_offered(disabled) -> None:
    # A one-sided "comparison" isn't a comparison; suppress the block entirely.
    config = _config(roofline_comparison_enabled=True, **disabled)
    assert build_public_roofline_comparison(config, _estimate(config, 100)) is None


def test_roofline_comparison_block_is_feet_free() -> None:
    # Feet-privacy contract: costs only, never the measurement that produced them.
    config = _config(roofline_comparison_enabled=True)
    block = build_public_roofline_comparison(config, _estimate(config, 100))

    assert block is not None
    assert set(block.model_dump()) == {
        "permanent_total",
        "seasonal_total",
        "seasonal_multi_year",
        "savings",
    }


def test_public_comparison_payload_never_serializes_feet() -> None:
    # Structural check on the whole public model (roofline block included): no
    # nested key anywhere may expose a measurement or an internal per-foot rate.
    config = _config(roofline_comparison_enabled=True)
    computed = _estimate(config, 100, christmas_items={"trees": {"medium": 2}})
    payload = PublicComparison(
        business_name="Test Co",
        brand_color="#000000",
        accent_color="#ffffff",
        permanent=PublicPermanentComparison(
            enabled=computed.permanent.enabled, total=computed.permanent.total
        ),
        christmas=PublicChristmasComparison(
            enabled=computed.christmas.enabled, total=computed.christmas.total
        ),
        difference=computed.difference,
        years=computed.years,
        temporary_multi_year=computed.temporary_multi_year,
        permanent_one_time=computed.permanent_one_time,
        multi_year_savings=computed.multi_year_savings,
        roofline=build_public_roofline_comparison(config, computed),
    ).model_dump()
    assert payload["roofline"] is not None

    forbidden = {"feet", "per_ft", "roofline_feet", "channels", "roofline_cost"}

    def assert_clean(node) -> None:
        if isinstance(node, dict):
            assert forbidden.isdisjoint(node.keys()), node.keys()
            for value in node.values():
                assert_clean(value)
        elif isinstance(node, list):
            for value in node:
                assert_clean(value)

    assert_clean(payload)


# --------------------------------------------------------------------------- #
# Estimate -> quote conversion (the light designer's "design -> quote" step)
# --------------------------------------------------------------------------- #
def _convert(config: PricingSettings, side: str, feet: float, **kw):
    """Price a side and map it to quote line items (both pure, no DB)."""
    service = QuoteService(None)  # type: ignore[arg-type]  # pure methods only
    req = EstimateQuoteRequest(side=side, feet=feet, **kw)
    title, pricing = service._price_estimate_side(config, req)
    return title, pricing, service._estimate_line_items(pricing)


def _lines_sum(line_items) -> float:
    # Mirrors QuoteService._line_total for quantity=1 lines (quantity*unit price).
    return round(sum(li.quantity * li.unit_price - li.discount for li in line_items), 2)


def test_convert_permanent_lines_sum_to_permanent_total() -> None:
    title, pricing, lines = _convert(_config(), "permanent", 100)
    # 100ft * $30 + $300 controller = $3,300, split across itemized lines.
    assert pricing.total == 3300
    assert title == "Permanent Holiday Lighting"
    names = [li.name for li in lines]
    assert "100 ft permanent roofline" in names
    assert any("Controller" in n for n in names)
    # The summed quote total equals the estimate exactly (no per-unit drift).
    assert _lines_sum(lines) == 3300


def test_convert_seasonal_a_la_carte_itemizes_roofline_and_decor() -> None:
    title, pricing, lines = _convert(
        _config(),
        "seasonal",
        100,
        christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
    )
    # roofline 600 + trees 520 + garland 400 = 1520.
    assert pricing.total == 1520
    assert title == "Christmas Lighting"
    names = [li.name for li in lines]
    assert "100 ft roofline" in names
    assert any("Garland" in n for n in names)
    assert _lines_sum(lines) == 1520


def test_convert_seasonal_package_scopes_coverage_and_titles() -> None:
    title, pricing, lines = _convert(
        _packages_config(),
        "seasonal",
        100,
        selected_package="middle",
        christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
    )
    # "Middle" covers roofline + trees only (garland excluded): 600 + 520 = 1120.
    assert pricing.total == 1120
    assert title == "Christmas Lighting \u2014 The Classic"
    assert all("Garland" not in li.name for li in lines)
    assert _lines_sum(lines) == 1120


def test_convert_reconciles_job_minimum_with_a_line() -> None:
    config = _config(
        permanent=PermanentConfig(enabled=True, per_ft=30, controller_base=0, minimum=5000)
    )
    _title, pricing, lines = _convert(config, "permanent", 100)
    # 100 * 30 = 3000 raw, lifted to the $5,000 minimum via a reconciliation line.
    assert pricing.total == 5000
    assert any(li.name == "Job minimum" and li.unit_price == 2000 for li in lines)
    assert _lines_sum(lines) == 5000


def test_convert_all_lines_are_quantity_one_at_component_total() -> None:
    # The mapping keeps totals exact by emitting quantity=1 lines priced at the
    # authoritative component total (feet/counts live in the label instead).
    _title, _pricing, lines = _convert(
        _config(), "seasonal", 100, christmas_items={"trees": {"medium": 2}}
    )
    assert lines and all(li.quantity == 1 for li in lines)


def test_convert_permanent_override_flows_into_quote() -> None:
    _title, pricing, lines = _convert(_config(), "permanent", 100, per_ft_override=45)
    # Internal rate bills 100*45 + 300 = 4800 on the quote.
    assert pricing.total == 4800
    assert _lines_sum(lines) == 4800


def test_convert_disabled_permanent_side_raises() -> None:
    config = _config(permanent=PermanentConfig(enabled=False))
    with pytest.raises(ValidationError):
        _convert(config, "permanent", 100)


def test_convert_disabled_seasonal_side_raises() -> None:
    config = _config(christmas=ChristmasConfig(enabled=False))
    with pytest.raises(ValidationError):
        _convert(config, "seasonal", 100)
