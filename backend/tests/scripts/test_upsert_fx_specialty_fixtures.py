from __future__ import annotations

import copy

import pytest

from scripts.demo.seed_lighting_workspace import PRICING
from scripts.ops.upsert_fx_specialty_fixtures import (
    SPECIALTY_SECTION_TITLE,
    SPECIALTY_SKUS,
    merge_premier_specialty_section,
    specialty_catalog_payload,
)


def test_specialty_catalog_payload_keeps_customer_price_and_procurement_cost_separate() -> None:
    wall = specialty_catalog_payload("59306832")
    underwater = specialty_catalog_payload("59407330")

    assert wall["unit_price"] == 775
    assert wall["attributes"]["unit_cost"] == 166.76
    assert wall["attributes"]["fixture_type"] == "walllight"
    assert wall["attributes"]["core_drill_required"] is True
    assert wall["components"] == [
        {"sku": "59306832", "description": "PO-ZD-1LED-RD-FB Wall Light", "qty": 1}
    ]

    assert underwater["unit_price"] == 1295
    assert underwater["attributes"]["unit_cost"] == 374.37
    assert underwater["attributes"]["list_price"] == 664.95
    assert underwater["attributes"]["fixture_type"] == "underwater"
    assert underwater["attributes"]["fixture_watts"] == 9.1
    assert underwater["components"] == [
        {"sku": "59407330", "description": "LL-ZDC-BS Underwater Light", "qty": 1}
    ]


def test_merge_premier_specialty_section_is_preserving_and_idempotent() -> None:
    original = copy.deepcopy(PRICING)
    premier = next(tier for tier in original["tiers"] if tier["key"] == "best")
    premier["sections"] = [
        section for section in premier["sections"] if section["title"] != SPECIALTY_SECTION_TITLE
    ]
    original["operator_custom_setting"] = {"keep": True}

    merged, changed = merge_premier_specialty_section(original)
    merged_again, changed_again = merge_premier_specialty_section(merged)

    assert changed is True
    assert changed_again is False
    assert original["tiers"][0]["sections"][-1]["title"] != SPECIALTY_SECTION_TITLE
    assert merged["operator_custom_setting"] == {"keep": True}
    assert merged_again == merged

    premier = next(tier for tier in merged["tiers"] if tier["key"] == "best")
    specialty = next(
        section for section in premier["sections"] if section["title"] == SPECIALTY_SECTION_TITLE
    )
    assert specialty["item_ids"] == list(SPECIALTY_SKUS)


def test_merge_requires_an_existing_premier_tier() -> None:
    pricing = copy.deepcopy(PRICING)
    pricing["tiers"] = [tier for tier in pricing["tiers"] if tier["key"] != "best"]

    with pytest.raises(ValueError, match="Premier"):
        merge_premier_specialty_section(pricing)
