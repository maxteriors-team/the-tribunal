"""Regression + contract tests for the category-agnostic package presentation.

Two jobs:

* **Freeze the Christmas path.** Seasonal Good/Better/Best is live, revenue-
  critical code. Every assertion below is a byte-level snapshot of what
  :func:`price_christmas_packages` and :func:`build_public_comparison_packages`
  emit today for a fixed config + measurement, so generalizing the presentation
  layer to non-seasonal service categories cannot silently reprice, reorder, or
  re-copy a seasonal proposal that is already in a customer's inbox.
* **Lock the privacy boundary.** ``build_public_comparison_packages`` leaks a
  package's ``total`` and nothing else. The full pricing breakdown carries the
  measurement (``roofline_feet`` / ``roofline_cost``) and must never cross to
  the homeowner — for *any* category, not just Christmas.

Pure (no DB / no marker) so they run in the default suite.
"""

from __future__ import annotations

import pytest

from app.schemas.pricing import (
    ChristmasConfig,
    FinancingConfig,
    PackagePricing,
    PermanentConfig,
    PricingSettings,
    ServiceInclusion,
    ServicePackage,
    ServicePackageConfig,
)
from app.services.quotes.proposal_pricing import (
    price_christmas_packages,
    price_service_packages,
)
from app.services.quotes.quote_service import (
    _resolve_recommended_package,
    build_public_comparison_packages,
)


def _config(**overrides) -> PricingSettings:
    """Seasonal packages on, zero gross-up buffer so the dollars are exact."""
    base = {
        "financing": FinancingConfig(enabled=True, fee_buffer=0.0),
        "permanent": PermanentConfig(enabled=True, per_ft=30, controller_base=300),
        "christmas": ChristmasConfig(
            enabled=True,
            roofline_per_ft=6,
            minimum=0,
            packages_enabled=True,
        ),
        "comparison_years": 5,
    }
    base.update(overrides)
    return PricingSettings(**base)


# One measurement prices every package; these are the shipped default tiers.
_MEASUREMENT = {
    "roofline_feet": 100.0,
    "items": {"trees": {"medium": 2}, "garland": {"standard": 50}},
}


def _priced():
    return price_christmas_packages(_config(), **_MEASUREMENT)


# --------------------------------------------------------------------------- #
# Frozen Christmas output — the "nothing may change" snapshot
# --------------------------------------------------------------------------- #
def test_christmas_package_cards_are_frozen() -> None:
    """Every field the seasonal card renders from, exactly as it ships today."""
    cards = [
        {
            "key": p.key,
            "label": p.label,
            "name": p.name,
            "marker": p.marker,
            "experience": p.experience,
            "points": p.points,
            "value_tag": p.value_tag,
            "popular": p.popular,
            "includes_roofline": p.includes_roofline,
            "total": p.pricing.total,
        }
        for p in _priced()
    ]

    assert cards == [
        {
            "key": "essential",
            "label": "Essential — Trees & Bushes",
            "name": "The Essential",
            "marker": "\u25cf",
            "experience": (
                "A festive first impression. Your trees and bushes wrapped and "
                "glowing — a clean, cheerful look without the roofline."
            ),
            "points": [
                "Trees and bushes professionally wrapped",
                "Warm, welcoming curb appeal",
                "Lowest-cost way to get a holiday look",
            ],
            "value_tag": None,
            "popular": False,
            "includes_roofline": False,
            "total": 520.0,
        },
        {
            "key": "middle",
            "label": "Middle — Roofline + Trees & Bushes",
            "name": "The Classic",
            "marker": "\u25c6",
            "experience": (
                "The complete outline. A crisp roofline plus wrapped trees and "
                "bushes — the look most homes are known for."
            ),
            "points": [
                "Full roofline outlined in seasonal lighting",
                "Trees and bushes wrapped to match",
                "The classic, balanced holiday display",
            ],
            "value_tag": None,
            "popular": True,
            "includes_roofline": True,
            "total": 1120.0,
        },
        {
            "key": "premier",
            "label": "Premier — The Full Display",
            "name": "The Premier",
            "marker": "\u2605",
            "experience": (
                "The whole property, transformed. Roofline, trees, bushes, "
                "wreaths, and garland — nothing left dark."
            ),
            "points": [
                "Everything in Middle, fully dressed",
                "Wreaths and garland on entries and railings",
                "The magazine-cover holiday home",
            ],
            "value_tag": "\u2605 The Full Display",
            "popular": False,
            "includes_roofline": True,
            "total": 1520.0,
        },
    ]


