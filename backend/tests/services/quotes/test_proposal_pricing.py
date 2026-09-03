"""Pure unit coverage for proposal selling prices and Permanent economics.

Configured catalog amounts are customer prices. Legacy financing/commission settings
remain parseable but may not gross up any service or create payment presentation.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from app.schemas.pricing import (
    BistroConfig,
    BistroInstallationConfig,
    BistroProduct,
    BistroTier,
    CarePlanConfig,
    CarePlanTier,
    CashDiscountConfig,
    ChristmasConfig,
    ChristmasPackage,
    CommissionConfig,
    FinancingConfig,
    PermanentConfig,
    PricingSettings,
    SavingsConfig,
    SeasonalItem,
    SizeRate,
    TaxConfig,
)
from app.services.quotes import proposal_pricing as pp


def _landscape_config(**overrides) -> PricingSettings:
    """A PricingSettings mirroring the landscape wizard's shared knobs."""
    base = {
        "financing": FinancingConfig(
            enabled=True,
            max_amount=25000,
            terms=[6, 12, 24],
            default_term=24,
            apr=0.0,
            fee_buffer=0.11,
        ),
        "cash_discount": CashDiscountConfig(enabled=True, card_reserve_rate=0.03),
        "commission": CommissionConfig(enabled=True, rate=0.12, in_price=False),
        "care_plan": CarePlanConfig(
            free_fixtures=10,
            tiers=[
                CarePlanTier(
                    key="essential",
                    name="Essential",
                    base=179,
                    per_fixture=15,
                    visits=1,
                    repair_discount=0,
                ),
                CarePlanTier(
                    key="premier",
                    name="Premier",
                    base=299,
                    per_fixture=25,
                    visits=2,
                    repair_discount=0.10,
                    popular=True,
                ),
                CarePlanTier(
                    key="elite",
                    name="Elite",
                    base=499,
                    per_fixture=40,
                    visits=4,
                    repair_discount=0.15,
                ),
            ],
        ),
        "savings": SavingsConfig(
            per_visit_value=179,
            avoided_repair_per_fixture=28,
            assumed_repair_spend_per_fixture=40,
        ),
        "bistro": BistroConfig(
            enabled=True,
            minimum=2307,
            tiers=[
                BistroTier(key="easy", name="Easy", per_ft=14.86, classic_per_ft=11.63),
                BistroTier(key="medium", name="Medium", per_ft=18.11, classic_per_ft=15.50),
                BistroTier(key="complex", name="Complex", per_ft=28.22, classic_per_ft=20.68),
            ],
            color=BistroProduct(name="Color", hardware=577, strand_lengths=[50, 40, 20, 10, 4, 2]),
            classic=BistroProduct(name="Classic", hardware=35, min_footage=200, bulb_spacing_ft=2),
        ),
    }
    base.update(overrides)
    return PricingSettings(**base)


# --------------------------------------------------------------------------- #
# One-price policy and Permanent-only financing
# --------------------------------------------------------------------------- #
def test_legacy_buffers_never_change_the_configured_selling_price():
    baked_in = _landscape_config(
        commission=CommissionConfig(enabled=True, rate=0.12, in_price=True)
    )
    disabled = _landscape_config(financing=FinancingConfig(enabled=False, fee_buffer=0.11))

    for config in (_landscape_config(), baked_in, disabled):
        assert pp.commission_in_price(config) is False
        assert pp.price_buffer(config) == 0
        assert pp.gross_up_price(Decimal("2266.25"), config) == Decimal("2266.25")
        assert pp.cash_discount_rate(config) == 0
        assert pp.cash_price(Decimal("2266.25"), config) == Decimal("2266.25")
        assert pp.cash_savings(Decimal("2266.25"), config) == 0
        assert pp.commission_amount(Decimal("2266.25"), config) == 0


def test_legacy_global_financing_presentation_is_disabled():
    config = _landscape_config()
    assert pp.financing_is_offered(config) is False
    assert pp.financing_is_eligible(9000, {"landscape": 9000}, config) is False
    assert pp.financing_estimate(9000, {"landscape": 9000}, config) is None


