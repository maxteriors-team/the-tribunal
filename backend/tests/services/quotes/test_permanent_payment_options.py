"""Focused unit coverage for Permanent quote snapshots and approval invariants."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.quote import Quote
from app.schemas.pricing import PricingSettings
from app.services.exceptions import ConflictError, ValidationError
from app.services.quotes import quote_service as quote_service_module
from app.services.quotes.quote_service import QuoteService


def _quote(*, service: str | None, total: float = 5200) -> Quote:
    quote = Quote(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        number="QUO-TEST",
        title="Permanent Lighting words do not grant eligibility",
        status="sent",
        currency="USD",
    )
    quote.total = total
    quote.proposal_document = {"service": service} if service else None
    quote.permanent_pricing_snapshot = None
    quote.payment_option = None
    return quote


def _snapshot(quote: Quote, *, material_cogs: float = 1000) -> None:
    quote.permanent_pricing_snapshot = QuoteService._new_permanent_snapshot(
        quote, PricingSettings(), material_cogs=material_cogs
    )


def test_snapshot_has_one_cent_rounded_price_and_private_cost_inputs() -> None:
    quote = _quote(service="permanent", total=5200.004)

    _snapshot(quote)

    assert quote.permanent_pricing_snapshot == {
        "cash_check_price": "5200.00",
        "financing_price": "5200.00",
        "provider": "GreenSky",
        "plan_number": "6124",
        "apr": "0",
        "term_months": 24,
        "merchant_fee_rate": "0.1525",
        "sales_commission_rate": "0.07",
        "material_cogs": "1000.00",
    }


def test_financing_requires_exact_snapshotted_permanent_service() -> None:
    eligible = _quote(service="permanent")
    _snapshot(eligible)
    titled_only = _quote(service="landscape")
    titled_only.permanent_pricing_snapshot = eligible.permanent_pricing_snapshot
    legacy = _quote(service="permanent")

    estimate = QuoteService._financing_for_quote(eligible)
    assert estimate is not None
    assert estimate.plan_number == "6124"
    assert estimate.monthly_payment == 216.67
    assert QuoteService._financing_for_quote(titled_only) is None
    assert QuoteService._financing_for_quote(legacy) is None


def test_new_snapshot_requires_one_option_and_retry_cannot_switch_it() -> None:
    quote = _quote(service="permanent")
    _snapshot(quote)

    with pytest.raises(ValidationError, match="Choose cash/check"):
        QuoteService._apply_approval_payment_option(quote, None, retry=False)
    QuoteService._apply_approval_payment_option(quote, "financing", retry=False)
    QuoteService._apply_approval_payment_option(quote, "financing", retry=True)
    assert quote.payment_option == "financing"
    with pytest.raises(ConflictError, match="cannot be changed"):
        QuoteService._apply_approval_payment_option(quote, "cash_check", retry=True)


def test_legacy_and_non_permanent_quotes_keep_old_approval_flow() -> None:
    legacy = _quote(service="permanent")
    other = _quote(service="landscape")

    QuoteService._apply_approval_payment_option(legacy, None, retry=False)
    QuoteService._apply_approval_payment_option(other, None, retry=False)
    with pytest.raises(ValidationError, match="only for Permanent"):
        QuoteService._apply_approval_payment_option(other, "financing", retry=False)


def test_repricing_syncs_both_prices_and_service_change_clears_snapshot() -> None:
    quote = _quote(service="permanent")
    _snapshot(quote)
    quote.total = 5100.126

    QuoteService._sync_permanent_snapshot_price(quote)
    assert quote.permanent_pricing_snapshot["cash_check_price"] == "5100.13"
    assert quote.permanent_pricing_snapshot["financing_price"] == "5100.13"

    quote.proposal_document = {"service": "mixed"}
    QuoteService._sync_permanent_snapshot_price(quote)
    assert quote.permanent_pricing_snapshot is None
    assert quote.payment_option is None


async def test_profitability_response_uses_snapshot_and_exact_default_costs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = _quote(service="permanent")
    _snapshot(quote)
    quote.payment_option = "financing"

    async def quote_lookup(*args: object, **kwargs: object) -> Quote:
        return quote

    monkeypatch.setattr(quote_service_module, "get_or_404", quote_lookup)
    response = await QuoteService(AsyncMock()).get_permanent_profitability(
        quote.workspace_id, quote.id
    )

    assert response is not None
    assert response.selected_payment_option == "financing"
    assert response.cash_check.contract_price == response.financing.contract_price == 5200
    assert response.cash_check.merchant_fee == 0
    assert response.financing.merchant_fee == 793
    assert response.cash_check.sales_commission == response.financing.sales_commission == 364
    assert response.cash_check.contribution_before_labor == 3836
    assert response.financing.contribution_before_labor == 3043


async def test_profitability_returns_none_without_exact_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        currency="USD",
        proposal_document={"service": "landscape"},
        permanent_pricing_snapshot=None,
    )

    async def quote_lookup(*args: object, **kwargs: object) -> object:
        return quote

    monkeypatch.setattr(quote_service_module, "get_or_404", quote_lookup)
    assert (
        await QuoteService(AsyncMock()).get_permanent_profitability(quote.workspace_id, quote.id)
        is None
    )