def test_christmas_package_pricing_breakdown_is_frozen() -> None:
    """The internal breakdown behind the middle card, line for line."""
    middle = next(p for p in _priced() if p.key == "middle")

    assert middle.pricing.model_dump() == {
        "roofline_feet": 100.0,
        "roofline_cost": 600.0,
        "items": [
            {"key": "trees", "label": "Trees", "unit": "each", "cost": 520.0},
        ],
        "takedown_cost": 0.0,
        "storage_cost": 0.0,
        "minimum": 0.0,
        "raw_total": 1120.0,
        "total": 1120.0,
        "min_applied": False,
        "lines": [
            {
                "label": "Roofline",
                "detail": "Seasonal C9/mini install",
                "quantity": 100.0,
                "unit_price": 6.0,
                "line_total": 600.0,
            },
            {
                "label": "Medium tree (8–15 ft)",
                "detail": None,
                "quantity": 2.0,
                "unit_price": 260.0,
                "line_total": 520.0,
            },
        ],
    }


def test_christmas_pricing_model_dump_key_order_is_frozen() -> None:
    """Serialized field order is part of the wire contract for saved links."""
    essential = next(p for p in _priced() if p.key == "essential")

    assert list(essential.model_dump().keys()) == [
        "key",
        "label",
        "name",
        "marker",
        "experience",
        "points",
        "value_tag",
        "popular",
        "includes_roofline",
        "pricing",
    ]


def test_public_christmas_cards_are_frozen() -> None:
    """The exact JSON the homeowner's comparison page renders from."""
    public = build_public_comparison_packages(_priced(), None)

    assert [card.model_dump() for card in public] == [
        {
            "key": "essential",
            "label": "Essential — Trees & Bushes",
            "name": "The Essential",
            "marker": "\u25cf",
            "experience": (
                "A festive first impression. Your trees and bushes wrapped and "
                "glowing — a clean, cheerful look without the roofline."
            ),
            "points": [
                "Trees and bushes professionally wrapped",
                "Warm, welcoming curb appeal",
                "Lowest-cost way to get a holiday look",
            ],
            "value_tag": None,
            "popular": False,
            "includes_roofline": False,
            "total": 520.0,
            "recommended": False,
        },
        {
            "key": "middle",
            "label": "Middle — Roofline + Trees & Bushes",
            "name": "The Classic",
            "marker": "\u25c6",
            "experience": (
                "The complete outline. A crisp roofline plus wrapped trees and "
                "bushes — the look most homes are known for."
            ),
            "points": [
                "Full roofline outlined in seasonal lighting",
                "Trees and bushes wrapped to match",
                "The classic, balanced holiday display",
            ],
            "value_tag": None,
            "popular": True,
            "includes_roofline": True,
            "total": 1120.0,
            "recommended": False,
        },
        {
            "key": "premier",
            "label": "Premier — The Full Display",
            "name": "The Premier",
            "marker": "\u2605",
            "experience": (
                "The whole property, transformed. Roofline, trees, bushes, "
                "wreaths, and garland — nothing left dark."
            ),
            "points": [
                "Everything in Middle, fully dressed",
                "Wreaths and garland on entries and railings",
                "The magazine-cover holiday home",
            ],
            "value_tag": "\u2605 The Full Display",
            "popular": False,
            "includes_roofline": True,
            "total": 1520.0,
            "recommended": True,
        },
    ]


def test_public_christmas_cards_honor_an_explicit_rep_pick() -> None:
    """A rep's pick moves the highlight and changes nothing else."""
    default = [c.model_dump() for c in build_public_comparison_packages(_priced(), None)]
    picked = [c.model_dump() for c in build_public_comparison_packages(_priced(), "middle")]

    assert [c["recommended"] for c in picked] == [False, True, False]
    # Only the highlight moved: every other field on every card is untouched.
    for before, after in zip(default, picked, strict=True):
        assert {k: v for k, v in before.items() if k != "recommended"} == {
            k: v for k, v in after.items() if k != "recommended"
        }


@pytest.mark.parametrize("selected", [None, "", "nope", "middle"])
def test_public_christmas_cards_keep_low_to_high_order(selected: str | None) -> None:
    """Order is the ladder itself — never re-sorted by price or by the pick."""
    public = build_public_comparison_packages(_priced(), selected)
    assert [c.key for c in public] == ["essential", "middle", "premier"]
    assert [c.total for c in public] == [520.0, 1120.0, 1520.0]


# --------------------------------------------------------------------------- #
# Recommended-package resolution (shared by every category)
# --------------------------------------------------------------------------- #
def test_recommended_falls_back_to_the_most_inclusive_tier() -> None:
    packages = _priced()

    assert _resolve_recommended_package(packages, None) is packages[-1]
    assert _resolve_recommended_package(packages, "") is packages[-1]
    # A stale key from an old shared link must not crash or blank the highlight.
    assert _resolve_recommended_package(packages, "deleted-tier") is packages[-1]
    assert _resolve_recommended_package(packages, "middle") is packages[1]
    assert _resolve_recommended_package([], "middle") is None