def test_amortized_monthly_payment_handles_zero_and_nonzero_apr():
    assert pp.amortized_monthly_payment(5200, apr=0, term_months=24) == Decimal("216.67")
    assert pp.amortized_monthly_payment(10000, apr=0.12, term_months=24) == Decimal("470.73")
    with pytest.raises(ValueError, match="at least one month"):
        pp.amortized_monthly_payment(5200, apr=0, term_months=0)


def test_permanent_financing_estimate_uses_nested_green_sky_terms():
    config = _permanent_config()
    estimate = pp.permanent_financing_estimate(5200, config)

    assert estimate is not None
    assert estimate.provider == "GreenSky"
    assert estimate.plan_number == "6124"
    assert estimate.default_term == 24
    assert estimate.apr == 0
    assert estimate.monthly_payment == 216.67
    assert "Subject to credit approval" in estimate.disclaimer


def test_permanent_profitability_keeps_one_price_and_rounds_money():
    cash = pp.permanent_profitability(
        5200,
        material_cogs=1000,
        merchant_fee_rate=0.1525,
        sales_commission_rate=0.07,
        financed=False,
    )
    financed = pp.permanent_profitability(
        5200,
        material_cogs=1000,
        merchant_fee_rate=0.1525,
        sales_commission_rate=0.07,
        financed=True,
    )

    assert cash.contract_price == financed.contract_price == Decimal("5200.00")
    assert cash.merchant_fee == Decimal("0.00")
    assert financed.merchant_fee == Decimal("793.00")
    assert cash.sales_commission == financed.sales_commission == Decimal("364.00")
    assert cash.contribution_before_labor == Decimal("3836.00")
    assert financed.contribution_before_labor == Decimal("3043.00")


def test_price_tier_contains_only_direct_selling_price_fields():
    tier = pp.price_tier(base=10000, additional=500, config=_landscape_config())

    assert tier.financed_total == 10500
    assert tier.cash_total == 10500
    assert tier.cash_savings == 0
    assert tier.monthly_payment == 0
    assert tier.monthly_by_term == {}
    assert tier.commission_financed == 0
    assert tier.commission_cash == 0


def test_price_tier_additional_only_added_when_base_positive():
    cfg = _landscape_config()
    assert pp.price_tier(base=0, additional=500, config=cfg).financed_total == 0


# --------------------------------------------------------------------------- #
# Care Plan + savings
# --------------------------------------------------------------------------- #
def test_care_plan_price_over_free_fixtures():
    cfg = _landscape_config()
    essential = cfg.care_plan.tiers[0]
    assert pp.care_plan_price(essential, 20, cfg) == Decimal("329")  # 179 + 15*10
    assert pp.care_plan_price(essential, 5, cfg) == Decimal("179")  # under free count


def test_care_plan_savings_scales_with_fixtures():
    cfg = _landscape_config()
    essential, premier = cfg.care_plan.tiers[0], cfg.care_plan.tiers[1]
    # essential: 1*179 + round(20*28) + 0 = 739
    assert pp.care_plan_savings(essential, 20, cfg) == Decimal("739")
    # premier: 2*179 + 560 + round(20*40*0.10)=80 -> 998
    assert pp.care_plan_savings(premier, 20, cfg) == Decimal("998")


def test_price_care_plan_returns_all_tiers():
    cfg = _landscape_config()
    plans = pp.price_care_plan(20, cfg)
    assert [p.key for p in plans] == ["essential", "premier", "elite"]
    assert plans[1].popular is True


# --------------------------------------------------------------------------- #
# Bistro
# --------------------------------------------------------------------------- #
def test_bistro_color_applies_minimum():
    cfg = _landscape_config()
    result = pp.price_bistro(cfg, product="color", tier_key="easy", feet=100)
    # 100ft -> two 50ft strands; direct total falls below the configured minimum.
    assert result.ordered_ft == 100
    assert result.lights_cost == 1486
    assert result.hardware == 577
    assert result.total == 2307
    assert result.min_applied is True


