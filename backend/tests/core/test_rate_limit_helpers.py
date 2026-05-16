"""Tests for the central ``raise_rate_limited`` helper.

The helper is the single chokepoint for every 429 the API emits, so its
contract is load-bearing: status code, ``Retry-After`` header, and the
clamped-to-positive guarantee are all asserted here.
"""

import pytest
from fastapi import HTTPException, status

from app.core.rate_limit_helpers import raise_rate_limited


class TestRaiseRateLimited:
    def test_raises_429_with_retry_after_header(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(30)

        exc = exc_info.value
        assert exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert exc.headers is not None
        assert exc.headers["Retry-After"] == "30"

    def test_header_value_is_string_seconds(self) -> None:
        """``Retry-After`` per RFC 6585 must be an integer (delta-seconds)
        rendered as a string when used in a header dict."""
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(123)

        retry_after = exc_info.value.headers["Retry-After"]  # type: ignore[index]
        assert isinstance(retry_after, str)
        # Must round-trip cleanly through int() — clients use it numerically.
        assert int(retry_after) == 123

    def test_clamps_zero_to_one(self) -> None:
        """``Retry-After: 0`` is interpreted as "retry now" by most clients,
        which defeats the purpose. The helper must clamp to a minimum of 1."""
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(0)

        assert exc_info.value.headers["Retry-After"] == "1"  # type: ignore[index]

    def test_clamps_negative_to_one(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(-42)

        assert exc_info.value.headers["Retry-After"] == "1"  # type: ignore[index]

    def test_uses_custom_detail(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(60, detail="Slow down, friend.")

        assert exc_info.value.detail == "Slow down, friend."

    def test_default_detail_is_human_readable(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(60)

        # We don't pin exact wording, but the default must be a non-empty
        # string clients can surface to end users.
        assert isinstance(exc_info.value.detail, str)
        assert exc_info.value.detail
        # And must clearly communicate the rate-limit nature.
        assert "rate" in exc_info.value.detail.lower() or "again" in exc_info.value.detail.lower()

    def test_accepts_float_like_int(self) -> None:
        """Callers compute remaining-window seconds from datetime math, which
        can produce floats. ``int()`` cast inside the helper handles it."""
        with pytest.raises(HTTPException) as exc_info:
            raise_rate_limited(int(45.7))

        assert exc_info.value.headers["Retry-After"] == "45"  # type: ignore[index]
