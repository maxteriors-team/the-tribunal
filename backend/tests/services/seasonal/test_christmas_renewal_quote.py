"""What carries into a renewal draft, and what must never carry.

Pure copy rules, no DB. The dangerous half is the second one: a renewal is a new
offer, so anything recording the *outcome* of last season — money taken,
approval, the customer's share link, the job it became — would be a lie on a
fresh draft, and in the payment cases a customer-visible one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from app.models.quote import Quote, QuoteLineItem
from app.services.seasonal.christmas_renewal import ChristmasSeason
from app.services.seasonal.christmas_renewal_quote import (
    RENEWABLE_STATUSES,
    _is_christmas_quote,
    _service_unknown,
    build_renewal_quote,
)

SEASON = ChristmasSeason(year=2026, started_at=datetime(2026, 1, 8, tzinfo=UTC))
WORKSPACE_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def sold_quote(**overrides) -> Quote:
    """Last season's approved job, with every outcome field populated."""
    fields = {
        "title": "Holiday lighting",
        "primary_service": "christmas_lights",
        **overrides,
    }
    quote = Quote(
        workspace_id=WORKSPACE_ID,
        contact_id=42,
        service_location_id=uuid.uuid4(),
        assigned_user_id=7,
        lighting_project_id=PROJECT_ID,
        number="Q-00007",
        status="approved",
        currency="USD",
        notes="Ladder access via side gate.",
        terms="Net 15",
        tax_amount=0,
        discount_amount=0,
        proposal_document={"selected_tier": "better"},
        selected_permanent_kits=[],
        # Outcome of the settled sale — none of this may reach a new draft.
        issue_date=date(2025, 10, 1),
        sent_at=datetime(2025, 10, 2, tzinfo=UTC),
        approved_at=datetime(2025, 10, 3, tzinfo=UTC),
        declined_at=None,
        public_token="last-years-customer-link",
        converted_job_id=uuid.uuid4(),
        converted_invoice_id=uuid.uuid4(),
        deposit_checkout_session_id="cs_live_deposit",
        deposit_payment_intent_id="pi_live_deposit",
        proposal_payment_choice="deposit",
        proposal_payment_amount=500,
        proposal_payment_checkout_session_id="cs_live_proposal",
        proposal_payment_intent_id="pi_live_proposal",
        proposal_payment_paid_at=datetime(2025, 10, 4, tzinfo=UTC),
        view_count=9,
        first_viewed_at=datetime(2025, 10, 2, tzinfo=UTC),
        last_viewed_at=datetime(2025, 10, 5, tzinfo=UTC),
        revision_number=2,
        **fields,
    )
    quote.line_items = [
        QuoteLineItem(
            name="Roofline — 155 ft",
            description="C9 warm white, 12 in spacing",
            service_category="christmas_lights",
            quantity=155,
            unit_price=6.5,
            discount=0,
            total=1007.5,
        ),
        QuoteLineItem(
            name="Front spruce — 379 ft · 16 strands",
            description=None,
            service_category="christmas_lights",
            quantity=16,
            unit_price=39.99,
            discount=0,
            total=639.84,
        ),
    ]
    return quote


def renewal(**overrides) -> Quote:
    return build_renewal_quote(
        sold_quote(**overrides), number="Q-00031", season=SEASON, created_by_id=3
    )