def test_bistro_color_strand_fill_tops_up_gap():
    cfg = _landscape_config()
    result = pp.price_bistro(cfg, product="color", tier_key="easy", feet=95)
    # greedy largest-first: 50 + 40, remaining 5 -> one 4ft, remaining 1 -> top up
    # with the smallest (2ft) => 50 + 40 + 4 + 2 = 96
    assert result.ordered_ft == 96


def test_bistro_classic_enforces_min_footage():
    cfg = _landscape_config()
    result = pp.price_bistro(cfg, product="classic", tier_key="easy", feet=100)
    # Minimum footage applies, while each configured amount remains a direct price.
    assert result.ordered_ft == 200
    assert result.total == 2361


def test_bistro_zero_feet_is_empty():
    cfg = _landscape_config()
    result = pp.price_bistro(cfg, product="color", tier_key="easy", feet=0)
    assert result.total == 0
    assert result.lines == []


def _measured_bistro_config(*, minimum: float = 0) -> PricingSettings:
    cfg = _landscape_config()
    cfg.bistro.minimum = minimum
    cfg.bistro.temporary = BistroInstallationConfig(
        label="Temporary Bistro Lighting", lights_per_ft=10, poles_each=400
    )
    cfg.bistro.permanent = BistroInstallationConfig(
        label="Permanent Bistro Lighting", lights_per_ft=20, poles_each=350
    )
    return cfg


def test_bistro_legacy_pole_key_loads_as_per_pole_rate():
    rates = BistroInstallationConfig.model_validate(
        {"label": "Permanent Bistro Lighting", "lights_per_ft": 22, "poles_per_ft": 350}
    )

    assert rates.poles_each == 350
    assert rates.model_dump()["poles_each"] == 350
    assert "poles_per_ft" not in rates.model_dump()


def test_bistro_temporary_run_prices_lights_and_poles_separately():
    result = pp.price_bistro_installations(
        _measured_bistro_config(), {"temporary": 100}, {"temporary": 3}
    )

    assert result.pricing_mode == "installation"
    assert result.feet == 100
    assert result.lights_cost == 1000
    assert result.poles_cost == 1200
    assert result.total == 2200
    assert result.installations[0].installation == "temporary"
    assert result.installations[0].pole_count == 3
    assert result.installations[0].poles_each == 400


def test_bistro_permanent_run_uses_permanent_rates():
    result = pp.price_bistro_installations(
        _measured_bistro_config(), {"permanent": 80}, {"permanent": 4}
    )

    assert result.lights_cost == 1600
    assert result.poles_cost == 1400
    assert result.total == 3000
    assert result.installations[0].installation == "permanent"
    assert result.installations[0].pole_count == 4


def test_bistro_mixed_runs_apply_one_minimum_after_all_components():
    result = pp.price_bistro_installations(
        _measured_bistro_config(minimum=4000),
        {"temporary": 100, "permanent": 50},
        {"temporary": 2, "permanent": 2},
    )

    assert [row.installation for row in result.installations] == ["temporary", "permanent"]
    assert result.lights_cost == 2000
    assert result.poles_cost == 1500
    assert result.raw_total == 3500
    assert result.minimum == 4000
    assert result.total == 4000
    assert result.min_applied is True


@pytest.mark.parametrize("field", ["lights_per_ft", "poles_each"])
def test_bistro_requested_run_fails_when_an_active_rate_is_missing(field: str):
    cfg = _measured_bistro_config()
    setattr(cfg.bistro.temporary, field, 0)

    with pytest.raises(pp.BistroPricingConfigurationError, match="Configure Bistro Pricing"):
        pp.price_bistro_installations(cfg, {"temporary": 25})


def test_bistro_requested_run_fails_when_bistro_is_disabled():
    cfg = _measured_bistro_config()
    cfg.bistro.enabled = False

    with pytest.raises(pp.BistroPricingConfigurationError, match="disabled"):
        pp.price_bistro_installations(cfg, {"temporary": 25})


