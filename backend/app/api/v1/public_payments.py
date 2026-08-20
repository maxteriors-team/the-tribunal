"""Unauthenticated verification for the generic Stripe Checkout return page."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.api.deps import DB
from app.schemas.public_payment import PublicPaymentVerification
from app.services.payments.public_checkout_verification import (
    PaymentSessionNotFoundError,
    PaymentVerificationUnavailableError,
    verify_checkout_session,
)

public_router = APIRouter()
CheckoutSessionId = Annotated[
    str,
    Path(
        min_length=8,
        max_length=255,
        pattern=r"^cs_[A-Za-z0-9_]+$",
        description="Stripe Checkout Session identifier returned by Checkout",
    ),
]


@public_router.post(
    "/checkout-sessions/{session_id}/verify",
    response_model=PublicPaymentVerification,
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Unknown or invalid Checkout Session"},
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Stripe verification is temporarily unavailable"
        },
    },
)
async def verify_public_checkout_session(
    session_id: CheckoutSessionId,
    db: DB,
    response: Response,
) -> PublicPaymentVerification:
    """Return payment state only after local ownership and Stripe both agree."""
    response.headers["Cache-Control"] = "no-store"
    try:
        payment_status = await verify_checkout_session(db, session_id)
    except PaymentSessionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment session could not be verified.",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except PaymentVerificationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment verification is temporarily unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc
    return PublicPaymentVerification(status=payment_status)