class TestCarriesTheScope:
    def test_keeps_the_customer_and_the_crew_notes(self):
        source = sold_quote()
        copy = build_renewal_quote(source, number="Q-1", season=SEASON, created_by_id=3)
        assert copy.contact_id == source.contact_id
        # The address is the job: a renewal quoted to a different house is wrong.
        assert copy.service_location_id == source.service_location_id
        assert copy.assigned_user_id == source.assigned_user_id
        # "Ladder access via side gate" is exactly what a returning crew needs.
        assert copy.notes == source.notes
        assert copy.terms == source.terms

    def test_reuses_the_same_design_rather_than_copying_it(self):
        # The photo, traced roofline and measured trees belong to the house. One
        # project with many quotes is the existing model; duplicating it would
        # fork the measurements and let the two drift.
        assert renewal().lighting_project_id == PROJECT_ID

    def test_carries_every_line_at_last_years_price(self):
        copy = renewal()
        assert [line.name for line in copy.line_items] == [
            "Roofline — 155 ft",
            "Front spruce — 379 ft · 16 strands",
        ]
        assert [float(line.total) for line in copy.line_items] == [1007.5, 639.84]
        # Prices are the honest starting point: the customer already agreed to
        # them. Repricing silently would change what a renewal costs.
        assert float(copy.line_items[1].unit_price) == 39.99
        assert copy.line_items[0].service_category == "christmas_lights"

    def test_does_not_share_the_design_json_with_last_years_quote(self):
        source = sold_quote()
        copy = build_renewal_quote(source, number="Q-1", season=SEASON, created_by_id=None)
        # Same content, different object: editing this year's proposal must not
        # rewrite the settled record of what was sold last year.
        assert copy.proposal_document == source.proposal_document
        assert copy.proposal_document is not source.proposal_document
        copy.proposal_document["selected_tier"] = "best"
        assert source.proposal_document["selected_tier"] == "better"

    def test_copies_lines_rather_than_moving_them(self):
        source = sold_quote()
        copy = build_renewal_quote(source, number="Q-1", season=SEASON, created_by_id=None)
        # The settled quote must still have its own lines afterwards.
        assert len(source.line_items) == 2
        assert len(copy.line_items) == 2
        assert copy.line_items[0] is not source.line_items[0]

    def test_names_the_draft_for_the_season_it_sells(self):
        assert renewal().title == "Holiday lighting — 2026 renewal"

    def test_keeps_a_very_long_title_within_the_column(self):
        copy = renewal(title="x" * 400)
        assert len(copy.title) <= 200
        assert copy.title.endswith("— 2026 renewal")


class TestLeavesTheOutcomeBehind:
    def test_starts_as_an_unsent_draft_dated_today(self):
        copy = renewal()
        assert copy.status == "draft"
        assert copy.number == "Q-00031"
        assert copy.issue_date == date.today()
        assert copy.sent_at is None

    def test_never_looks_already_paid(self):
        # The worst failure mode: a new draft carrying last year's payment
        # evidence would show a customer as having already paid this season.
        copy = renewal()
        assert copy.proposal_payment_choice is None
        assert copy.proposal_payment_amount is None
        assert copy.proposal_payment_paid_at is None
        assert copy.proposal_payment_checkout_session_id is None
        assert copy.proposal_payment_intent_id is None
        assert copy.deposit_checkout_session_id is None
        assert copy.deposit_payment_intent_id is None

    def test_never_looks_already_accepted(self):
        copy = renewal()
        assert copy.approved_at is None
        assert copy.declined_at is None
        assert copy.decline_reason is None

    def test_does_not_inherit_last_years_customer_link(self):
        # Reusing the token would put a new price behind a link the customer
        # already has, and let last year's recipient see this year's quote.
        assert renewal().public_token is None

    def test_is_not_already_a_job_or_an_invoice(self):
        copy = renewal()
        assert copy.converted_job_id is None
        assert copy.converted_invoice_id is None

    def test_starts_its_own_view_history(self):
        copy = renewal()
        assert copy.view_count in (0, None)
        assert copy.first_viewed_at is None
        assert copy.last_viewed_at is None

    def test_is_a_new_quote_not_a_revision_of_the_old_one(self):
        # A revision replaces an offer; a renewal is next year's separate sale,
        # and chaining them would corrupt last season's revision history.
        copy = renewal()
        assert copy.revision_of_quote_id is None
        assert copy.revision_root_quote_id is None
        assert copy.revision_number in (1, None)


class TestOnlyRenewsRealChristmasWork:
    def test_recognises_holiday_lighting_by_its_service_category(self):
        assert _is_christmas_quote(sold_quote()) is True
        assert _is_christmas_quote(sold_quote(primary_service="christmas")) is True
        assert _is_christmas_quote(sold_quote(primary_service="gutter_cleaning")) is False
        assert _is_christmas_quote(sold_quote(primary_service=None)) is False

    def test_only_sold_work_is_worth_rebuilding(self):
        # An abandoned draft or a declined quote is not "what we did for them".
        assert "approved" in RENEWABLE_STATUSES
        assert "draft" not in RENEWABLE_STATUSES
        assert "declined" not in RENEWABLE_STATUSES
        assert "expired" not in RENEWABLE_STATUSES

    def test_a_named_other_trade_is_never_a_fallback_candidate(self):
        # The seasonal-plan fallback exists for quotes whose category was never
        # snapshotted. A gutter-cleaning quote is *known* not to be lighting, so
        # renewing it would put gutter lines on a quote titled "2026 renewal".
        assert _service_unknown(sold_quote(primary_service="gutter_cleaning")) is False
        assert _service_unknown(sold_quote(primary_service="christmas_lights")) is False
        # Genuinely unknown: eligible for the fallback.
        assert _service_unknown(sold_quote(primary_service=None)) is True
        assert _service_unknown(sold_quote(primary_service="   ")) is True