# --------------------------------------------------------------------------- #
# Tax
# --------------------------------------------------------------------------- #
def test_tax_disabled_is_zero():
    cfg = _landscape_config()
    assert pp.tax_amount(1000, cfg) == Decimal("0")


def test_tax_exclusive_and_inclusive():
    excl = _landscape_config(tax=TaxConfig(enabled=True, rate=0.06, method="Exclusive"))
    assert pp.tax_amount(1000, excl) == Decimal("60.00")
    incl = _landscape_config(tax=TaxConfig(enabled=True, rate=0.06, method="Inclusive"))
    # 1000 - 1000/1.06 = 56.60
    assert pp.tax_amount(1000, incl) == Decimal("56.60")


# --------------------------------------------------------------------------- #
# Permanent holiday lighting
# --------------------------------------------------------------------------- #
def _permanent_config(**overrides) -> PricingSettings:
    return _landscape_config(permanent=PermanentConfig(enabled=True, **overrides))


def test_permanent_pricing_ignores_bistro_installation_rates():
    baseline = _permanent_config()
    configured_bistro = _permanent_config()
    configured_bistro.bistro.permanent = BistroInstallationConfig(
        label="Permanent Bistro Lighting", lights_per_ft=999, poles_each=999
    )

    assert pp.price_permanent(configured_bistro, feet=165, channels=5) == pp.price_permanent(
        baseline, feet=165, channels=5
    )


def test_permanent_rounds_165_feet_up_to_200_foot_kit():
    result = pp.price_permanent(_permanent_config(), feet=165, channels=5)

    assert result.package_feet == 200
    assert result.package_cogs == 2099
    assert result.markup == 3
    # $2,099 COGS × 3 is the actual selling price; no fee is passed through.
    assert result.raw_total == 6297
    assert result.total == 6297
    assert result.min_applied is False
    assert sum(line.line_total for line in result.lines) == 6297


def test_permanent_complexity_selects_configured_multiplier():
    config = _permanent_config()

    easy = pp.price_permanent(config, feet=100, complexity="easy")
    standard = pp.price_permanent(config, feet=100, complexity="standard")
    complex_job = pp.price_permanent(config, feet=100, complexity="complex")

    assert (easy.markup, standard.markup, complex_job.markup) == (2.5, 3, 3.5)
    assert (easy.raw_total, standard.raw_total, complex_job.raw_total) == (3122.5, 3747, 4371.5)


def test_permanent_complexity_preserves_configured_multiplier_identity():
    config = _permanent_config(easy_markup=3.5, standard_markup=3, complex_markup=2.5)

    easy = pp.price_permanent(config, feet=100, complexity="easy")
    standard = pp.price_permanent(config, feet=100, complexity="standard")
    complex_job = pp.price_permanent(config, feet=100, complexity="complex")

    assert easy.markup == 3.5
    assert standard.markup == 3
    assert complex_job.markup == 2.5
    assert complex_job.total < standard.total < easy.total


def test_no_complexity_tier_undercuts_the_configured_standard_markup():
    """Guard the half-price gable bug.

    A retired "aerial" tier hardcoded a 1.5 markup in this map, which *replaced*
    the configured 3.0 standard markup and quoted every gable at roughly half
    price. Gable length is a measurement concern (the rake is longer), never a
    discount, so no tier may price below the operator's configured floor and an
    unknown tier must fall back to standard rather than invent a multiplier.
    """
    config = _permanent_config()
    standard = pp.price_permanent(config, feet=100, complexity="standard")

    assert pp.price_permanent(config, feet=100, complexity="aerial").markup == standard.markup
    assert min(
        pp.price_permanent(config, feet=100, complexity=tier).markup
        for tier in ("easy", "standard", "complex")
    ) == pytest.approx(config.permanent.easy_markup)