def test_no_packages_yields_no_public_cards() -> None:
    """à la carte workspaces send an empty ladder, not an empty-state card."""
    assert build_public_comparison_packages([], None) == []


# --------------------------------------------------------------------------- #
# Privacy boundary — only ``total`` crosses to the homeowner
# --------------------------------------------------------------------------- #
def test_public_cards_never_carry_the_measurement() -> None:
    """The pricing breakdown (and the feet inside it) stays server-side."""
    priced = _priced()
    # Precondition: the internal breakdown really does carry the measurement, so
    # this test fails loudly if the leak-shaped field is ever renamed instead of
    # quietly passing against a model that no longer has anything to leak.
    assert priced[1].pricing.roofline_feet == 100.0

    forbidden = {
        "pricing",
        "roofline_feet",
        "roofline_cost",
        "feet",
        "per_ft",
        "lines",
        "raw_total",
        "minimum",
        "items",
        "includes",
    }
    for card in build_public_comparison_packages(priced, None):
        payload = card.model_dump()
        assert forbidden.isdisjoint(payload.keys()), payload.keys()
        # Totals-only: no nested structure at all can smuggle a breakdown out.
        assert not any(isinstance(v, dict) for v in payload.values())


# --------------------------------------------------------------------------- #
# Non-seasonal service categories on the same presentation path
# --------------------------------------------------------------------------- #
def _roof_config(**category_overrides) -> PricingSettings:
    """A roofing category priced per square, with a shared scope catalog."""
    category = {
        "service_category": "roof",
        "label": "Roof Replacement",
        "enabled": True,
        "basis": "per_unit",
        "unit_label": "squares",
        "inclusions": [
            ServiceInclusion(key="ice_shield", label="Ice & water shield", price=40, per_unit=True),
            ServiceInclusion(key="ridge_vent", label="Ridge vent", price=600),
        ],
        "packages": [
            ServicePackage(key="good", label="Good", name="Essential", per_unit_price=400),
            ServicePackage(
                key="better",
                label="Better",
                name="Preferred",
                per_unit_price=500,
                popular=True,
                recommended=True,
                inclusion_keys=["ice_shield"],
            ),
            ServicePackage(
                key="best",
                label="Best",
                name="Premier",
                base_price=1000,
                per_unit_price=600,
                value_tag="Lifetime system",
                inclusion_keys=["ice_shield", "ridge_vent"],
            ),
        ],
    }
    category.update(category_overrides)
    return _config(service_packages=[ServicePackageConfig(**category)])


def test_service_packages_price_from_one_measurement() -> None:
    priced = price_service_packages(_roof_config(), "roof", units=30)

    # good 30*400; better 30*500 + 30*40 shield; best 1000 + 30*600 + shield + vent.
    assert {p.key: p.total for p in priced} == {
        "good": 12_000.0,
        "better": 16_200.0,
        "best": 20_800.0,
    }
    assert [p.key for p in priced] == ["good", "better", "best"]
    assert priced[1].pricing.inclusions[0].label == "Ice & water shield"


def test_flat_basis_ignores_the_measurement() -> None:
    """An operator who prices whole jobs never has to invent a unit count."""
    config = _roof_config(basis="flat")
    priced = price_service_packages(config, "roof", units=30)

    # Only the flat components bill: best = 1000 base + 600 ridge vent.
    assert {p.key: p.total for p in priced} == {"good": 0.0, "better": 0.0, "best": 1_600.0}


def test_service_category_job_minimum_lifts_the_total() -> None:
    config = _roof_config(minimum=15_000)
    priced = price_service_packages(config, "roof", units=30)

    good = next(p for p in priced if p.key == "good")
    assert good.pricing.raw_total == 12_000.0
    assert good.total == 15_000.0
    assert good.pricing.min_applied is True


@pytest.mark.parametrize("lookup", ["roof", "Roof", "  ROOF "])
def test_service_category_lookup_is_case_and_space_insensitive(lookup: str) -> None:
    """``service_category`` is free-form text an operator types into the price book."""
    assert len(price_service_packages(_roof_config(), lookup, units=10)) == 3


@pytest.mark.parametrize("lookup", ["siding", "", "   "])
def test_unknown_service_category_sells_a_la_carte(lookup: str) -> None:
    assert price_service_packages(_roof_config(), lookup, units=10) == []


