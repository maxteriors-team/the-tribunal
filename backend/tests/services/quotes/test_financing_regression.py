"""Byte-level regression lock on the lighting/landscape financing presentation.

Financing used to be a lighting-only feature: :class:`FinancingConfig` was
documented as "shared across lighting brands", and ``ProposalFinancing.enabled``
was a straight copy of ``config.financing.enabled``. Making it service-category
aware (so a roof or siding job gets a monthly estimate and a $400 gutter cleaning
does not) rewired that flag through
:func:`app.services.quotes.proposal_pricing.financing_is_eligible`.

The invariant tests in :mod:`test_proposal_pricing` prove the new gate behaves
sensibly per category. These assert something blunter: **an already-sold lighting
proposal still serializes the exact same financing block and the exact same
money.** A quote a customer signed at "$417/month" must not silently re-render.

Two properties are pinned here, both deliberately:

1. The financing *presentation* payload for a landscape quote, byte-for-byte.
2. The ``fee_buffer`` margin math (gross-up + cash reversal), which category
   eligibility must never touch. A bug there silently destroys margin on every
   financed job, and unlike a display bug it is invisible until payout.

Pure and DB-free. If a number below changes, that is a product decision about
already-sold work, not a test to update reflexively.
"""

from __future__ import annotations

from decimal import Decimal

from app.schemas.pricing import (
    BistroConfig,
    BistroInstallationConfig,
    CashDiscountConfig,
    ChristmasConfig,
    CommissionConfig,
    FinancingConfig,
    PermanentConfig,
    PermanentGreenSkyConfig,
    PermanentPackage,
    PricingSettings,
    TierConfig,
    TierSection,
)
from app.schemas.proposal_wizard import (
    ProposalWizardPayload,
    WizardBistroRun,
    WizardBistroSelection,
    WizardCharge,
    WizardChristmasSelection,
    WizardFixtureQty,
    WizardPermanentSelection,
)
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.proposal_builder import CatalogEntry, build_proposal_document

# --------------------------------------------------------------------------- #
# The frozen lighting workspace: the money knobs a real landscape brand runs on.
# Spelled out rather than taken from schema defaults, so a future default change
# cannot quietly move the numbers this file exists to protect.
# --------------------------------------------------------------------------- #
FROZEN_FINANCING = FinancingConfig(
    enabled=True,
    provider="Wisetack",
    max_amount=25000,
    terms=[6, 12, 24],
    default_term=24,
    apr=0.0,
    fee_buffer=0.11,
    headline="0% APR financing available.",
    body="Approved buyers can spread this project over monthly payments.",
    points=["No prepayment penalty", "Soft credit check to see your options"],
    disclaimer="Estimate only, not an offer of credit. Subject to application and approval.",
)

FROZEN_TIERS = [
    TierConfig(
        key="good",
        label="Good",
        name="The Essential",
        sections=[TierSection(title="Path & Accent", item_ids=["path", "accent"])],
    ),
    TierConfig(
        key="best",
        label="Best",
        name="The Signature",
        popular=True,
        sections=[TierSection(title="Path & Accent", item_ids=["path", "accent"])],
    ),
]

FROZEN_CATALOG = {
    "path": CatalogEntry(item_id="path", name="Path Light", unit_price=Decimal("178")),
    "accent": CatalogEntry(item_id="accent", name="Accent Uplight", unit_price=Decimal("267")),
}


def _lighting_config(**overrides) -> PricingSettings:
    """A landscape-lighting workspace pinned to the shipped money knobs."""
    base = {
        "financing": FROZEN_FINANCING,
        "cash_discount": CashDiscountConfig(enabled=True, card_reserve_rate=0.03),
        "commission": CommissionConfig(enabled=True, rate=0.12, in_price=False),
        "tier_order": ["good", "best"],
        "tiers": FROZEN_TIERS,
    }
    base.update(overrides)
    return PricingSettings(**base)


def _landscape_payload(**overrides) -> ProposalWizardPayload:
    """A landscape quote: 10 path lights + 6 uplights on the Best package."""
    data = {
        "categories": ["landscape"],
        "selected_tier": "best",
        "quantities": [
            WizardFixtureQty(item_id="path", quantity=10),
            WizardFixtureQty(item_id="accent", quantity=6),
        ],
    }
    data.update(overrides)
    return ProposalWizardPayload(**data)


# --------------------------------------------------------------------------- #
# 1. The financing presentation a lighting client already received
# --------------------------------------------------------------------------- #
def test_landscape_proposal_financing_block_is_byte_identical():
    """The snapshotted financing copy a landscape client sees, pinned exactly.

    This is the block ``client_safe_document`` forwards to the public proposal
    page, so these bytes are literally what an already-shared link renders.
    """
    document, _ = build_proposal_document(
        _lighting_config(), FROZEN_CATALOG, _landscape_payload()
    )

    assert document.financing.model_dump_json().encode() == (
        b'{"enabled":true,"provider":"Wisetack","terms":[6,12,24],"default_term":24,'
        b'"max_amount":25000.0,"headline":"0% APR financing available.",'
        b'"body":"Approved buyers can spread this project over monthly payments.",'
        b'"points":["No prepayment penalty","Soft credit check to see your options"],'
        b'"disclaimer":"Estimate only, not an offer of credit. '
        b'Subject to application and approval."}'
    )


