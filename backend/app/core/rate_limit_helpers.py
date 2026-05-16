"""Helpers for emitting RFC 6585-compliant ``429 Too Many Requests`` responses.

All rate-limit sites in the public API must include a ``Retry-After`` header so
clients can back off intelligently instead of hammering the endpoint blind.
Centralizing the construction here keeps the contract consistent — every 429 we
emit is guaranteed to carry the header with a positive integer value.

See: https://datatracker.ietf.org/doc/html/rfc6585#section-4
"""

from fastapi import HTTPException, status

_DEFAULT_DETAIL = "Rate limit exceeded. Please try again later."


def raise_rate_limited(
    retry_after_seconds: int,
    *,
    detail: str = _DEFAULT_DETAIL,
) -> "HTTPException":
    """Raise an HTTP 429 with a ``Retry-After`` header (seconds).

    Args:
        retry_after_seconds: Seconds the client should wait before retrying.
            Values < 1 are clamped to 1 so we never emit ``Retry-After: 0``
            (which most clients interpret as "retry immediately" — useless for
            an exhausted-quota response).
        detail: Human-readable detail surfaced as the JSON error body.

    Raises:
        HTTPException: Always — status 429 with the ``Retry-After`` header set.

    Notes:
        This function is declared as returning ``HTTPException`` so callers can
        write ``raise raise_rate_limited(...)`` without confusing mypy, but the
        body raises unconditionally — control never returns to the caller.
    """
    # Clamp to ≥1: Retry-After: 0 is interpreted by most clients as
    # "retry immediately" which defeats the purpose of a rate-limit response.
    retry_after = max(1, int(retry_after_seconds))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )
