"""Unit tests for the ported sales-proposal pricing math.

Pure (no DB / no marker, so they run in the default suite). Expected values are
computed from the uploaded landscape-lighting wizard's JavaScript so any drift in
the Python port is caught: grossing buffer, cash discount, commission, 0% APR
monthly, Care Plan price/savings, bistro strand fill, and tax.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.pricing import (
    DEFAULT_FINANCING_DISCLAIMER,
    BistroConfig,
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
# Buffer + gross-up
# --------------------------------------------------------------------------- #
def test_price_buffer_is_fee_buffer_when_commission_out_of_price():
    cfg = _landscape_config()
    assert pp.price_buffer(cfg) == Decimal("0.11")


def test_price_buffer_adds_commission_when_baked_in():
    cfg = _landscape_config(commission=CommissionConfig(enabled=True, rate=0.12, in_price=True))
    assert pp.price_buffer(cfg) == Decimal("0.23")


def test_gross_up_price_rounds_to_whole_dollar():
    cfg = _landscape_config()
    # 2266 / (1 - 0.11) = 2546.06... -> 2546
    assert pp.gross_up_price(2266, cfg) == Decimal("2546")


def test_gross_up_price_identity_when_no_buffer():
    cfg = _landscape_config(
        financing=FinancingConfig(enabled=False, fee_buffer=0.0),
        commission=CommissionConfig(enabled=False, rate=0.0, in_price=False),
    )
    assert pp.gross_up_price(500, cfg) == Decimal("500")


def test_disabling_financing_also_removes_the_price_buffer():
    """``financing.enabled`` gates the fee buffer, not just the financing offer.

    This is a trap worth stating out loud: we do **not** offer financing to
    clients any more, but that was removed in the proposal UI, deliberately, and
    the buffer was kept. Flipping this flag off to "turn financing off" instead
    would silently cut every sticker price by the buffer — giving away the margin
    the buffer exists to protect.

    If the buffer should ever apply independently of the financing offer, that is
    a pricing decision: decouple it on purpose and update this test.
    """
    on = _landscape_config()
    off = _landscape_config(financing=FinancingConfig(enabled=False, fee_buffer=0.11))

    assert pp.price_buffer(on) == Decimal("0.11")
    assert pp.price_buffer(off) == Decimal("0")
    # Same net cost, ~11% less revenue — the whole point of the warning.
    assert pp.gross_up_price(2266, on) == Decimal("2546")
    assert pp.gross_up_price(2266, off) == Decimal("2266")


# --------------------------------------------------------------------------- #
# Cash / commission
# --------------------------------------------------------------------------- #
def test_cash_discount_rate_backs_out_fee_keeps_reserve():
    cfg = _landscape_config()
    # 1 - (1.03 * 0.89 / 1) = 0.0833
    assert pp.cash_discount_rate(cfg) == Decimal("0.0833")


def test_cash_price_and_savings():
    cfg = _landscape_config()
    # 10000 * (1 - 0.0833) = 9167
    assert pp.cash_price(10000, cfg) == Decimal("9167")
    assert pp.cash_savings(10000, cfg) == Decimal("833")


def test_commission_amount():
    cfg = _landscape_config()
    assert pp.commission_amount(9167, cfg) == Decimal("1100")


def test_commission_zero_when_disabled():
    cfg = _landscape_config(commission=CommissionConfig(enabled=False, rate=0.12))
    assert pp.commission_amount(9167, cfg) == Decimal("0")


# --------------------------------------------------------------------------- #
# Financing
# --------------------------------------------------------------------------- #
def test_monthly_payment_zero_apr_is_total_over_term():
    cfg = _landscape_config()
    assert pp.monthly_payment(10000, cfg, term=24) == Decimal("416.67")
    assert pp.monthly_payment(12000, cfg, term=12) == Decimal("1000.00")


def test_monthly_payment_zero_over_cap_or_disabled():
    cfg = _landscape_config()
    assert pp.monthly_payment(30000, cfg) == Decimal("0")
    off = _landscape_config(financing=FinancingConfig(enabled=False))
    assert pp.monthly_payment(5000, off) == Decimal("0")


def test_monthly_payment_with_apr():
    cfg = _landscape_config(
        financing=FinancingConfig(
            enabled=True,
            max_amount=25000,
            terms=[24],
            default_term=24,
            apr=0.12,
            fee_buffer=0.11,
        )
    )
    # r = .01/mo, 24 mo, 10000 -> ~470.73
    assert pp.monthly_payment(10000, cfg, term=24) == Decimal("470.73")


def test_financing_eligibility_uses_each_category_subtotal_and_minimum():
    cfg = _landscape_config(
        financing=FinancingConfig(
            category_minimums={"roof": 1000, "gutters": 1000},
            disclaimer=None,
        )
    )

    roof = pp.financing_estimate(9000, {"roof": 9000}, cfg)
    assert roof is not None
    assert roof.monthly_payment == 375.0
    assert roof.disclaimer == DEFAULT_FINANCING_DISCLAIMER

    assert pp.financing_estimate(400, {"gutters": 400}, cfg) is None
    assert pp.financing_estimate(400, {"roof": 9000}, cfg) is None
    # A large uncategorized amount cannot make a $400 gutter line qualify.
    assert pp.financing_estimate(9400, {"gutters": 400, "other": 9000}, cfg) is None
    assert pp.financing_estimate(9000, {"unknown": 9000}, cfg) is None


def test_category_presentation_gate_never_changes_fee_buffer_or_cash_reversal():
    cfg = _landscape_config(
        financing=FinancingConfig(
            enabled=True,
            fee_buffer=0.11,
            category_minimums={},
        )
    )

    assert pp.financing_is_eligible(10000, {"landscape": 10000}, cfg) is False
    assert pp.gross_up_price(2266, cfg) == Decimal("2546")
    assert pp.cash_price(10000, cfg) == Decimal("9167")


def test_landscape_financing_pricing_bytes_are_unchanged():
    """Lock the pre-generalization landscape financing payload byte-for-byte."""
    actual = pp.price_tier(base=10000, additional=0, config=_landscape_config())

    assert actual.model_dump_json().encode() == (
        b'{"base":10000.0,"additional":0.0,"financed_total":10000.0,'
        b'"cash_total":9167.0,"cash_savings":833.0,"monthly_payment":416.67,'
        b'"monthly_by_term":{"6":1666.67,"12":833.33,"24":416.67},'
        b'"commission_financed":1200.0,"commission_cash":1100.0}'
    )


# --------------------------------------------------------------------------- #
# Tier aggregate
# --------------------------------------------------------------------------- #
def test_price_tier_combines_financed_cash_commission():
    cfg = _landscape_config()
    tier = pp.price_tier(base=10000, additional=0, config=cfg)
    assert tier.financed_total == 10000
    assert tier.cash_total == 9167
    assert tier.monthly_payment == pytest.approx(416.67)
    assert set(tier.monthly_by_term) == {6, 12, 24}
    assert tier.commission_financed == 1200
    assert tier.commission_cash == 1100


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
    # 100ft -> two 50ft strands; lights 100*14.86=1486 -> gross 1670; hw 577 -> 648
    # raw 2318 < gross minimum(2307->2592) -> total 2592
    assert result.ordered_ft == 100
    assert result.lights_cost == 1670
    assert result.hardware == 648
    assert result.total == 2592
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
    # min footage 200 applied; 200*11.63=2326 -> gross 2613; +hw 35->39 = 2652
    assert result.ordered_ft == 200
    assert result.total == 2652


def test_bistro_zero_feet_is_empty():
    cfg = _landscape_config()
    result = pp.price_bistro(cfg, product="color", tier_key="easy", feet=0)
    assert result.total == 0
    assert result.lines == []


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


def test_permanent_rounds_165_feet_up_to_200_foot_kit():
    result = pp.price_permanent(_permanent_config(), feet=165, channels=5)

    assert result.package_feet == 200
    assert result.package_cogs == 2099
    assert result.markup == 3
    # $2,099 COGS × 3, then grossed up for the configured 11% fee buffer.
    assert result.raw_total == 7075
    assert result.total == 7075
    assert result.min_applied is False
    assert sum(line.line_total for line in result.lines) == 7075


def test_permanent_complexity_selects_configured_multiplier():
    config = _permanent_config()

    aerial = pp.price_permanent(config, feet=100, complexity="aerial")
    easy = pp.price_permanent(config, feet=100, complexity="easy")
    standard = pp.price_permanent(config, feet=100, complexity="standard")
    complex_job = pp.price_permanent(config, feet=100, complexity="complex")

    assert (aerial.markup, easy.markup, standard.markup, complex_job.markup) == (1.5, 2.5, 3, 3.5)
    assert (aerial.raw_total, easy.raw_total, standard.raw_total, complex_job.raw_total) == (
        2105,
        3508,
        4210,
        4912,
    )


def test_permanent_complexity_order_cannot_be_reversed_by_saved_settings():
    config = _permanent_config(easy_markup=3.5, standard_markup=3, complex_markup=2.5)

    aerial = pp.price_permanent(config, feet=100, complexity="aerial")
    easy = pp.price_permanent(config, feet=100, complexity="easy")
    complex_job = pp.price_permanent(config, feet=100, complexity="complex")

    assert aerial.markup == 1.5
    assert easy.markup == 2.5
    assert complex_job.markup == 3.5
    assert aerial.total < easy.total < complex_job.total


def test_permanent_weights_markup_by_measured_run_footage():
    result = pp.price_permanent(
        _permanent_config(),
        feet=100,
        complexity_feet={"easy": 75, "complex": 25},
    )

    assert result.package_feet == 100
    assert result.markup == 2.75
    # $1,249 COGS × weighted 2.75 multiplier, then the configured fee buffer.
    assert result.raw_total == 3859


def test_permanent_applies_minimum():
    result = pp.price_permanent(_permanent_config(minimum=5000), feet=100)

    # $1,249 COGS × 3 grosses to $4,210; the $5,000 net floor grosses to $5,618.
    assert result.raw_total == 4210
    assert result.total == 5618
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
    # roofline 900 -> 1011; trees 2*260 & 1*520 each 520 -> 584 each = 1168;
    # bushes 4*35=140 -> 157; wreaths 2*85=170 -> 191;
    # takedown 0.25*(900+1040+140+170=2250)=562.5 -> 632; storage 200 -> 225.
    assert r.roofline_cost == 1011
    costs = {i.key: i.cost for i in r.items}
    assert costs["trees"] == 1168
    assert costs["bushes"] == 157
    assert costs["wreaths"] == 191
    # Categories with no selection are absent from the breakdown.
    assert "garland" not in costs
    assert r.takedown_cost == 632
    assert r.storage_cost == 225
    assert r.raw_total == 3384
    assert r.total == 3384
    assert sum(line.line_total for line in r.lines) == 3384


def test_christmas_prices_garland_per_linear_foot():
    cfg = _christmas_config()
    # Garland is per_ft: 80 ft * $8 = $640 net -> grossed. Folds into takedown base.
    r = pp.price_christmas(cfg, roofline_feet=0, items={"garland": {"standard": 80}})
    costs = {i.key: i.cost for i in r.items}
    garland = next(i for i in r.items if i.key == "garland")
    assert garland.unit == "per_ft"
    # 640 net grossed at 0.11 buffer -> round(640 / 0.89) = 719.
    assert costs["garland"] == 719
    assert r.total == 719
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
    # buffer 0.11 -> gross = round_half_up(net / 0.89):
    # roofline 600 -> 674; mini 300 -> 337; trees 240 -> 270; wreaths 85 -> 96.
    assert r.roofline_cost == 674
    costs = {i.key: i.cost for i in r.items}
    assert costs["mini_lights"] == 337
    mini = next(i for i in r.items if i.key == "mini_lights")
    assert mini.unit == "per_ft"
    assert costs["trees"] == 270
    assert costs["wreaths"] == 96
    # Unselected categories stay out of the breakdown.
    assert "bushes" not in costs
    assert "garland" not in costs
    assert r.raw_total == 1377
    assert r.total == 1377
    assert sum(line.line_total for line in r.lines) == 1377


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
    # 120 -> gross 135; no takedown line because config disables it.
    assert r.takedown_cost == 0
    assert r.total == 135


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
    # trees 260 -> 292; bushes 2*35=70 -> 79; wreaths 85 -> 96; roofline 600 -> 674.
    assert costs["trees"] == 292
    assert costs["bushes"] == 79
    assert costs["wreaths"] == 96
    assert r.roofline_cost == 674


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
    assert middle.roofline_cost == 1011
    assert {i.key for i in middle.items} == {"trees", "bushes"}
    # Premier is the full display: roofline + every decor category.
    assert premier.roofline_cost == 1011
    assert {i.key for i in premier.items} == {"trees", "bushes", "wreaths", "garland"}


def test_christmas_packages_are_monotonic_good_better_best():
    cfg = _christmas_packages_config()
    pkgs = pp.price_christmas_packages(cfg, roofline_feet=150, items=_PACKAGE_ITEMS)
    totals = [p.pricing.total for p in pkgs]
    # Each higher tier is a superset of coverage, so totals never decrease.
    assert totals == [1325, 2336, 3246]
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
    # The grossed job minimum (5000 -> 5618) floors every package independently.
    for p in pkgs:
        assert p.pricing.min_applied is True
        assert p.pricing.total == 5618


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
