"""Redis-backed rate limiting for public embed API endpoints.

The embed endpoints in ``app/api/v1/embed.py`` are unauthenticated and call
out to expensive third-party services (OpenAI Realtime, OpenAI Chat, Telnyx).
This module provides per-scope rolling-window rate limits keyed by
``(scope, identifier)`` so we can apply distinct caps per IP and per agent
public_id without coupling the routes to Redis details.

The implementation reuses the same atomic INCR-with-limit Lua pattern as
``app.services.rate_limiting.rate_limiter`` and is fully self-contained so it
can be mocked easily in tests.
"""

from datetime import UTC, datetime

import structlog

from app.core.rate_limit_helpers import raise_rate_limited
from app.db.redis import get_redis
from app.services.rate_limiting.rate_limiter import INCREMENT_WITH_LIMIT_SCRIPT

logger = structlog.get_logger()


_KEY_PREFIX = "rate_limit:embed"


def _build_key(scope: str, identifier: str) -> str:
    return f"{_KEY_PREFIX}:{scope}:{identifier}"


async def _check_and_increment(
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
) -> tuple[bool, int]:
    """Atomically check-and-increment a counter for (scope, identifier).

    Args:
        scope: Logical bucket name (e.g. ``"token:ip"``, ``"chat:public_id"``).
        identifier: The thing being limited (an IP address, a public_id...).
        limit: Maximum allowed requests in the window.
        window_seconds: Window size used as the Redis key TTL.

    Returns:
        Tuple of ``(allowed, current_count)``. ``allowed`` is ``False`` when
        the limit has already been reached *before* this call; the counter is
        not incremented further in that case.
    """
    redis_client = await get_redis()
    key = _build_key(scope, identifier)

    result = await redis_client.eval(  # type: ignore[misc]
        INCREMENT_WITH_LIMIT_SCRIPT, 1, key, limit, window_seconds
    )

    allowed = bool(int(result[0]))
    current = int(result[1])
    return allowed, current


async def _retry_after_seconds(scope: str, identifier: str, window_seconds: int) -> int:
    """Read the live TTL on a limiter key to derive a precise ``Retry-After``.

    Falls back to ``window_seconds`` if Redis can't tell us (key missing,
    TTL not set, or a transient error) — a conservative upper bound is
    always better than no header at all.
    """
    try:
        redis_client = await get_redis()
        ttl = await redis_client.ttl(_build_key(scope, identifier))
    except Exception as exc:  # noqa: BLE001 - fail-safe to window default
        logger.warning(
            "embed_rate_limit_ttl_lookup_failed",
            scope=scope,
            identifier=identifier,
            error=str(exc),
        )
        return window_seconds
    # Redis returns -2 (missing key) or -1 (no expire). Both mean we can't
    # derive a real remaining window; fall back to the configured window.
    if ttl is None or ttl < 0:
        return window_seconds
    return max(1, int(ttl))


async def enforce_embed_rate_limit(
    scope: str,
    identifier: str,
    limit: int,
    window_seconds: int,
    *,
    detail: str = "Rate limit exceeded. Please try again later.",
) -> None:
    """Enforce a rate limit, raising 429 if exceeded.

    Fail-open on Redis errors: if Redis is unreachable we log and allow the
    request through rather than locking out every embed caller during an
    outage. The auth-path counters in PostgreSQL remain as a defense in depth.
    """
    try:
        allowed, current = await _check_and_increment(
            scope=scope,
            identifier=identifier,
            limit=limit,
            window_seconds=window_seconds,
        )
    except Exception as exc:  # noqa: BLE001 - fail-open intentionally
        logger.warning(
            "embed_rate_limit_redis_error",
            scope=scope,
            identifier=identifier,
            error=str(exc),
        )
        return

    if not allowed:
        retry_after = await _retry_after_seconds(scope, identifier, window_seconds)
        logger.info(
            "embed_rate_limit_exceeded",
            scope=scope,
            identifier=identifier,
            limit=limit,
            current=current,
            retry_after_seconds=retry_after,
            timestamp=datetime.now(UTC).isoformat(),
        )
        raise_rate_limited(retry_after, detail=detail)


# Default limits ---------------------------------------------------------------
# Token endpoint mints expensive OpenAI Realtime client secrets; keep tight.
TOKEN_PER_IP_LIMIT = 10
TOKEN_PER_PUBLIC_ID_LIMIT = 30

# Chat / tool-call / transcript endpoints are cheaper but still bill OpenAI.
CHAT_PER_PUBLIC_ID_LIMIT = 60
CHAT_PER_IP_LIMIT = 60

ONE_HOUR_SECONDS = 3600


async def enforce_token_rate_limits(client_ip: str, public_id: str) -> None:
    """Apply per-IP and per-public_id limits for the /token endpoint."""
    await enforce_embed_rate_limit(
        scope="token:ip",
        identifier=client_ip,
        limit=TOKEN_PER_IP_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
    )
    await enforce_embed_rate_limit(
        scope="token:public_id",
        identifier=public_id,
        limit=TOKEN_PER_PUBLIC_ID_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
    )


async def enforce_chat_rate_limits(client_ip: str, public_id: str) -> None:
    """Apply per-IP and per-public_id limits for chat-style endpoints.

    Used by ``/chat``, ``/tool-call``, and ``/transcript`` so the three share
    a single budget per agent and per caller.
    """
    await enforce_embed_rate_limit(
        scope="chat:public_id",
        identifier=public_id,
        limit=CHAT_PER_PUBLIC_ID_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
    )
    await enforce_embed_rate_limit(
        scope="chat:ip",
        identifier=client_ip,
        limit=CHAT_PER_IP_LIMIT,
        window_seconds=ONE_HOUR_SECONDS,
    )
