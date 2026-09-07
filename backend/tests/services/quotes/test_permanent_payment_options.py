"""Focused unit coverage for client-selected Permanent proposal payments."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.models.quote import Quote
from app.models.workspace import Workspace
from app.schemas.proposal import PublicProposalApprove
from app.services.exceptions import ConflictError, ValidationError
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
    quote.workspace = Workspace(
        id=quote.workspace_id,
        name="Enabled workspace",
        slug=f"payments-{uuid.uuid4().hex[:8]}",
        settings={"proposal_payments_enabled": True},
    )
    return quote


def test_payment_amounts_round_once_and_preserve_the_completion_balance() -> None:
    quote = _quote(service="permanent", total=5200.01)

    options = QuoteService._public_payment_options(quote, quote.total)

    assert options is not None
    assert options.fifty_percent_down_amount == 2600.01
    assert options.completion_balance == 2600.0
    assert options.pay_in_full_amount == 5200.01


def test_payment_choice_is_required_and_cannot_change_after_approval() -> None:
    quote = _quote(service="permanent", total=5200.01)

    with pytest.raises(ValidationError, match="Choose 50% down"):
        QuoteService._apply_proposal_payment_choice(quote, None, retry=False)

    QuoteService._apply_proposal_payment_choice(quote, "fifty_percent_down", retry=False)
    assert quote.proposal_payment_amount == 2600.01

    quote.status = "approved"
    QuoteService._apply_proposal_payment_choice(quote, "fifty_percent_down", retry=True)
    with pytest.raises(ConflictError, match="cannot be changed"):
        QuoteService._apply_proposal_payment_choice(quote, "pay_in_full", retry=True)


@pytest.mark.parametrize("choice", ["financing", "cash_check", "unknown"])
def test_public_approval_schema_rejects_non_customer_payment_choices(choice: str) -> None:
    with pytest.raises(PydanticValidationError):
        PublicProposalApprove.model_validate({"payment_option": choice})


def test_payment_choices_are_disabled_for_unapproved_workspaces() -> None:
    quote = _quote(service="permanent")
    quote.workspace.settings = {}

    assert QuoteService._public_payment_options(quote, quote.total) is None
    with pytest.raises(ValidationError, match="only for exact Permanent"):
        QuoteService._apply_proposal_payment_choice(quote, "pay_in_full", retry=False)


def test_non_permanent_proposal_cannot_submit_a_card_choice() -> None:
    quote = _quote(service="landscape")

    assert QuoteService._public_payment_options(quote, quote.total) is None
    QuoteService._apply_proposal_payment_choice(quote, None, retry=False)
    with pytest.raises(ValidationError, match="only for exact Permanent"):
        QuoteService._apply_proposal_payment_choice(quote, "pay_in_full", retry=False)
