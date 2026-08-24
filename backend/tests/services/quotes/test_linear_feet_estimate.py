"""Unit tests for the roofline permanent-vs-temporary comparison math.

Pure (no DB / no marker, so they run in the default suite). Exercises
``QuoteService._compute_comparison`` directly with hand-built pricing configs so
the estimator's dollar math, multi-year projection, disabled-service handling,
and feet-privacy contract are all locked down without touching Postgres.
"""

from __future__ import annotations

import pytest

from app.schemas.estimate import (
    EstimateCustomLine,
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
            packages=[{"feet": 100, "cost": 3300}],
            easy_markup=1,
            standard_markup=1,
            complex_markup=1,
            markup=1,
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


def _complexity_config(markups: tuple[float, float, float]) -> PricingSettings:
    easy, standard, complex_ = markups
    return _config(
        permanent=PermanentConfig(
            enabled=True,
            packages=[{"feet": 100, "cost": 1000}],
            easy_markup=easy,
            standard_markup=standard,
            complex_markup=complex_,
            markup=standard,
            minimum=0,
        )
    )


@pytest.mark.parametrize(
    ("markups", "expected_easy", "expected_complex"),
    [((2, 3, 4), 2, 4), ((4, 3, 2), 4, 2)],
    ids=["ascending-settings", "descending-settings"],
)
def test_run_complexity_uses_its_configured_markup_in_live_comparison(
    markups: tuple[float, float, float],
    expected_easy: float,
    expected_complex: float,
) -> None:
    config = _complexity_config(markups)

    # The measured per-run map is authoritative even when the scalar fallback says
    # the opposite, while each named tier retains its explicitly configured value.
    complex_result = _estimate(
        config,
        100,
        permanent_complexity="easy",
        permanent_complexity_feet={"complex": 100},
    )
    easy_result = _estimate(
        config,
        100,
        permanent_complexity="complex",
        permanent_complexity_feet={"easy": 100},
    )

    assert complex_result.permanent.markup == expected_complex
    assert complex_result.permanent.total == expected_complex * 1000
    assert easy_result.permanent.markup == expected_easy
    assert easy_result.permanent.total == expected_easy * 1000


def test_aerial_pics_run_uses_fixed_multiplier_in_live_comparison() -> None:
    result = _estimate(
        _complexity_config((2, 3, 4)),
        100,
        permanent_complexity_feet={"aerial": 100},
    )

    assert result.permanent.markup == 1.5
    assert result.permanent.total == 1500


def test_flat_discount_applies_only_to_selected_proposal_side() -> None:
    permanent = _estimate(
        _complexity_config((2, 3, 4)),
        100,
        proposal_side="permanent",
        discount_amount=500,
        permanent_complexity_feet={"complex": 100},
    )
    seasonal = _estimate(
        _complexity_config((2, 3, 4)),
        100,
        proposal_side="seasonal",
        discount_amount=100,
    )

    assert permanent.permanent.subtotal == 4000
    assert permanent.permanent.total == 3500
    assert permanent.christmas.total == 600
    assert seasonal.permanent.total == 3000
    assert seasonal.christmas.subtotal == 600
    assert seasonal.christmas.total == 500


def test_flat_discount_cannot_exceed_selected_proposal_total() -> None:
    with pytest.raises(ValidationError, match="Discount cannot exceed"):
        _estimate(
            _config(),
            100,
            proposal_side="seasonal",
            discount_amount=601,
        )


def test_both_services_priced_from_feet() -> None:
    result = _estimate(_config(), 100)

    # Permanent: the configured 100-ft package is $3,300.
    assert result.permanent.enabled is True
    assert result.permanent.total == 3300
    assert result.permanent.package_feet == 100
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


def test_legacy_per_ft_override_does_not_bypass_package_pricing() -> None:
    config = _config()
    standard = _estimate(config, 100)
    overridden = _estimate(config, 100, per_ft_override=45)

    assert overridden.permanent.total == standard.permanent.total == 3300
    assert overridden.permanent.package_feet == 100
    assert overridden.christmas.total == standard.christmas.total == 600


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


def test_seasonal_override_does_not_change_permanent_package() -> None:
    result = _estimate(_config(), 100, per_ft_override=45, christmas_per_ft_override=9)
    assert result.permanent.total == 3300
    assert result.christmas.total == 900  # 100*9
    assert result.permanent.package_feet == 100
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


def test_discount_cannot_exceed_selected_seasonal_package() -> None:
    with pytest.raises(ValidationError, match="Discount cannot exceed"):
        _estimate(
            _packages_config(),
            100,
            proposal_side="seasonal",
            selected_package="middle",
            discount_amount=1121,
            christmas_items={"trees": {"medium": 2}, "garland": {"standard": 50}},
        )


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
    # Permanent complete-kit price includes all package hardware.
    assert block.permanent_total == 3300
    # Seasonal roofline only: 100ft * $6 = $600 (the $520 of trees is excluded).
    assert block.seasonal_total == 600
    assert computed.christmas.total == 1120  # headline still includes the decor
    # Projected over the configured horizon: $600 * 5 = $3,000, dead even here.
    assert block.seasonal_multi_year == 3000
    assert block.savings == -300


def test_roofline_comparison_savings_follow_the_horizon() -> None:
    config = _config(roofline_comparison_enabled=True, comparison_years=10)
    block = build_public_roofline_comparison(config, _estimate(config, 100))

    assert block is not None
    assert block.seasonal_multi_year == 6000  # 600 * 10
    assert block.savings == 2700  # 6000 - 3300 permanent package


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


def test_estimate_quote_deposit_is_bounded_and_permanent_only() -> None:
    request = EstimateQuoteRequest(side="permanent", feet=100, deposit_percentage=30)
    assert request.deposit_percentage == 30

    with pytest.raises(ValueError, match="only be added to a permanent quote"):
        EstimateQuoteRequest(side="seasonal", feet=100, deposit_percentage=30)
    with pytest.raises(ValueError):
        EstimateQuoteRequest(side="permanent", feet=100, deposit_percentage=0)
    with pytest.raises(ValueError):
        EstimateQuoteRequest(side="permanent", feet=100, deposit_percentage=101)


def test_convert_permanent_lines_sum_to_permanent_total() -> None:
    title, pricing, lines = _convert(_config(), "permanent", 100)
    assert pricing.total == 3300
    assert pricing.package_feet == 100
    assert [kit.model_dump() for kit in pricing.selected_kits] == [{"feet": 100, "quantity": 1}]
    assert title == "Permanent Holiday Lighting"
    names = [li.name for li in lines]
    assert "Permanent lighting package — covers 100 ft" in names
    # The summed quote total equals the estimate exactly (no per-unit drift).
    assert _lines_sum(lines) == 3300


@pytest.mark.parametrize(
    ("markups", "expected_complex"),
    [((2, 3, 4), 4), ((4, 3, 2), 2)],
    ids=["ascending-settings", "descending-settings"],
)
def test_convert_all_complex_run_uses_configured_markup(
    markups: tuple[float, float, float],
    expected_complex: float,
) -> None:
    _title, pricing, lines = _convert(
        _complexity_config(markups),
        "permanent",
        100,
        # Deliberately oppose the measured map so this fails if conversion drops
        # the map and falls back to the scalar, which was the production defect.
        permanent_complexity="easy",
        permanent_complexity_feet={"complex": 100},
    )

    assert pricing.markup == expected_complex
    assert pricing.total == expected_complex * 1000
    assert _lines_sum(lines) == expected_complex * 1000


def test_convert_aerial_pics_run_uses_fixed_multiplier() -> None:
    _title, pricing, lines = _convert(
        _complexity_config((2, 3, 4)),
        "permanent",
        100,
        permanent_complexity="aerial",
        permanent_complexity_feet={"aerial": 100},
    )

    assert pricing.markup == 1.5
    assert pricing.total == 1500
    assert _lines_sum(lines) == 1500


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
    assert any(li.name == "Job minimum" and li.unit_price == 1253 for li in lines)
    assert _lines_sum(lines) == 5000


def test_convert_all_lines_are_quantity_one_at_component_total() -> None:
    # The mapping keeps totals exact by emitting quantity=1 lines priced at the
    # authoritative component total (feet/counts live in the label instead).
    _title, _pricing, lines = _convert(
        _config(), "seasonal", 100, christmas_items={"trees": {"medium": 2}}
    )
    assert lines and all(li.quantity == 1 for li in lines)


def test_convert_legacy_permanent_override_keeps_package_price() -> None:
    _title, pricing, lines = _convert(_config(), "permanent", 100, per_ft_override=45)
    assert pricing.total == 3300
    assert pricing.package_feet == 100
    assert _lines_sum(lines) == 3300


def test_convert_disabled_permanent_side_raises() -> None:
    config = _config(permanent=PermanentConfig(enabled=False))
    with pytest.raises(ValidationError):
        _convert(config, "permanent", 100)


def test_convert_disabled_seasonal_side_raises() -> None:
    config = _config(christmas=ChristmasConfig(enabled=False))
    with pytest.raises(ValidationError):
        _convert(config, "seasonal", 100)


# --------------------------------------------------------------------------- #
# Standalone line items (rep-entered, independent of packages)
# --------------------------------------------------------------------------- #
def _line(label: str, unit_price: float, **kw) -> EstimateCustomLine:
    return EstimateCustomLine(label=label, unit_price=unit_price, **kw)


def test_custom_line_adds_to_the_side_it_names() -> None:
    result = _estimate(
        _config(),
        100,
        custom_lines=[
            _line("Bucket truck day", 150, quantity=2),
            _line("Remove old clips", 90, side="permanent"),
        ],
    )

    # Seasonal: 100ft * $6 = $600, plus 2 x $150.
    assert result.christmas.total == 900
    assert result.christmas.custom_total == 300
    # Permanent: $3,300 priced work plus the $90 line.
    assert result.permanent.total == 3390
    assert result.permanent.custom_total == 90
    # Amounts are computed server-side and echoed back per line.
    assert [(line.label, line.amount) for line in result.custom_lines] == [
        ("Remove old clips", 90),
        ("Bucket truck day", 300),
    ]


def test_custom_line_is_not_grossed_up() -> None:
    # Every other rate on an estimate is net and gets marked up; a standalone line
    # is the client-facing amount the rep quoted out loud, so it must land exactly.
    config = _config(financing=FinancingConfig(enabled=True, fee_buffer=0.25))
    result = _estimate(config, 0, custom_lines=[_line("Custom mantel garland", 425)])

    assert result.christmas.total == 425
    assert result.custom_lines[0].amount == 425


def test_custom_line_stands_alone_without_a_drawn_design() -> None:
    # The whole point: quote something that isn't in the price book or a package,
    # on an estimate with nothing traced on the photo yet.
    result = _estimate(_config(), 0, custom_lines=[_line("Consultation", 75)])

    assert result.christmas.total == 75
    assert result.permanent.total == 0


def test_custom_lines_project_over_the_horizon_on_the_seasonal_side() -> None:
    result = _estimate(_config(), 100, custom_lines=[_line("Extra strand", 100)])

    # Seasonal work recurs: ($600 + $100) * 5 seasons.
    assert result.christmas.total == 700
    assert result.temporary_multi_year == 3500
    assert result.multi_year_savings == 200  # 3500 - 3300 permanent one-time


def test_custom_lines_stay_out_of_package_totals() -> None:
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 1}},
        custom_lines=[_line("Balcony hand-tie", 200)],
    )

    # Each tier still quotes its own scope — switching package changes one number.
    assert {p.key: p.pricing.total for p in result.christmas_packages} == {
        "essential": 260,
        "middle": 860,
        "premier": 860,
    }
    # …while the à la carte seasonal headline carries the add-on.
    assert result.christmas.total == 1060
    assert result.christmas.custom_total == 200