def test_gable_pitch_scales_feet_rather_than_discounting_markup():
    """The Pythagorean correction reaches pricing as feet, at an unchanged markup."""
    config = _permanent_config()
    flat = pp.price_permanent(config, feet=100, complexity="standard")
    steep = pp.price_permanent(config, feet=100 * math.sqrt(2), complexity="standard")

    assert steep.markup == flat.markup
    assert steep.total > flat.total


def test_permanent_weights_markup_by_measured_run_footage():
    result = pp.price_permanent(
        _permanent_config(),
        feet=100,
        complexity_feet={"easy": 75, "complex": 25},
    )

    assert result.package_feet == 100
    assert result.markup == 2.75
    # $1,249 COGS × weighted 2.75 multiplier is sold directly.
    assert result.raw_total == 3434.75


def test_permanent_applies_minimum():
    result = pp.price_permanent(_permanent_config(minimum=5000), feet=100)

    # The direct $3,747 package price is raised only to the configured $5,000 floor.
    assert result.raw_total == 3747
    assert result.total == 5000
    assert result.min_applied is True


def test_permanent_zero_feet_is_empty():
    cfg = _permanent_config()
    r = pp.price_permanent(cfg, feet=0, channels=4)
    assert r.total == 0
    assert r.lines == []


# --------------------------------------------------------------------------- #
# Christmas (seasonal)
# --------------------------------------------------------------------------- #
def _christmas_config(**overrides) -> PricingSettings:
    return _landscape_config(
        christmas=ChristmasConfig(
            enabled=True,
            roofline_per_ft=6,
            items=[
                SeasonalItem(
                    key="trees",
                    label="Trees",
                    unit="each",
                    options=[
                        SizeRate(key="small", name="Small tree", price=120),
                        SizeRate(key="medium", name="Medium tree", price=260),
                        SizeRate(key="large", name="Large tree", price=520),
                    ],
                ),
                SeasonalItem(
                    key="bushes",
                    label="Bushes",
                    unit="each",
                    options=[
                        SizeRate(key="small", name="Small bush", price=35),
                        SizeRate(key="large", name="Large bush", price=65),
                    ],
                ),
                SeasonalItem(
                    key="wreaths",
                    label="Wreaths",
                    unit="each",
                    options=[SizeRate(key="standard", name="Wreath", price=85)],
                ),
                SeasonalItem(
                    key="garland",
                    label="Garland",
                    unit="per_ft",
                    options=[SizeRate(key="standard", name="Garland", price=8)],
                ),
            ],
            takedown_rate=0.25,
            storage_price=200,
            **overrides,
        )
    )


def test_christmas_prices_roofline_decor_takedown_and_storage():
    cfg = _christmas_config()
    r = pp.price_christmas(
        cfg,
        roofline_feet=150,
        items={
            "trees": {"medium": 2, "large": 1},
            "bushes": {"small": 4},
            "wreaths": {"standard": 2},
        },
        takedown=True,
        storage=True,
    )
    # Every configured amount is direct; takedown remains 25% of selected work.
    assert r.roofline_cost == 900
    costs = {i.key: i.cost for i in r.items}
    assert costs["trees"] == 1040
    assert costs["bushes"] == 140
    assert costs["wreaths"] == 170
    # Categories with no selection are absent from the breakdown.
    assert "garland" not in costs
    assert r.takedown_cost == 562.5
    assert r.storage_cost == 200
    assert r.raw_total == 3012.5
    assert r.total == 3012.5
    assert sum(line.line_total for line in r.lines) == 3012.5


def test_christmas_prices_garland_per_linear_foot():
    cfg = _christmas_config()
    # Garland is per_ft: 80 ft * $8 = a direct $640 price.
    r = pp.price_christmas(cfg, roofline_feet=0, items={"garland": {"standard": 80}})
    costs = {i.key: i.cost for i in r.items}
    garland = next(i for i in r.items if i.key == "garland")
    assert garland.unit == "per_ft"
    assert costs["garland"] == 640
    assert r.total == 640
    assert any("ft Garland" in line.label for line in r.lines)


