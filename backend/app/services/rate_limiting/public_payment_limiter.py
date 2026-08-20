"""Rate limiting for unauthenticated Stripe Checkout verification."""

from app.services.rate_limiting.embed_limiter import enforce_embed_rate_limit

PUBLIC_PAYMENT_VERIFY_PER_IP_LIMIT = 30
PUBLIC_PAYMENT_VERIFY_WINDOW_SECONDS = 3600


async def enforce_public_payment_verification_rate_limit(client_ip: str) -> None:
    """Bound provider-backed verification requests from one public caller."""
    await enforce_embed_rate_limit(
        scope="public_payment_verify:ip",
        identifier=client_ip,
        limit=PUBLIC_PAYMENT_VERIFY_PER_IP_LIMIT,
        window_seconds=PUBLIC_PAYMENT_VERIFY_WINDOW_SECONDS,
        detail="Too many payment verification requests. Please try again later.",
    )