def test_custom_lines_stay_out_of_the_roofline_comparison() -> None:
    # Roofline-vs-roofline must stay like-for-like: same run of lights, both ways.
    config = _config(roofline_comparison_enabled=True)
    computed = _estimate(config, 100, custom_lines=[_line("Bucket truck day", 150)])
    block = build_public_roofline_comparison(config, computed)

    assert block is not None
    assert block.seasonal_total == 600
    assert block.permanent_total == 3300
    assert computed.christmas.roofline_cost == 600


def test_custom_lines_for_a_disabled_service_are_dropped() -> None:
    config = _config(permanent=PermanentConfig(enabled=False))
    result = _estimate(config, 100, custom_lines=[_line("Trip fee", 60, side="permanent")])

    assert result.permanent.total == 0
    assert result.permanent.custom_total == 0
    # Not reported against a total it was never added to.
    assert result.custom_lines == []


def test_convert_carries_custom_lines_onto_the_quote() -> None:
    _title, pricing, lines = _convert(
        _config(),
        "seasonal",
        100,
        custom_lines=[
            _line("Bucket truck day", 150, quantity=2),
            _line("Permanent-only line", 500, side="permanent"),
        ],
    )

    # The seasonal line becomes a real quote line; the permanent one stays behind.
    assert pricing.total == 900
    assert "2 × Bucket truck day" in [li.name for li in lines]
    assert all("Permanent-only" not in li.name for li in lines)
    assert _lines_sum(lines) == 900


