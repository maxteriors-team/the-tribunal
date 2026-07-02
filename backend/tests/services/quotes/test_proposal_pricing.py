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
    BistroConfig,
    BistroProduct,
    BistroTier,
    CarePlanConfig,
    CarePlanTier,
    CashDiscountConfig,
    CommissionConfig,
    FinancingConfig,
    PricingSettings,
    SavingsConfig,
    TaxConfig,
)
from app.services.quotes import proposal_pricing as pp


def _landscape_config(**overrides) -> PricingSettings:
    """A PricingSettings mirroring the landscape wizard's shared knobs."""
    base = dict(
        financing=FinancingConfig(
            enabled=True,
            max_amount=25000,
            terms=[6, 12, 24],
            default_term=24,
            apr=0.0,
            fee_buffer=0.11,
        ),
        cash_discount=CashDiscountConfig(enabled=True, card_reserve_rate=0.03),
        commission=CommissionConfig(enabled=True, rate=0.12, in_price=False),
        care_plan=CarePlanConfig(
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
        savings=SavingsConfig(
            per_visit_value=179,
            avoided_repair_per_fixture=28,
            assumed_repair_spend_per_fixture=40,
        ),
        bistro=BistroConfig(
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
    )
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
