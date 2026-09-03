"""Regression lock on direct seasonal-Christmas selling prices.

Legacy financing, cash-discount, and commission settings remain parseable, but
must not alter configured Christmas prices. Stored proposal snapshots protect
already-sent quotes; these DB-free tests pin the engine used for new quotes.
"""

from __future__ import annotations

from app.schemas.pricing import (
    CashDiscountConfig,
    ChristmasConfig,
    ChristmasPackage,
    CommissionConfig,
    FinancingConfig,
    PricingSettings,
    SeasonalItem,
    SizeRate,
)
from app.services.quotes import proposal_pricing as pp

# --------------------------------------------------------------------------- #
# The frozen workspace: the shipped defaults a real seasonal workspace runs on.
# --------------------------------------------------------------------------- #
FROZEN_ITEMS = [
    SeasonalItem(
        key="trees",
        label="Trees",
        unit="each",
        options=[
            SizeRate(key="small", name="Small tree (up to 8 ft)", price=120),
            SizeRate(key="medium", name="Medium tree (8–15 ft)", price=260),
            SizeRate(key="large", name="Large tree (15–25 ft)", price=520),
        ],
    ),
    SeasonalItem(
        key="bushes",
        label="Bushes & Shrubs",
        unit="each",
        options=[
            SizeRate(key="small", name="Small bush / shrub", price=35),
            SizeRate(key="large", name="Large bush / shrub", price=65),
        ],
    ),
    SeasonalItem(
        key="wreaths",
        label="Wreaths",
        unit="each",
        options=[SizeRate(key="w36", name="Wreath (36 in)", price=85)],
    ),
    SeasonalItem(
        key="garland",
        label="Garland",
        unit="per_ft",
        options=[SizeRate(key="standard", name="Garland (installed)", price=8)],
    ),
]


def _frozen_config(**christmas_overrides) -> PricingSettings:
    """Legacy money knobs remain stored but no longer alter selling prices."""
    return PricingSettings(
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
        christmas=ChristmasConfig(
            enabled=True,
            roofline_per_ft=6,
            items=FROZEN_ITEMS,
            takedown_enabled=True,
            takedown_rate=0.25,
            storage_price=200,
            **christmas_overrides,
        ),
    )


# A typical Detroit two-story: 160 ft of roofline, a couple of trees and bushes,
# one wreath, and a run of garland over the porch.
FROZEN_SELECTION = {
    "trees": {"medium": 2},
    "bushes": {"small": 4},
    "wreaths": {"w36": 1},
    "garland": {"standard": 20},
}


# --------------------------------------------------------------------------- #
# À la carte: the full seasonal quote
# --------------------------------------------------------------------------- #
def test_frozen_full_seasonal_quote_totals_are_unchanged():
    priced = pp.price_christmas(
        _frozen_config(),
        roofline_feet=160,
        items=FROZEN_SELECTION,
        takedown=True,
        storage=True,
    )

    assert priced.roofline_feet == 160
    assert priced.roofline_cost == 960
    assert priced.takedown_cost == 466.25
    assert priced.storage_cost == 200
    assert priced.raw_total == 2531.25
    assert priced.total == 2531.25
    assert priced.min_applied is False


def test_frozen_full_seasonal_quote_display_lines_are_unchanged():
    """The client reads these strings. Order, wording, and money are all pinned."""
    priced = pp.price_christmas(
        _frozen_config(),
        roofline_feet=160,
        items=FROZEN_SELECTION,
        takedown=True,
        storage=True,
    )

    assert [(line.label, line.line_total) for line in priced.lines] == [
        ("Roofline", 960),
        ("Medium tree (8–15 ft)", 520),
        ("Small bush / shrub", 140),
        ("Wreath (36 in)", 85),
        ("20 ft Garland (installed)", 160),
        ("Post-season takedown", 466.25),
        ("Off-season storage", 200),
    ]
    # The breakdown the customer sees must still add up to the posted total.
    assert sum(line.line_total for line in priced.lines) == priced.raw_total
    assert priced.lines[0].detail == "Seasonal C9/mini install"


def test_frozen_per_category_costs_are_unchanged():
    priced = pp.price_christmas(
        _frozen_config(),
        roofline_feet=160,
        items=FROZEN_SELECTION,
        takedown=True,
        storage=True,
    )

    assert [(cost.key, cost.unit, cost.cost) for cost in priced.items] == [
        ("trees", "each", 520),
        ("bushes", "each", 140),
        ("wreaths", "each", 85),
        ("garland", "per_ft", 160),
    ]