def test_convert_carries_custom_lines_onto_a_package_quote() -> None:
    _title, pricing, lines = _convert(
        _packages_config(),
        "seasonal",
        100,
        selected_package="middle",
        christmas_items={"trees": {"medium": 2}},
        custom_lines=[_line("Balcony hand-tie", 200)],
    )

    # "Middle" covers roofline + trees (600 + 520), plus the standalone line.
    assert pricing.total == 1320
    assert "Balcony hand-tie" in [li.name for li in lines]
    assert _lines_sum(lines) == 1320


# --------------------------------------------------------------------------- #
# Package-scoped standalone lines (the bucket truck Best needs and Good doesn't)
# --------------------------------------------------------------------------- #
def _package_totals(result) -> dict[str, float]:
    """Every priced tier's card total, keyed by package."""
    totals: dict[str, float] = {}
    for pkg in result.christmas_packages:
        totals[pkg.key] = pkg.pricing.total
    return totals


def _package(result, wanted: str):
    """One priced tier by its package key."""
    return next(pkg for pkg in result.christmas_packages if pkg.key in {wanted})


def test_scoped_custom_line_is_priced_inside_only_its_own_card() -> None:
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 1}},
        custom_lines=[_line("Bucket truck day", 200, package_key="middle")],
    )

    # Only "middle" moves: the line was sold with that tier and follows it.
    assert _package_totals(result) == {
        "essential": 260,
        "middle": 1060,  # 860 + 200
        "premier": 860,
    }
    # It reads on the card too, not just in the total.
    middle = _package(result, "middle")
    assert "Bucket truck day" in [line.label for line in middle.pricing.lines]


