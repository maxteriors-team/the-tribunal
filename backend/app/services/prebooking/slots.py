"""Slot accounting and offer maths for pre-booking (pure).

The crew calendar is the thing that can actually be oversold, so the rules that
decide whether one more customer may be let in live here as plain functions over
plain numbers — no session, no ORM — and the service layer only supplies the
counts. Same split as
:func:`app.services.reporting.capacity_service.assemble_backlog`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.prebooking import PreBookingAmountType
from app.services.payments.quote_deposit_service import resolve_deposit


@dataclass(frozen=True, slots=True)
class SlotUsage:
    """How much of a season's capacity is spoken for."""

    cap: int
    held: int
    confirmed: int

    @property
    def occupied(self) -> int:
        """Slots that are not available to a new customer right now."""
        return self.held + self.confirmed

    @property
    def remaining(self) -> int:
        """Slots still sellable. Never negative, even if a cap was lowered."""
        return max(0, self.cap - self.occupied)

    @property
    def is_full(self) -> bool:
        """True when no further slot may be *held*."""
        return self.remaining <= 0

    @property
    def oversold(self) -> int:
        """Slots beyond the cap.

        Normally zero. It can go positive two ways, both deliberate: an operator
        lowering ``slot_cap`` after selling, and a deposit landing on a hold that
        had already lapsed — a paid booking is always honoured (see
        :func:`app.services.prebooking.reservation_service.confirm_reservation_for_quote`),
        because refusing money already taken is worse than one tight week.
        """
        return max(0, self.occupied - self.cap)


def assemble_slot_usage(*, cap: int, held: int, confirmed: int) -> SlotUsage:
    """Build a :class:`SlotUsage` from raw counts."""
    return SlotUsage(cap=cap, held=held, confirmed=confirmed)


def resolve_incentive_amount(
    *,
    incentive_type: PreBookingAmountType,
    incentive_value: float,
    subtotal: float,
) -> float:
    """Discount (major units) the early commitment buys, clamped to the subtotal.

    A percentage is taken off the subtotal; a fixed amount is capped at it, so a
    fat-fingered "$5000 off" on a $400 house wash discounts the job to zero
    rather than owing the customer money.
    """
    if subtotal <= 0 or incentive_value <= 0:
        return 0.0
    if incentive_type is PreBookingAmountType.FIXED:
        return round(min(float(incentive_value), subtotal), 2)
    return round(subtotal * min(float(incentive_value), 100.0) / 100, 2)


def resolve_deposit_terms(
    *,
    deposit_type: PreBookingAmountType,
    deposit_value: float,
) -> tuple[float | None, float | None]:
    """Map the offer's deposit onto a quote's ``(percentage, fixed)`` pair.

    Exactly one of the two is non-``None``, matching the quote schema's
    "set at most one" rule, so the deposit rides the existing Stripe checkout
    with no second payment path and no second money rule.
    """
    if deposit_type is PreBookingAmountType.FIXED:
        return None, round(float(deposit_value), 2)
    return round(float(deposit_value), 2), None


def preview_deposit_amount(
    *,
    deposit_type: PreBookingAmountType,
    deposit_value: float,
    total: float,
) -> float:
    """Deposit due (major units) on ``total`` under this offer's terms.

    Delegates to :func:`app.services.payments.quote_deposit_service.resolve_deposit`
    so the number quoted in the wizard is produced by the same code that charges
    the card.
    """
    return resolve_deposit(deposit_type.value, float(deposit_value), total)
