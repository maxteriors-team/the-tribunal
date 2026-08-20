"""Public payment-return verification schemas."""

from typing import Literal

from pydantic import BaseModel


class PublicPaymentVerification(BaseModel):
    """Non-sensitive Stripe Checkout state for the generic return page."""

    status: Literal["paid", "pending", "expired", "failed"]
