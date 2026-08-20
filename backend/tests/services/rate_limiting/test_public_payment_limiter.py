"""Public payment verification rate-limit tests."""

from unittest.mock import AsyncMock

import pytest

from app.services.rate_limiting import public_payment_limiter


@pytest.mark.asyncio
async def test_payment_verification_uses_bounded_per_ip_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enforce = AsyncMock()
    monkeypatch.setattr(public_payment_limiter, "enforce_embed_rate_limit", enforce)

    await public_payment_limiter.enforce_public_payment_verification_rate_limit("203.0.113.7")

    enforce.assert_awaited_once_with(
        scope="public_payment_verify:ip",
        identifier="203.0.113.7",
        limit=public_payment_limiter.PUBLIC_PAYMENT_VERIFY_PER_IP_LIMIT,
        window_seconds=public_payment_limiter.PUBLIC_PAYMENT_VERIFY_WINDOW_SECONDS,
        detail="Too many payment verification requests. Please try again later.",
    )