def test_landscape_tier_and_grand_money_are_byte_identical():
    """Every money figure on the landscape document, pinned exactly.

    Category eligibility is presentation-only, so the priced tiers, the selected
    package totals, and the grand totals must be untouched by it.
    """
    document, _ = build_proposal_document(
        _lighting_config(), FROZEN_CATALOG, _landscape_payload()
    )
    best = next(view for view in document.tiers if view.key == "best")

    assert best.pricing.model_dump_json().encode() == (
        b'{"base":3800.0,"additional":0.0,"financed_total":3800.0,'
        b'"cash_total":3483.0,"cash_savings":317.0,"monthly_payment":158.33,'
        b'"monthly_by_term":{"6":633.33,"12":316.67,"24":158.33},'
        b'"commission_financed":456.0,"commission_cash":418.0}'
    )
    assert document.selected_financed_total == 3800.0
    assert document.selected_cash_total == 3483.0
    assert document.selected_monthly_payment == 158.33
    assert document.grand_financed_total == 3800.0
    assert document.grand_cash_total == 3483.0
    assert document.grand_monthly_payment == 158.33


def test_landscape_priced_only_through_add_on_charges_still_offers_financing():
    """A "Custom Quote" package sold purely on add-on charges keeps its estimate.

    The selected tier prices at $0 here, so the landscape *category* subtotal is
    zero while the quote total is not. Lighting categories ship with a zero
    minimum, which means "no floor" — this quote showed a monthly estimate before
    financing was category-aware and must keep showing one. Gating on a strictly
    positive subtotal instead would silently drop financing from this quote.
    """
    document, _ = build_proposal_document(
        _lighting_config(),
        FROZEN_CATALOG,
        _landscape_payload(
            quantities=[],
            additional_charges=[WizardCharge(description="Design & install", net_amount=4450)],
        ),
    )

    assert document.grand_financed_total > 0
    assert document.financing.enabled is True


def test_landscape_workspace_with_no_configured_tiers_still_offers_financing():
    """A quote whose workspace has no packages at all keeps its estimate too.

    There is no selected tier here, so nothing contributes a landscape subtotal.
    The quote is still a landscape quote, and landscape has no floor, so the
    estimate it showed before financing became category-aware survives.
    """
    config = _lighting_config(tier_order=[], tiers=[])
    document, _ = build_proposal_document(
        config,
        FROZEN_CATALOG,
        _landscape_payload(
            selected_tier=None,
            quantities=[],
            additional_charges=[WizardCharge(description="Custom design", net_amount=2670)],
        ),
    )

    assert document.tiers == []
    assert document.grand_financed_total == 3000.0
    assert document.financing.enabled is True


def test_financing_disabled_workspace_still_reports_disabled():
    """Turning financing off at the workspace level still wins over categories."""
    config = _lighting_config(financing=FinancingConfig(enabled=False, fee_buffer=0.11))
    document, _ = build_proposal_document(config, FROZEN_CATALOG, _landscape_payload())

    assert document.financing.enabled is False


def test_landscape_over_the_provider_cap_reports_disabled():
    """A quote above ``max_amount`` cannot be presented as financeable.

    Pre-existing behavior: ``monthly_payment`` already returned 0 over the cap,
    so no payment figure was ever rendered. The flag now agrees with the money.
    """
    config = _lighting_config()
    document, _ = build_proposal_document(
        config,
        FROZEN_CATALOG,
        _landscape_payload(
            quantities=[WizardFixtureQty(item_id="accent", quantity=200)],
        ),
    )

    assert document.grand_financed_total > config.financing.max_amount
    assert document.financing.enabled is False
    assert document.grand_monthly_payment == 0


def test_fixed_fixture_selection_reprices_every_package() -> None:
    catalog = {
        **FROZEN_CATALOG,
        "designer-uplight": CatalogEntry(
            item_id="designer-uplight",
            name="Designer Uplight",
            unit_price=Decimal("400"),
        ),
    }
    payload = _landscape_payload(
        pricing_source="price_book",
        quantities=[
            WizardFixtureQty(item_id="path", quantity=9),
            WizardFixtureQty(item_id="accent", quantity=6),
        ],
        fixed_items=[WizardFixtureQty(item_id="designer-uplight", quantity=1)],
    )

    document, _ = build_proposal_document(_lighting_config(), catalog, payload)

    for tier in document.tiers:
        fixed = next(line for line in tier.lines if line.item_id == "designer-uplight")
        assert fixed.quantity == 1
        assert fixed.unit_price == 400
        assert tier.pricing.financed_total == 3604


