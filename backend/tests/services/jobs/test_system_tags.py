"""Structured equipment classification for durable contact ownership tags."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.jobs.system_tags import (
    LIGHTING_SYSTEM_TAG,
    LUXOR_SYSTEM_TAG,
    LUXOR_UPGRADE_CANDIDATE_TAG,
    PERMANENT_LIGHT_SYSTEM_TAG,
    completed_install_tags,
    is_luxor_install,
)


def _job(*, project: dict | None = None, quote: dict | None = None):
    return SimpleNamespace(
        lighting_project_id=uuid.uuid4() if project is not None else None,
        lighting_project=SimpleNamespace(document=project) if project is not None else None,
        source_quote=SimpleNamespace(proposal_document=quote) if quote is not None else None,
    )


def test_any_landscape_project_adds_broad_lighting_owner_tag() -> None:
    assert completed_install_tags(_job(project={"shots": []})) == (LIGHTING_SYSTEM_TAG,)


def test_project_transformer_sku_adds_luxor_owner_tag() -> None:
    job = _job(
        project={
            "shots": [
                {
                    "design": {
                        "items": [
                            {
                                "productId": "fixture-transformer",
                                "catalogSku": "best-luxor",
                            }
                        ]
                    }
                }
            ]
        }
    )

    assert completed_install_tags(job) == (LIGHTING_SYSTEM_TAG, LUXOR_SYSTEM_TAG)


def test_selected_quote_tier_adds_luxor_when_project_plan_is_legacy() -> None:
    job = _job(
        project={"shots": []},
        quote={
            "selected_tier": "best",
            "tiers": [
                {
                    "key": "best",
                    "lines": [
                        {
                            "item_id": "best-luxor",
                            "name": "Luxor Smart 300W Transformer",
                            "transformer": True,
                        }
                    ],
                }
            ],
        },
    )

    assert is_luxor_install(job) is True


def test_fulfillment_sku_recognizes_historical_luxor_quote() -> None:
    job = _job(
        project={"shots": []},
        quote={
            "fulfillment": [{"sku": "59409312", "description": "Luxor 300W Transformer", "qty": 1}]
        },
    )

    assert is_luxor_install(job) is True


def test_unselected_luxor_tier_does_not_tag_a_lower_package_owner() -> None:
    job = _job(
        project={"shots": []},
        quote={
            "selected_tier": "essential",
            "tiers": [
                {
                    "key": "best",
                    "lines": [
                        {
                            "item_id": "best-luxor",
                            "name": "Luxor Smart 300W Transformer",
                            "transformer": True,
                        }
                    ],
                },
                {"key": "essential", "lines": []},
            ],
        },
    )

    assert is_luxor_install(job) is False


def test_non_luxor_transformer_gets_upgrade_segment_not_luxor_tag() -> None:
    job = _job(
        project={"shots": []},
        quote={
            "selected_tier": "essential",
            "tiers": [
                {
                    "key": "essential",
                    "lines": [
                        {
                            "item_id": "essential-ex-150",
                            "name": "EX 150W Transformer",
                            "transformer": True,
                        }
                    ],
                }
            ],
        },
    )

    assert completed_install_tags(job) == (
        LIGHTING_SYSTEM_TAG,
        LUXOR_UPGRADE_CANDIDATE_TAG,
    )


def test_permanent_quote_adds_broad_and_permanent_owner_tags() -> None:
    assert completed_install_tags(_job(quote={"service": "permanent"})) == (
        LIGHTING_SYSTEM_TAG,
        PERMANENT_LIGHT_SYSTEM_TAG,
    )


def test_mixed_quote_still_detects_permanent_category() -> None:
    assert completed_install_tags(
        _job(quote={"service": "mixed", "categories": ["landscape", "permanent"]})
    ) == (LIGHTING_SYSTEM_TAG, PERMANENT_LIGHT_SYSTEM_TAG)


def test_service_job_title_never_creates_an_ownership_tag() -> None:
    job = _job()
    job.title = "Install Luxor permanent lighting repair"

    assert completed_install_tags(job) == ()