def test_frozen_install_only_quote_is_unchanged():
    """The same measurement without takedown or storage — the cheaper sale."""
    priced = pp.price_christmas(
        _frozen_config(),
        roofline_feet=160,
        items=FROZEN_SELECTION,
        takedown=False,
        storage=False,
    )

    assert priced.takedown_cost == 0
    assert priced.storage_cost == 0
    assert priced.raw_total == 1865
    assert [line.label for line in priced.lines] == [
        "Roofline",
        "Medium tree (8–15 ft)",
        "Small bush / shrub",
        "Wreath (36 in)",
        "20 ft Garland (installed)",
    ]


def test_frozen_job_minimum_still_lifts_a_small_quote():
    priced = pp.price_christmas(
        _frozen_config(minimum=900),
        roofline_feet=0,
        items={"wreaths": {"w36": 1}},
        takedown=False,
        storage=False,
    )

    assert priced.raw_total == 85
    assert priced.minimum == 900
    assert priced.total == 900
    assert priced.min_applied is True


# --------------------------------------------------------------------------- #
# Legacy stored blobs: a workspace that saved its config before decor was
# standardized must keep pricing to the cent.
# --------------------------------------------------------------------------- #
def test_frozen_legacy_blob_prices_identically_to_the_standardized_catalog():
    legacy = PricingSettings(
        financing=FinancingConfig(
            enabled=True, max_amount=25000, terms=[6, 12, 24], default_term=24, fee_buffer=0.11
        ),
        cash_discount=CashDiscountConfig(enabled=True, card_reserve_rate=0.03),
        commission=CommissionConfig(enabled=True, rate=0.12, in_price=False),
        christmas=ChristmasConfig.model_validate(
            {
                "enabled": True,
                "roofline_per_ft": 6,
                "takedown_enabled": True,
                "takedown_rate": 0.25,
                "storage_price": 200,
                "tree_rates": [{"key": "medium", "name": "Medium tree (8–15 ft)", "price": 260}],
                "bush_rates": [{"key": "small", "name": "Small bush / shrub", "price": 35}],
                "wreath_rates": [{"key": "w36", "name": "Wreath (36 in)", "price": 85}],
            }
        ),
    )

    priced = pp.price_christmas(
        legacy,
        roofline_feet=160,
        items={"trees": {"medium": 2}, "bushes": {"small": 4}, "wreaths": {"w36": 1}},
        takedown=True,
        storage=True,
    )

    # The standardized catalog's numbers minus the garland run and its share of
    # takedown — the legacy blob has no garland category to select.
    assert priced.roofline_cost == 960
    assert priced.takedown_cost == 426.25
    assert priced.storage_cost == 200
    assert priced.raw_total == 2331.25


# --------------------------------------------------------------------------- #
# Packages: the Good/Better/Best cards a package-tier refactor will touch.
# --------------------------------------------------------------------------- #
def _frozen_packages_config() -> PricingSettings:
    config = _frozen_config()
    config.christmas.packages_enabled = True
    config.christmas.package_order = ["essential", "middle", "premier"]
    config.christmas.packages = [
        ChristmasPackage(
            key="essential",
            label="Essential — Trees & Bushes",
            includes_roofline=False,
            item_keys=["trees", "bushes"],
        ),
        ChristmasPackage(
            key="middle",
            label="Middle — Roofline + Trees & Bushes",
            includes_roofline=True,
            item_keys=["trees", "bushes"],
            popular=True,
        ),
        ChristmasPackage(
            key="premier",
            label="Premier — The Full Display",
            includes_roofline=True,
            item_keys=["trees", "bushes", "wreaths", "garland"],
        ),
    ]
    return config


def test_frozen_package_totals_and_order_are_unchanged():
    priced = pp.price_christmas_packages(
        _frozen_packages_config(),
        roofline_feet=160,
        items=FROZEN_SELECTION,
        takedown=True,
        storage=True,
    )

    assert [(pkg.key, pkg.pricing.total) for pkg in priced] == [
        ("essential", 1025),
        ("middle", 2225),
        ("premier", 2531.25),
    ]
    # Widening coverage must never make a package cheaper.
    totals = [pkg.pricing.total for pkg in priced]
    assert totals == sorted(totals)
    assert [pkg.popular for pkg in priced] == [False, True, False]


def test_frozen_premier_package_matches_the_a_la_carte_quote():
    """The most inclusive package is the à la carte price of everything.

    This is the seam a package-tier refactor is most likely to break: packages
    must stay a *restriction* of the shared engine, never a second pricing path.
    """
    config = _frozen_packages_config()
    packages = pp.price_christmas_packages(
        config, roofline_feet=160, items=FROZEN_SELECTION, takedown=True, storage=True
    )
    a_la_carte = pp.price_christmas(
        _frozen_config(),
        roofline_feet=160,
        items=FROZEN_SELECTION,
        takedown=True,
        storage=True,
    )

    premier = next(pkg for pkg in packages if pkg.key == "premier")
    assert premier.pricing.total == a_la_carte.total
    assert [line.label for line in premier.pricing.lines] == [
        line.label for line in a_la_carte.lines
    ]