def test_scoped_custom_line_stays_out_of_the_global_custom_total() -> None:
    # ``custom_total`` is what the client page adds *on top of* a package total,
    # so a line already inside a card must not appear in it — that is the
    # double-count that would overbill the homeowner.
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 1}},
        custom_lines=[_line("Bucket truck day", 200, package_key="middle")],
    )

    assert result.christmas.custom_total == 0
    assert result.christmas.total == 860  # à la carte, untouched
    # Still echoed to the rep, carrying the tier it belongs to.
    assert [(line.label, line.amount, line.package_key) for line in result.custom_lines] == [
        ("Bucket truck day", 200, "middle")
    ]


def test_global_and_scoped_lines_coexist_on_one_estimate() -> None:
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 1}},
        custom_lines=[
            _line("Trip charge", 75),
            _line("Bucket truck day", 200, package_key="premier"),
        ],
    )

    # The global line rides on top of every tier (via custom_total); the scoped
    # one is inside exactly one card.
    assert result.christmas.custom_total == 75
    assert result.christmas.total == 935  # 860 + 75
    assert _package_totals(result) == {
        "essential": 260,
        "middle": 860,
        "premier": 1060,
    }
    assert [line.label for line in result.custom_lines] == [
        "Trip charge",
        "Bucket truck day",
    ]