def test_default_seasonal_items_include_mini_lights_per_ft():
    # The estimator draws mini-light strands on bushes/trees; they price through
    # a per-ft `mini_lights` decor category seeded into the default catalog.
    items = {i.key: i for i in ChristmasConfig().items}
    assert "mini_lights" in items
    assert items["mini_lights"].unit == "per_ft"


def test_default_wreaths_ship_three_diameter_sizes():
    # Reps quote wreaths by diameter, so the default catalog offers 36/48/60 in
    # as separate line items (each independently countable on one quote).
    items = {i.key: i for i in ChristmasConfig().items}
    wreaths = items["wreaths"]
    assert wreaths.unit == "each"
    assert [o.key for o in wreaths.options] == ["36in", "48in", "60in"]
    # Prices stay monotonic with size so bigger wreaths never quote cheaper.
    prices = [o.price for o in wreaths.options]
    assert prices == sorted(prices)


def test_christmas_prices_multi_product_payload_with_mini_lights():
    # Default christmas catalog (now includes a per-ft `mini_lights` category),
    # mirroring a drawn design: roofline + mini-lights runs + a tree + a wreath.
    cfg = _landscape_config(
        christmas=ChristmasConfig(
            enabled=True, roofline_per_ft=6, takedown_rate=0.25, storage_price=0
        )
    )
    r = pp.price_christmas(
        cfg,
        roofline_feet=100,
        items={
            "mini_lights": {"standard": 60},
            "trees": {"small": 2},
            "wreaths": {"36in": 1},
        },
    )
    # Roofline and decor retain their configured direct selling prices.
    assert r.roofline_cost == 600
    costs = {i.key: i.cost for i in r.items}
    assert costs["mini_lights"] == 300
    mini = next(i for i in r.items if i.key == "mini_lights")
    assert mini.unit == "per_ft"
    assert costs["trees"] == 240
    assert costs["wreaths"] == 85
    # Unselected categories stay out of the breakdown.
    assert "bushes" not in costs
    assert "garland" not in costs
    assert r.raw_total == 1225
    assert r.total == 1225
    assert sum(line.line_total for line in r.lines) == 1225


def test_christmas_ignores_unknown_and_zero_counts():
    cfg = _christmas_config()
    r = pp.price_christmas(
        cfg,
        roofline_feet=0,
        items={"trees": {"medium": 0, "nope": 5}, "missing_category": {"x": 3}},
        takedown=False,
        storage=False,
    )
    assert r.total == 0
    assert r.items == []
    assert r.lines == []


def test_christmas_takedown_requires_config_enabled():
    cfg = _christmas_config(takedown_enabled=False)
    r = pp.price_christmas(cfg, items={"trees": {"small": 1}}, takedown=True)
    # The direct $120 item remains unchanged; disabled takedown adds nothing.
    assert r.takedown_cost == 0
    assert r.total == 120


def test_christmas_legacy_rate_lists_upgrade_and_price_identically():
    # A pre-standardization stored blob (tree_rates/bush_rates/wreath_rates) must
    # upgrade to items and price the same as the equivalent items config.
    legacy = _landscape_config(
        christmas=ChristmasConfig.model_validate(
            {
                "enabled": True,
                "roofline_per_ft": 6,
                "tree_rates": [{"key": "medium", "name": "Medium tree", "price": 260}],
                "bush_rates": [{"key": "small", "name": "Small bush", "price": 35}],
                "wreath_rates": [{"key": "standard", "name": "Wreath", "price": 85}],
            }
        )
    )
    r = pp.price_christmas(
        legacy,
        roofline_feet=100,
        items={"trees": {"medium": 1}, "bushes": {"small": 2}, "wreaths": {"standard": 1}},
    )
    costs = {i.key: i.cost for i in r.items}
    assert costs["trees"] == 260
    assert costs["bushes"] == 70
    assert costs["wreaths"] == 85
    assert r.roofline_cost == 600


