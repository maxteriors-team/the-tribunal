"""Redis-backed per-user rate limiting for authenticated auth endpoints.

The IP-based ``_check_auth_rate_limit`` in ``app/api/v1/auth.py`` is keyed on
client IP and is appropriate for the unauthenticated routes (login/register/
refresh). The authenticated routes ``/change-password`` and ``/ws-ticket``
already know the calling user, so we cap them per ``user_id`` instead: a
compromised session shouldn't be able to brute-force the current password or
mint an unbounded number of WS tickets, even from a single IP.

This module mirrors ``app.services.rate_limiting.embed_limiter`` so we have a
single Lua-backed INCR-with-TTL primitive in the codebase. It is fully
self-contained for easy mocking in tests.
"""

from datetime import UTC, datetime

import structlog

from app.core.rate_limit_helpers import raise_rate_limited
from app.db.redis import get_redis
from app.services.rate_limiting.rate_limiter import INCREMENT_WITH_LIMIT_SCRIPT

logger = structlog.get_logger()


_KEY_PREFIX = "rate_limit:auth"


def _build_key(scope: str, user_id: int) -> str:
    return f"{_KEY_PREFIX}:{scope}:{user_id}"


async def _check_and_increment(
    scope: str,
    user_id: int,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """Atomically check-and-increment a per-user counter.

    Returns ``(allowed, current_count)``. ``allowed`` is ``False`` when the
    limit has already been reached *before* this call; the counter is not
    incremented further in that case (the Lua script short-circuits).
    """
    redis_client = await get_redis()
    key = _build_key(scope, user_id)

    result = await redis_client.eval(  # type: ignore[misc]
        INCREMENT_WITH_LIMIT_SCRIPT, 1, key, limit, window_seconds
    )

    allowed = bool(int(result[0]))
    current = int(result[1])
    return allowed, current


async def _retry_after_seconds(scope: str, user_id: int, window_seconds: int) -> int:
    """Look up the live TTL on a limiter key for a precise ``Retry-After``.

    Falls back to ``window_seconds`` when the TTL can't be read (missing key,
    no expire, or transient Redis error). A conservative upper bound is
    better than no header.
    """
    try:
        redis_client = await get_redis()
        ttl = await redis_client.ttl(_build_key(scope, user_id))
    except Exception as exc:  # noqa: BLE001 - fail-safe to window default
        logger.warning(
            "auth_rate_limit_ttl_lookup_failed",
            scope=scope,
            user_id=user_id,
            error=str(exc),
        )
        return window_seconds
    if ttl is None or ttl < 0:
        return window_seconds
    return max(1, int(ttl))


async def _enforce(
    scope: str,
    user_id: int,
    limit: int,
    window_seconds: int,
    *,
    detail: str,
) -> None:
    """Enforce a per-user rate limit, raising 429 if exceeded.

    Fail-open on Redis errors: if Redis is unreachable we log and allow the
    request through rather than locking authenticated users out of password
    rotation or WS handshakes during an outage.
    """
    try:
        allowed, current = await _check_and_increment(
            scope=scope,
            user_id=user_id,
            limit=limit,
            window_seconds=window_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open intentionally
        logger.warning(
            "auth_rate_limit_redis_error",
            scope=scope,
            user_id=user_id,
            error=str(exc),
        )
        return

    if not allowed:
        retry_after = await _retry_after_seconds(scope, user_id, window_seconds)
        logger.info(
            "auth_rate_limit_exceeded",
            scope=scope,
            user_id=user_id,
            limit=limit,
            current=current,
            retry_after_seconds=retry_after,
            timestamp=datetime.now(UTC).isoformat(),
        )
        raise_rate_limited(retry_after, detail=detail)


# Default limits ---------------------------------------------------------------
# Password change is expensive (Argon2id rehash + revoking all refresh tokens)
# and brute-forcing the *current* password from an authenticated session is a
# real risk after a session-token leak. Five per hour is plenty for a human.
CHANGE_PASSWORD_LIMIT = 5
CHANGE_PASSWORD_WINDOW_SECONDS = 3600

# WS tickets are cheap to mint but each one opens a WebSocket budget. 30/min
# covers normal reconnect storms (network blips, tab refreshes) without giving
# a hijacked session room to flood the WS layer.
WS_TICKET_LIMIT = 30
WS_TICKET_WINDOW_SECONDS = 60


async def enforce_change_password_rate_limit(user_id: int) -> None:
    """Cap ``POST /auth/change-password`` to 5 attempts per user per hour."""
    await _enforce(
        scope="change_password",
        user_id=user_id,
        limit=CHANGE_PASSWORD_LIMIT,
        window_seconds=CHANGE_PASSWORD_WINDOW_SECONDS,
        detail="Too many password change attempts. Please try again later.",
    )


async def enforce_ws_ticket_rate_limit(user_id: int) -> None:
    """Cap ``POST /auth/ws-ticket`` to 30 tickets per user per minute."""
    await _enforce(
        scope="ws_ticket",
        user_id=user_id,
        limit=WS_TICKET_LIMIT,
        window_seconds=WS_TICKET_WINDOW_SECONDS,
        detail="Too many WebSocket ticket requests. Please slow down.",
    )
