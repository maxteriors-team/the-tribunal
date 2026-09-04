"""Regression coverage for Permanent-only, one-price payment presentation.

Legacy global financing settings remain parseable but cannot affect customer prices or
put financing copy on Landscape, Christmas, Bistro, service, or mixed proposals.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.pricing import (
    FinancingConfig,
    PermanentConfig,
    PricingSettings,
    TierConfig,
    TierSection,
)
from app.schemas.proposal_wizard import (
    ProposalWizardPayload,
    WizardCharge,
    WizardFixtureQty,
)
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.proposal_builder import CatalogEntry, build_proposal_document


def _config(*, apr: float = 0) -> PricingSettings:
    return PricingSettings(
        financing=FinancingConfig(
            enabled=True,
            provider="Legacy provider",
            max_amount=99999,
            terms=[12],
            default_term=12,
            apr=0,
            fee_buffer=0.25,
            headline="Legacy financing copy",
        ),
        permanent=PermanentConfig(
            enabled=True,
            financing={
                "provider": "GreenSky",
                "plan_number": "6124",
                "apr": apr,
                "term_months": 24,
                "merchant_fee_rate": 0.1525,
                "sales_commission_rate": 0.07,
            },
        ),
    )


def _proposal(categories: list[str], *, amount: float = 5200, apr: float = 0):
    return build_proposal_document(
        _config(apr=apr),
        {},
        ProposalWizardPayload(
            categories=categories,
            additional_charges=[WizardCharge(description="Contract price", net_amount=amount)],
        ),
    )[0]


@pytest.mark.parametrize(
    "categories",
    [
        ["landscape"],
        ["christmas"],
        ["bistro"],
        ["service"],
        ["permanent", "landscape"],
    ],
)
def test_every_non_permanent_service_is_single_price_without_financing(categories: list[str]):
    document = _proposal(categories)

    assert document.service != "permanent"
    assert document.financing is None
    assert document.grand_financed_total == 5200
    assert document.grand_cash_total == 5200
    assert document.grand_monthly_payment == 0


def test_exact_permanent_snapshot_uses_equal_prices_and_green_sky_terms():
    document = _proposal(["permanent"])

    assert document.service == "permanent"
    assert document.grand_financed_total == 5200
    assert document.grand_cash_total == 5200
    assert document.grand_monthly_payment == 216.67
    assert document.financing is not None
    assert document.financing.provider == "GreenSky"
    assert document.financing.plan_number == "6124"
    assert document.financing.apr == 0
    assert document.financing.default_term == 24
    assert document.financing.headline is None
    assert document.financing.body is None
    assert document.financing.points == []
    assert document.financing.disclaimer == "Estimated payment only. Subject to credit approval."


def test_permanent_nonzero_apr_uses_amortization():
    document = _proposal(["permanent"], amount=10000, apr=0.12)

    assert document.grand_monthly_payment == 470.73
    assert document.financing is not None
    assert document.financing.apr == 0.12


def test_fixed_price_book_item_still_reprices_every_package() -> None:
    """The financing rewrite must not drop fixed-item package coverage."""
    config = _config().model_copy(
        update={
            "tier_order": ["good", "best"],
            "tiers": [
                TierConfig(
                    key=key,
                    label=key.title(),
                    name=key.title(),
                    sections=[TierSection(title="Lighting", item_ids=["path", "accent"])],
                )
                for key in ("good", "best")
            ],
        }
    )
    catalog = {
        "path": CatalogEntry(item_id="path", name="Path Light", unit_price=Decimal("178")),
        "accent": CatalogEntry(item_id="accent", name="Accent Uplight", unit_price=Decimal("267")),
        "designer-uplight": CatalogEntry(
            item_id="designer-uplight",
            name="Designer Uplight",
            unit_price=Decimal("400"),
        ),
    }
    payload = ProposalWizardPayload(
        categories=["landscape"],
        pricing_source="price_book",
        selected_tier="best",
        quantities=[
            WizardFixtureQty(item_id="path", quantity=9),
            WizardFixtureQty(item_id="accent", quantity=6),
        ],
        fixed_items=[WizardFixtureQty(item_id="designer-uplight", quantity=1)],
    )

    document, _ = build_proposal_document(config, catalog, payload)

    for tier in document.tiers:
        fixed = next(line for line in tier.lines if line.item_id == "designer-uplight")
        assert fixed.quantity == 1
        assert fixed.unit_price == 400
        assert tier.pricing.financed_total == 3604


def test_legacy_global_buffer_never_changes_any_service_price():
    config = _config()

    assert pp.price_buffer(config) == 0
    assert pp.gross_up_price(Decimal("5200.25"), config) == Decimal("5200.25")
    assert pp.cash_price(Decimal("5200.25"), config) == Decimal("5200.25")
    assert pp.cash_savings(Decimal("5200.25"), config) == 0
    assert pp.financing_estimate(5200, {"landscape": 5200}, config) is None


def test_tier_pricing_contains_no_hidden_financing_derivations():
    tier = pp.price_tier(5000, 200, _config())

    assert tier.financed_total == tier.cash_total == 5200
    assert tier.cash_savings == 0
    assert tier.monthly_payment == 0
    assert tier.monthly_by_term == {}
    assert tier.commission_financed == tier.commission_cash == 0
