"""Read-only verification for the generic Stripe Checkout return page."""

from dataclasses import dataclass
from typing import Literal

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call_payment import CallPayment
from app.models.invoice import Invoice
from app.services.payments import call_payment_service

PublicPaymentStatus = Literal["paid", "pending", "expired", "failed"]


class PaymentSessionNotFoundError(Exception):
    """The supplied Checkout Session is not a known local payment."""


class PaymentVerificationUnavailableError(Exception):
    """Stripe could not be reached to verify a known payment."""


@dataclass(frozen=True, slots=True)
class _LocalCheckoutReference:
    expected_metadata: dict[str, str]
    currency: str
    amount_total: int | None
    payment_intent_id: str | None


async def _find_local_reference(
    db: AsyncSession,
    session_id: str,
) -> _LocalCheckoutReference | None:
    call_result = await db.execute(
        select(CallPayment).where(CallPayment.stripe_checkout_session_id == session_id).limit(1)
    )
    call_payment = call_result.scalar_one_or_none()
    if call_payment is not None:
        return _LocalCheckoutReference(
            expected_metadata={
                "kind": call_payment_service.PAYMENT_KIND,
                "call_payment_id": str(call_payment.id),
                "workspace_id": str(call_payment.workspace_id),
            },
            currency=call_payment.currency.lower(),
            amount_total=call_payment_service.to_minor_units(
                float(call_payment.amount), call_payment.currency
            ),
            payment_intent_id=call_payment.stripe_payment_intent_id,
        )

    invoice_result = await db.execute(
        select(Invoice).where(Invoice.stripe_checkout_session_id == session_id).limit(1)
    )
    invoice = invoice_result.scalar_one_or_none()
    if invoice is None:
        return None

    return _LocalCheckoutReference(
        expected_metadata={
            "invoice_id": str(invoice.id),
            "workspace_id": str(invoice.workspace_id),
        },
        currency=invoice.currency.lower(),
        # An invoice can be partially paid after its Checkout Session was created,
        # so its current balance is not a reliable snapshot of the original amount.
        amount_total=None,
        payment_intent_id=invoice.stripe_payment_intent_id,
    )


def _matches_local_reference(
    session: call_payment_service.CheckoutSessionDetails,
    reference: _LocalCheckoutReference,
) -> bool:
    if session.mode != "payment":
        return False
    if session.currency != reference.currency:
        return False
    if session.amount_total is None or session.amount_total <= 0:
        return False
    if reference.amount_total is not None and session.amount_total != reference.amount_total:
        return False
    if (
        reference.payment_intent_id is not None
        and session.payment_intent_id != reference.payment_intent_id
    ):
        return False
    return all(
        session.metadata.get(key) == value for key, value in reference.expected_metadata.items()
    )


async def verify_checkout_session(
    db: AsyncSession,
    session_id: str,
) -> PublicPaymentStatus:
    """Verify Stripe state without fulfilling or mutating the payment.

    The local lookup happens first so random identifiers cannot be used to proxy
    arbitrary Stripe API requests. Replays are safe because this function is
    read-only; fulfillment remains webhook-driven and idempotent.
    """
    reference = await _find_local_reference(db, session_id)
    if reference is None:
        raise PaymentSessionNotFoundError
    if not call_payment_service.is_payment_configured():
        raise PaymentVerificationUnavailableError

    try:
        session = await call_payment_service.retrieve_checkout_session_details(session_id)
    except stripe.InvalidRequestError as exc:
        raise PaymentSessionNotFoundError from exc
    except stripe.StripeError as exc:
        raise PaymentVerificationUnavailableError from exc

    if not _matches_local_reference(session, reference):
        raise PaymentSessionNotFoundError
    if session.payment_status == "paid" and session.payment_intent_id is not None:
        return "paid"
    if session.status == "expired":
        return "expired"
    if session.payment_status == "unpaid" and session.status in {"open", "complete"}:
        return "pending"
    return "failed"