def test_disabled_service_category_sells_a_la_carte() -> None:
    assert price_service_packages(_roof_config(enabled=False), "roof", units=10) == []


def test_service_packages_render_through_the_same_public_mapping() -> None:
    """The whole point: one mapping, one card payload, any trade."""
    public = build_public_comparison_packages(
        price_service_packages(_roof_config(), "roof", units=30), None
    )

    assert [c.model_dump() for c in public] == [
        {
            "key": "good",
            "label": "Good",
            "name": "Essential",
            "marker": None,
            "experience": None,
            "points": [],
            "value_tag": None,
            "popular": False,
            "includes_roofline": False,
            "total": 12_000.0,
            "recommended": False,
        },
        {
            "key": "better",
            "label": "Better",
            "name": "Preferred",
            "marker": None,
            "experience": None,
            "points": [],
            "value_tag": None,
            "popular": True,
            "includes_roofline": False,
            "total": 16_200.0,
            # The steered middle option, not the most expensive tier.
            "recommended": True,
        },
        {
            "key": "best",
            "label": "Best",
            "name": "Premier",
            "marker": None,
            "experience": None,
            "points": [],
            "value_tag": "Lifetime system",
            "popular": False,
            "includes_roofline": False,
            "total": 20_800.0,
            "recommended": False,
        },
    ]


def test_rep_pick_still_outranks_a_flagged_tier() -> None:
    priced = price_service_packages(_roof_config(), "roof", units=30)
    public = build_public_comparison_packages(priced, "best")

    assert [c.key for c in public if c.recommended] == ["best"]


def test_service_packages_fall_back_to_most_inclusive_without_a_flag() -> None:
    """No flagged tier => the seasonal rule (most inclusive wins) still applies."""
    config = _roof_config(
        packages=[
            ServicePackage(key="good", label="Good", per_unit_price=400),
            ServicePackage(key="best", label="Best", per_unit_price=600),
        ]
    )
    priced = price_service_packages(config, "roof", units=30)

    assert _resolve_recommended_package(priced, None) is priced[-1]


def test_service_cards_never_carry_the_measurement() -> None:
    """Same privacy boundary as seasonal: units stay server-side."""
    priced = price_service_packages(_roof_config(), "roof", units=30)
    assert priced[0].pricing.units == 30.0  # the breakdown really does hold it

    forbidden = {"pricing", "units", "unit_label", "lines", "raw_total", "inclusions"}
    for card in build_public_comparison_packages(priced, None):
        payload = card.model_dump()
        assert forbidden.isdisjoint(payload.keys()), payload.keys()
        assert not any(isinstance(v, dict) for v in payload.values())


def test_new_service_category_defaults_to_three_tiers_steering_the_middle() -> None:
    """An operator who only names a category still gets the good/better/best lever."""
    category = ServicePackageConfig(service_category="siding", label="Siding")

    assert [p.key for p in category.packages] == ["good", "better", "best"]
    assert [p.recommended for p in category.packages] == [False, True, False]
    # Nothing is priced until the operator types a number.
    assert all(p.base_price == 0 and p.per_unit_price == 0 for p in category.packages)


def test_both_package_kinds_satisfy_the_presentation_contract() -> None:
    """Structural conformance is the refactor's actual invariant."""
    seasonal = _priced()[0]
    service = price_service_packages(_roof_config(), "roof", units=30)[0]

    for pkg in (seasonal, service):
        assert isinstance(pkg, PackagePricing)
        assert pkg.total == pkg.pricing.total

    assert seasonal.includes == {"roofline": False}
    assert seasonal.recommended is False
    assert service.includes == {}


# --------------------------------------------------------------------------- #
# Backward compatibility of the settings blob
# --------------------------------------------------------------------------- #
def test_existing_settings_blob_parses_without_service_packages() -> None:
    """A stored config written before service packages existed is unaffected."""
    stored = {
        "christmas": {"enabled": True, "roofline_per_ft": 6, "packages_enabled": True},
        "comparison_years": 7,
    }
    config = PricingSettings(**stored)

    assert config.service_packages == []
    assert config.comparison_years == 7
    assert config.christmas.packages_enabled is True
    # And it still prices its seasonal ladder exactly as before.
    assert [p.key for p in price_christmas_packages(config, roofline_feet=100)] == [
        "essential",
        "middle",
        "premier",
    ]


def test_service_packages_do_not_disturb_the_seasonal_ladder() -> None:
    """Configuring roofing must not move a single seasonal number or card."""
    with_roof = price_christmas_packages(_roof_config(), **_MEASUREMENT)

    assert [p.model_dump() for p in with_roof] == [p.model_dump() for p in _priced()]