# --------------------------------------------------------------------------- #
# Christmas packages (Good/Better/Best seasonal service tiers)
# --------------------------------------------------------------------------- #
def _christmas_packages_config(**overrides) -> PricingSettings:
    """Christmas config with three coverage tiers over the shared decor engine."""
    cfg = _christmas_config(**overrides)
    cfg.christmas.packages_enabled = True
    cfg.christmas.package_order = ["essential", "middle", "premier"]
    cfg.christmas.packages = [
        ChristmasPackage(
            key="essential",
            label="Essential",
            name="The Essential",
            includes_roofline=False,
            item_keys=["trees", "bushes"],
        ),
        ChristmasPackage(
            key="middle",
            label="Middle",
            name="The Classic",
            popular=True,
            includes_roofline=True,
            item_keys=["trees", "bushes"],
        ),
        ChristmasPackage(
            key="premier",
            label="Premier",
            name="The Premier",
            includes_roofline=True,
            item_keys=["trees", "bushes", "wreaths", "garland"],
        ),
    ]
    return cfg


_PACKAGE_ITEMS = {
    "trees": {"medium": 2, "large": 1},
    "bushes": {"small": 4},
    "wreaths": {"standard": 2},
    "garland": {"standard": 80},
}


def test_christmas_package_scopes_decor_and_roofline_to_coverage():
    cfg = _christmas_packages_config()
    essential, middle, premier = (
        p.pricing for p in pp.price_christmas_packages(cfg, roofline_feet=150, items=_PACKAGE_ITEMS)
    )
    # Essential covers trees+bushes and excludes the roofline even with feet > 0.
    assert essential.roofline_cost == 0
    assert {i.key for i in essential.items} == {"trees", "bushes"}
    # Middle adds the roofline but still no wreaths/garland.
    assert middle.roofline_cost == 900
    assert {i.key for i in middle.items} == {"trees", "bushes"}
    # Premier is the full display: roofline + every decor category.
    assert premier.roofline_cost == 900
    assert {i.key for i in premier.items} == {"trees", "bushes", "wreaths", "garland"}


def test_christmas_packages_are_monotonic_good_better_best():
    cfg = _christmas_packages_config()
    pkgs = pp.price_christmas_packages(cfg, roofline_feet=150, items=_PACKAGE_ITEMS)
    totals = [p.pricing.total for p in pkgs]
    # Each higher tier is a superset of coverage, so totals never decrease.
    assert totals == [1180, 2080, 2890]
    assert totals[0] <= totals[1] <= totals[2]


def test_christmas_packages_follow_package_order_and_carry_copy():
    cfg = _christmas_packages_config()
    pkgs = pp.price_christmas_packages(cfg, roofline_feet=150, items=_PACKAGE_ITEMS)
    assert [p.key for p in pkgs] == ["essential", "middle", "premier"]
    assert [p.label for p in pkgs] == ["Essential", "Middle", "Premier"]
    # Presentation copy (name, popular flag, roofline inclusion) rides along.
    assert pkgs[1].name == "The Classic"
    assert pkgs[1].popular is True
    assert [p.includes_roofline for p in pkgs] == [False, True, True]


def test_christmas_package_applies_job_minimum_per_package():
    cfg = _christmas_packages_config(minimum=5000)
    pkgs = pp.price_christmas_packages(cfg, roofline_feet=150, items=_PACKAGE_ITEMS)
    # The direct job minimum floors every package independently.
    for p in pkgs:
        assert p.pricing.min_applied is True
        assert p.pricing.total == 5000


def test_price_christmas_package_direct_excludes_uncovered_selection():
    cfg = _christmas_packages_config()
    essential = cfg.christmas.packages[0]
    # A wreaths/garland selection is ignored by a package that doesn't cover them.
    r = pp.price_christmas_package(
        cfg,
        essential,
        roofline_feet=150,
        items={"trees": {"medium": 1}, "wreaths": {"standard": 5}, "garland": {"standard": 40}},
    )
    assert {i.key for i in r.items} == {"trees"}
    assert r.roofline_cost == 0