def test_scoped_custom_line_naming_no_priced_package_is_dropped() -> None:
    # Silently falling back to "global" would move money the rep never asked to
    # move, so an unknown tier drops the line — same as a disabled service.
    result = _estimate(
        _packages_config(),
        100,
        christmas_items={"trees": {"medium": 1}},
        custom_lines=[_line("Bucket truck day", 200, package_key="platinum")],
    )

    assert _package_totals(result) == {
        "essential": 260,
        "middle": 860,
        "premier": 860,
    }
    assert result.christmas.total == 860
    assert result.christmas.custom_total == 0
    assert result.custom_lines == []


def test_scoped_custom_line_is_dropped_when_the_workspace_sells_no_packages() -> None:
    result = _estimate(
        _config(), 100, custom_lines=[_line("Bucket truck day", 200, package_key="middle")]
    )

    assert result.christmas.total == 600
    assert result.christmas.custom_total == 0
    assert result.custom_lines == []


def test_scoped_custom_line_stays_out_of_the_roofline_comparison() -> None:
    config = _packages_config()
    config = config.model_copy(update={"roofline_comparison_enabled": True})
    computed = _estimate(
        config, 100, custom_lines=[_line("Bucket truck day", 200, package_key="middle")]
    )
    block = build_public_roofline_comparison(config, computed)

    # Like-for-like stays like-for-like: same run of lights, both ways.
    assert block is not None
    assert block.seasonal_total == 600
    assert block.permanent_total == 3300


def test_convert_carries_a_scoped_line_onto_that_package_quote_once() -> None:
    _title, pricing, lines = _convert(
        _packages_config(),
        "seasonal",
        100,
        selected_package="middle",
        christmas_items={"trees": {"medium": 2}},
        custom_lines=[_line("Bucket truck day", 200, package_key="middle")],
    )

    # "Middle" covers roofline + trees (600 + 520) plus its own scoped line, and
    # the line is folded exactly once — the sum proves it.
    assert pricing.total == 1320
    assert [li.name for li in lines].count("Bucket truck day") == 1
    assert _lines_sum(lines) == 1320


def test_convert_drops_a_line_scoped_to_a_different_package() -> None:
    _title, pricing, lines = _convert(
        _packages_config(),
        "seasonal",
        100,
        selected_package="essential",
        christmas_items={"trees": {"medium": 2}},
        custom_lines=[_line("Bucket truck day", 200, package_key="middle")],
    )

    # "Essential" covers trees only (520). The Best-tier add-on isn't sold here.
    assert pricing.total == 520
    assert all("Bucket truck" not in li.name for li in lines)
    assert _lines_sum(lines) == 520


def test_convert_carries_global_and_scoped_lines_together() -> None:
    _title, pricing, lines = _convert(
        _packages_config(),
        "seasonal",
        100,
        selected_package="middle",
        christmas_items={"trees": {"medium": 2}},
        custom_lines=[
            _line("Trip charge", 75),
            _line("Bucket truck day", 200, package_key="middle"),
        ],
    )

    assert pricing.total == 1395  # 1120 package + 75 global + 200 scoped
    assert _lines_sum(lines) == 1395


def test_custom_line_tops_up_a_job_that_hit_the_minimum() -> None:
    # The minimum lifts the *priced work*; an add-on is billed on top of it rather
    # than disappearing into the shortfall.
    config = _config(
        permanent=PermanentConfig(enabled=True, per_ft=30, controller_base=0, minimum=5000)
    )
    _title, pricing, lines = _convert(
        config, "permanent", 100, custom_lines=[_line("Trip fee", 250, side="permanent")]
    )

    assert pricing.total == 5250
    assert any(li.name == "Job minimum" and li.unit_price == 1253 for li in lines)
    assert _lines_sum(lines) == 5250