# --------------------------------------------------------------------------- #
# 2. The margin math category eligibility must never touch
# --------------------------------------------------------------------------- #
def test_fee_buffer_gross_up_and_cash_reversal_ignore_category_eligibility():
    """``fee_buffer`` grosses price up by ``price / (1 - fee_buffer)`` — always.

    Three workspaces with wildly different category eligibility (shipped
    defaults, nothing eligible, everything eligible at a high floor) must gross
    up and back out identically. Eligibility is a presentation gate; if it ever
    leaks into :func:`price_buffer` or :func:`cash_discount_rate`, every financed
    job quietly loses margin.
    """
    variants = [
        _lighting_config(),
        _lighting_config(
            financing=FROZEN_FINANCING.model_copy(update={"category_minimums": {}})
        ),
        _lighting_config(
            financing=FROZEN_FINANCING.model_copy(
                update={"category_minimums": {"landscape": 50000}}
            )
        ),
    ]

    for config in variants:
        # 1000 / (1 - 0.11) = 1123.59… -> 1124; cash backs the buffer out and
        # keeps the 3% card reserve: 1124 * (1 - (1 - 1.03 * 0.89)) = 1030.
        assert pp.price_buffer(config) == Decimal("0.11")
        assert pp.gross_up_price(1000, config) == Decimal("1124")
        assert pp.cash_price(1124, config) == Decimal("1030")
        assert pp.cash_savings(1124, config) == Decimal("94")

    # …and the ineligible workspaces really are ineligible, so the assertions
    # above are proving the buffer survives the gate rather than never meeting it.
    assert pp.financing_is_eligible(1124, {"landscape": 1124}, variants[0]) is True
    assert pp.financing_is_eligible(1124, {"landscape": 1124}, variants[1]) is False
    assert pp.financing_is_eligible(1124, {"landscape": 1124}, variants[2]) is False


def test_landscape_estimate_payload_is_byte_identical():
    """The client-safe estimate served on core quote + public proposal reads."""
    estimate = pp.financing_estimate(3800, {"landscape": 3800}, _lighting_config())

    assert estimate is not None
    assert estimate.model_dump_json().encode() == (
        b'{"provider":"Wisetack","terms":[6,12,24],"default_term":24,"apr":0.0,'
        b'"monthly_payment":158.33,'
        b'"monthly_by_term":{"6":633.33,"12":316.67,"24":158.33},'
        b'"headline":"0% APR financing available.",'
        b'"body":"Approved buyers can spread this project over monthly payments.",'
        b'"points":["No prepayment penalty","Soft credit check to see your options"],'
        b'"disclaimer":"Estimate only, not an offer of credit. '
        b'Subject to application and approval."}'
    )


def test_green_sky_config_does_not_reprice_any_other_service_path() -> None:
    """A merchant-program edit is presentation-only and Permanent-only."""
    permanent = PermanentConfig(
        enabled=True,
        packages=[PermanentPackage(feet=100, cost=1000)],
    )
    config = _lighting_config(
        permanent=permanent,
        christmas=ChristmasConfig(enabled=True, roofline_per_ft=6),
        bistro=BistroConfig(
            enabled=True,
            permanent=BistroInstallationConfig(
                label="Permanent Bistro Lighting", lights_per_ft=12, poles_each=75
            ),
        ),
    )
    enabled = config.model_copy(
        update={
            "permanent": permanent.model_copy(
                update={
                    "green_sky": PermanentGreenSkyConfig(
                        enabled=True,
                        merchant_number="1234567890",
                        plan_number="246810",
                        term_months=24,
                        apr_percent=0,
                        offer_details="Provider-approved test fixture copy.",
                    )
                }
            )
        }
    )
    payloads = [
        _landscape_payload(),
        ProposalWizardPayload(
            categories=["christmas"],
            christmas=WizardChristmasSelection(roofline_feet=120),
        ),
        ProposalWizardPayload(
            categories=["bistro"],
            bistro=WizardBistroSelection(
                runs=[WizardBistroRun(installation="permanent", feet=80, pole_count=2)]
            ),
        ),
        ProposalWizardPayload(
            categories=["permanent", "christmas"],
            permanent=WizardPermanentSelection(feet=100),
            christmas=WizardChristmasSelection(roofline_feet=120),
        ),
    ]

    for payload in payloads:
        before, _ = build_proposal_document(config, FROZEN_CATALOG, payload)
        after, _ = build_proposal_document(enabled, FROZEN_CATALOG, payload)

        assert before.service != "permanent"
        assert before.grand_financed_total > 0
        assert after.green_sky is None
        assert after.model_dump(exclude={"green_sky"}) == before.model_dump(exclude={"green_sky"})
