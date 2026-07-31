"""Slot accounting, offer money maths, and the offer schema's two hard rules.

Pure — no database. The two rules that make a pre-booking campaign a booking
rather than a coupon are enforced by :class:`PreBookingConfigBase` before
anything is written, so they are asserted here at the boundary they live on:

- a **deposit** is mandatory and positive;
- a **slot cap** is mandatory and positive.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models.prebooking import PreBookingAmountType
from app.schemas.prebooking import (
    PreBookingConfigCreate,
    PreBookingConfigResponse,
    PreBookingReserveRequest,
)
from app.services.payments.quote_deposit_service import resolve_deposit
from app.services.prebooking.slots import (
    assemble_slot_usage,
    preview_deposit_amount,
    resolve_deposit_terms,
    resolve_incentive_amount,
)

VALID_OFFER = {
    "service_season_start_month": 3,
    "service_season_end_month": 5,
    "service_season_year": 2027,
    "service_description": "Spring house wash + gutter clean",
    "incentive_type": "percentage",
    "incentive_value": 15,
    "deposit_type": "percentage",
    "deposit_value": 25,
    "slot_cap": 20,
}


class TestSlotUsage:
    def test_remaining_counts_holds_and_confirmations(self) -> None:
        usage = assemble_slot_usage(cap=20, held=3, confirmed=5)
        assert usage.occupied == 8
        assert usage.remaining == 12
        assert usage.is_full is False
        assert usage.oversold == 0

    def test_full_when_the_cap_is_met(self) -> None:
        usage = assemble_slot_usage(cap=2, held=1, confirmed=1)
        assert usage.remaining == 0
        assert usage.is_full is True

    def test_lowering_the_cap_below_what_is_sold_never_reports_negative_slots(self) -> None:
        """An operator trimming the cap mid-season must not see -3 slots left."""
        usage = assemble_slot_usage(cap=5, held=0, confirmed=8)
        assert usage.remaining == 0
        assert usage.is_full is True
        assert usage.oversold == 3


class TestIncentiveMaths:
    def test_percentage_off_the_subtotal(self) -> None:
        amount = resolve_incentive_amount(
            incentive_type=PreBookingAmountType.PERCENTAGE,
            incentive_value=15,
            subtotal=450.0,
        )
        assert amount == 67.5

    def test_fixed_amount(self) -> None:
        amount = resolve_incentive_amount(
            incentive_type=PreBookingAmountType.FIXED,
            incentive_value=50,
            subtotal=450.0,
        )
        assert amount == 50.0

    def test_fixed_amount_is_clamped_to_the_job(self) -> None:
        """A fat-fingered $5,000 off a $400 wash discounts to zero, never below."""
        amount = resolve_incentive_amount(
            incentive_type=PreBookingAmountType.FIXED,
            incentive_value=5000,
            subtotal=400.0,
        )
        assert amount == 400.0

    @pytest.mark.parametrize("subtotal", [0.0, -10.0])
    def test_no_discount_on_a_worthless_job(self, subtotal: float) -> None:
        assert (
            resolve_incentive_amount(
                incentive_type=PreBookingAmountType.PERCENTAGE,
                incentive_value=15,
                subtotal=subtotal,
            )
            == 0.0
        )


class TestDepositTerms:
    def test_percentage_maps_to_the_quote_percentage_field_only(self) -> None:
        percentage, fixed = resolve_deposit_terms(
            deposit_type=PreBookingAmountType.PERCENTAGE, deposit_value=25
        )
        assert percentage == 25.0
        assert fixed is None

    def test_fixed_maps_to_the_quote_fixed_field_only(self) -> None:
        """The quote schema refuses both at once, so exactly one may be set."""
        percentage, fixed = resolve_deposit_terms(
            deposit_type=PreBookingAmountType.FIXED, deposit_value=99
        )
        assert percentage is None
        assert fixed == 99.0

    def test_preview_agrees_with_the_code_that_charges_the_card(self) -> None:
        preview = preview_deposit_amount(
            deposit_type=PreBookingAmountType.PERCENTAGE, deposit_value=25, total=382.5
        )
        assert preview == resolve_deposit("percentage", 25, 382.5)
        assert preview == 95.62


class TestOfferSchema:
    def test_a_valid_offer_round_trips(self) -> None:
        offer = PreBookingConfigCreate(**VALID_OFFER)
        assert offer.slot_cap == 20
        assert offer.hold_hours == 72

    def test_deposit_is_required(self) -> None:
        """No deposit means no booking — it is a discount with extra steps."""
        payload = {k: v for k, v in VALID_OFFER.items() if k != "deposit_value"}
        with pytest.raises(ValidationError, match="deposit_value"):
            PreBookingConfigCreate(**payload)

    @pytest.mark.parametrize("bad", [0, -5])
    def test_deposit_must_be_positive(self, bad: float) -> None:
        with pytest.raises(ValidationError, match="deposit_value"):
            PreBookingConfigCreate(**{**VALID_OFFER, "deposit_value": bad})

    def test_slot_cap_is_required(self) -> None:
        payload = {k: v for k, v in VALID_OFFER.items() if k != "slot_cap"}
        with pytest.raises(ValidationError, match="slot_cap"):
            PreBookingConfigCreate(**payload)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_slot_cap_must_be_positive(self, bad: int) -> None:
        with pytest.raises(ValidationError, match="slot_cap"):
            PreBookingConfigCreate(**{**VALID_OFFER, "slot_cap": bad})

    def test_a_percentage_deposit_over_100_is_a_typo_not_an_offer(self) -> None:
        with pytest.raises(ValidationError, match="percentage deposit cannot exceed"):
            PreBookingConfigCreate(**{**VALID_OFFER, "deposit_value": 120})

    def test_a_percentage_incentive_over_100_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="percentage incentive cannot exceed"):
            PreBookingConfigCreate(**{**VALID_OFFER, "incentive_value": 150})

    def test_a_fixed_deposit_may_exceed_100(self) -> None:
        offer = PreBookingConfigCreate(
            **{**VALID_OFFER, "deposit_type": "fixed", "deposit_value": 250}
        )
        assert offer.deposit_value == 250

    def test_unknown_fields_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            PreBookingConfigCreate(**{**VALID_OFFER, "slot_capp": 5})


class TestOfferResponseComputedFields:
    def _response(self, **overrides: object) -> PreBookingConfigResponse:
        now = datetime.now(UTC)
        payload = {
            "id": uuid.uuid4(),
            "workspace_id": uuid.uuid4(),
            "campaign_id": uuid.uuid4(),
            **VALID_OFFER,
            "hold_hours": 72,
            "slots_held": 2,
            "slots_confirmed": 3,
            "scheduled_start": datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
        return PreBookingConfigResponse(**payload)  # type: ignore[arg-type]

    def test_season_dates_and_label(self) -> None:
        response = self._response()
        assert response.season_start_date.isoformat() == "2027-03-01"
        assert response.season_end_date.isoformat() == "2027-05-31"
        assert response.season_label == "March–May 2027"

    def test_slot_counts(self) -> None:
        response = self._response()
        assert response.slots_remaining == 15
        assert response.is_full is False

    def test_lead_time_is_measured_from_the_scheduled_launch(self) -> None:
        response = self._response()
        assert response.lead_time_days == 181
        assert response.lead_time_status == "ample"

    def test_a_launch_inside_the_season_is_graded_late(self) -> None:
        response = self._response(scheduled_start=datetime(2027, 3, 15, 9, 0, tzinfo=UTC))
        assert response.lead_time_days < 0
        assert response.lead_time_status == "late"


class TestReserveRequest:
    def test_a_price_is_required_from_somewhere(self) -> None:
        with pytest.raises(ValidationError, match="source_quote_id or base_amount"):
            PreBookingReserveRequest(contact_id=1)

    def test_a_flat_price_is_enough(self) -> None:
        assert PreBookingReserveRequest(contact_id=1, base_amount=450).base_amount == 450

    def test_last_years_unsold_quote_is_enough(self) -> None:
        request = PreBookingReserveRequest(contact_id=1, source_quote_id=uuid.uuid4())
        assert request.base_amount is None
