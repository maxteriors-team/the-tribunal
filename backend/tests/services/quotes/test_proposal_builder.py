"""Permanent GreenSky proposal snapshot and one-price contract tests."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.pricing import (
    CashDiscountConfig,
    ChristmasConfig,
    FinancingConfig,
    PermanentConfig,
    PermanentGreenSkyConfig,
    PermanentPackage,
    PricingSettings,
)
from app.schemas.proposal_wizard import (
    GREEN_SKY_APPLICATION_DISCLOSURE,
    GREEN_SKY_APPLICATION_URL,
    ProposalGreenSky,
    ProposalWizardPayload,
    WizardCharge,
    WizardChristmasSelection,
    WizardClient,
    WizardPermanentSelection,
    client_safe_document,
)
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.proposal_builder import build_proposal_document


def _program(*, enabled: bool = True) -> PermanentGreenSkyConfig:
    return PermanentGreenSkyConfig(
        enabled=enabled,
        merchant_number="1234567890",
        plan_number="246810",
        term_months=24,
        apr_percent=0,
        offer_details="0% APR for 24 months (provider-approved test fixture).",
    )


def _config(*, green_sky: PermanentGreenSkyConfig | None = None) -> PricingSettings:
    return PricingSettings(
        financing=FinancingConfig(enabled=True, fee_buffer=0.11),
        cash_discount=CashDiscountConfig(enabled=True, card_reserve_rate=0.03),
        permanent=PermanentConfig(
            enabled=True,
            packages=[PermanentPackage(feet=100, cost=1000)],
            standard_markup=3,
            green_sky=green_sky or PermanentGreenSkyConfig(),
        ),
        christmas=ChristmasConfig(enabled=True, roofline_per_ft=6),
    )


def _permanent_payload() -> ProposalWizardPayload:
    return ProposalWizardPayload(
        client=WizardClient(
            first_name="Private",
            last_name="Homeowner",
            email="private@example.com",
            phone="+15555550100",
            street="1 Private Lane",
        ),
        categories=["permanent"],
        permanent=WizardPermanentSelection(feet=100),
        additional_charges=[WizardCharge(description="Custom install", net_amount=100)],
    )


def test_permanent_green_sky_snapshot_is_fixed_and_public_safe() -> None:
    document, _ = build_proposal_document(_config(green_sky=_program()), {}, _permanent_payload())

    assert document.green_sky is not None
    assert document.green_sky.model_dump() == {
        "application_url": GREEN_SKY_APPLICATION_URL,
        "merchant_number": "1234567890",
        "plan_number": "246810",
        "apr_percent": 0.0,
        "term_months": 24,
        "offer_details": "0% APR for 24 months (provider-approved test fixture).",
        "disclosure": GREEN_SKY_APPLICATION_DISCLOSURE,
    }
    encoded = document.green_sky.model_dump_json()
    for private_value in (
        "Private",
        "private@example.com",
        "+15555550100",
        "1 Private Lane",
        "15.25",
        "merchant_fee",
        "fee_buffer",
    ):
        assert private_value not in encoded


def test_green_sky_application_destination_cannot_be_overridden() -> None:
    with pytest.raises(ValidationError):
        ProposalGreenSky(
            application_url="https://example.com/apply",
            merchant_number="1234567890",
            plan_number="246810",
            apr_percent=0,
            term_months=24,
            offer_details="Provider-approved test fixture copy.",
        )


def test_permanent_document_presents_one_contract_price_without_repricing_quote() -> None:
    config = _config(green_sky=_program())
    document, _ = build_proposal_document(config, {}, _permanent_payload())

    permanent = document.category_sections[0]
    assert permanent.financed_total > 0
    assert permanent.cash_total == permanent.financed_total
    assert permanent.cash_savings == 0
    assert document.grand_cash_total == document.grand_financed_total
    # The workspace's cash economics still exist; only the public snapshot is normalized.
    assert pp.cash_price(document.grand_financed_total, config) < Decimal(
        str(document.grand_financed_total)
    )


@pytest.mark.parametrize("enabled", [False, True])
def test_green_sky_is_omitted_from_every_non_permanent_service(enabled: bool) -> None:
    config = _config(green_sky=_program(enabled=enabled))
    christmas, _ = build_proposal_document(
        config,
        {},
        ProposalWizardPayload(
            categories=["christmas"],
            christmas=WizardChristmasSelection(roofline_feet=100),
        ),
    )
    mixed, _ = build_proposal_document(
        config,
        {},
        ProposalWizardPayload(
            categories=["permanent", "christmas"],
            permanent=WizardPermanentSelection(feet=100),
            christmas=WizardChristmasSelection(roofline_feet=100),
        ),
    )

    assert christmas.service == "christmas"
    assert mixed.service == "mixed"
    assert christmas.green_sky is None
    assert mixed.green_sky is None


def test_incomplete_enabled_green_sky_is_omitted_defensively() -> None:
    config = _config()
    config.permanent.green_sky = PermanentGreenSkyConfig.model_construct(
        enabled=True,
        merchant_number="1234567890",
        plan_number=None,
        term_months=24,
        apr_percent=0,
        offer_details="Provider-approved test fixture copy.",
    )

    document, _ = build_proposal_document(config, {}, _permanent_payload())

    assert document.green_sky is None


def test_existing_saved_snapshot_is_not_backfilled() -> None:
    stored = {
        "version": 1,
        "service": "permanent",
        "grand_financed_total": 4200.0,
        "grand_cash_total": 4200.0,
    }

    assert client_safe_document(stored) == stored
    assert "green_sky" not in json.dumps(client_safe_document(stored))
