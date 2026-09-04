"""A custom add-on charge can be pinned to one package.

An add-on has always ridden on *every* tier, which is right for a mobilization
fee and wrong for work only the top package needs: core drilling the Premier
install requires quietly inflated the Starter too, so the cheap option never
looked cheap. ``tier_key`` pins a charge to the tier it was sold with.

Pure-function tests over ``charges_for_tier`` \u2014 the whole rule lives there, and
the wizard flow's own DB tests cover the plumbing around it.
"""

from __future__ import annotations

import pytest

from app.schemas.pricing import TierPricing
from app.schemas.proposal_wizard import ProposalCharge, ProposalTierView
from app.services.quotes import proposal_pricing as pp
from app.services.quotes.proposal_builder import charges_for_tier


def _tier(key: str) -> ProposalTierView:
    return ProposalTierView(
        key=key,
        name=key.title(),
        label=key.title(),
        lines=[],
        pricing=TierPricing(
            base=1000.0,
            additional=0.0,
            financed_total=1000.0,
            cash_total=970.0,
            cash_savings=30.0,
            monthly_payment=42.0,
            commission_financed=0.0,
            commission_cash=0.0,
        ),
    )


TIERS = [_tier("best"), _tier("better"), _tier("essential")]

GLOBAL = ProposalCharge(description="Mobilization", amount=250.0)
BEST_ONLY = ProposalCharge(description="Core drilling", amount=900.0, tier_key="best")
BETTER_ONLY = ProposalCharge(description="Rock removal", amount=400.0, tier_key="better")


def _labels(charges: list[ProposalCharge]) -> list[str]:
    return [c.description for c in charges]


def test_unpinned_charge_still_rides_on_every_tier() -> None:
    """The default is unchanged: this is how every existing quote prices."""
    for key in ("best", "better", "essential"):
        assert _labels(charges_for_tier([GLOBAL], key, TIERS)) == ["Mobilization"]


def test_pinned_charge_applies_only_to_its_own_tier() -> None:
    charges = [GLOBAL, BEST_ONLY, BETTER_ONLY]

    assert _labels(charges_for_tier(charges, "best", TIERS)) == [
        "Mobilization",
        "Core drilling",
    ]
    assert _labels(charges_for_tier(charges, "better", TIERS)) == [
        "Mobilization",
        "Rock removal",
    ]
    # The cheap package finally prices as the cheap package.
    assert _labels(charges_for_tier(charges, "essential", TIERS)) == ["Mobilization"]


def test_stale_key_falls_back_to_global_rather_than_vanishing() -> None:
    """Money the rep typed must never silently disappear from a quote.

    The estimator drops a line whose key prices nothing, because that is only a
    preview. A charge is on a quote about to be sent, so an unknown key degrades
    to the old every-tier behaviour where the rep can still see it.
    """
    stale = ProposalCharge(description="Permit", amount=150.0, tier_key="deleted-tier")

    for key in ("best", "better", "essential"):
        assert _labels(charges_for_tier([stale], key, TIERS)) == ["Permit"]


def test_no_selection_still_charges_globals_only() -> None:
    """Before the client picks, a pinned charge is not yet owed."""
    assert _labels(charges_for_tier([GLOBAL, BEST_ONLY], None, TIERS)) == ["Mobilization"]


# --------------------------------------------------------------------------- #
# The card price must move too, not just the saved line items
# --------------------------------------------------------------------------- #
def test_pinned_charge_stays_out_of_other_tiers_card_prices() -> None:
    """The regression the rep actually sees.

    ``TierPricing.additional`` used to be the sum of *every* charge, so core
    drilling the Premier needed was baked into the Starter's posted price and the
    cheap package never looked cheap. The card and the saved quote must apply the
    same rule, or the document's displayed total drifts from the recomputed one.
    """
    from app.schemas.pricing import PricingSettings, TierConfig
    from app.schemas.proposal_wizard import ProposalWizardPayload, WizardCharge
    from app.services.quotes.proposal_builder import build_proposal_document

    config = PricingSettings(
        tier_order=["best", "essential"],
        tiers=[
            TierConfig(key="best", name="The Premier", label="Best"),
            TierConfig(key="essential", name="The Starter", label="Good"),
        ],
    )
    payload = ProposalWizardPayload(
        categories=["landscape"],
        additional_charges=[
            WizardCharge(description="Mobilization", net_amount=100),
            WizardCharge(description="Core drilling", net_amount=900, tier_key="best"),
        ],
    )

    doc, _ = build_proposal_document(config, {}, payload)
    by_key = {view.key: view for view in doc.tiers}

    premier_add = by_key["best"].pricing.additional
    starter_add = by_key["essential"].pricing.additional

    # The Starter carries only the global charge; the Premier carries both.
    assert starter_add > 0
    assert premier_add > starter_add
    selling_price = pp.gross_up_price(900, config)
    assert premier_add - starter_add == pytest.approx(float(selling_price))
