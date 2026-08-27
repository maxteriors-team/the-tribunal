"""Layered spend caps for AI estimate renders."""

import uuid
from datetime import UTC, datetime
from typing import Protocol, cast

import structlog
from redis.exceptions import RedisError

from app.core.rate_limit_helpers import raise_rate_limited
from app.db.redis import get_redis
from app.services.exceptions import ServiceUnavailableError
from app.services.rate_limiting.rate_limiter import INCREMENT_WITH_LIMIT_SCRIPT

logger = structlog.get_logger()

ESTIMATE_RENDER_USER_LIMIT = 12
ESTIMATE_RENDER_WORKSPACE_LIMIT = 12
# simplification: this also caps BYOK workspaces at 120/hour; split counters by
# credential source when legitimate platform volume approaches that ceiling.
ESTIMATE_RENDER_PLATFORM_LIMIT = 120
ESTIMATE_RENDER_WINDOW_SECONDS = 3600
_KEY_PREFIX = "rate_limit:estimate_render"


class _RateLimitRedis(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]: ...

    async def ttl(self, key: str) -> int: ...


def _scopes(workspace_id: uuid.UUID, user_id: int) -> tuple[tuple[str, str, int], ...]:
    # A workspace-only cap is bypassable because authenticated users may create
    # more workspaces, all of which can fall back to the shared provider credential.
    return (
        ("user", f"{_KEY_PREFIX}:user:{user_id}", ESTIMATE_RENDER_USER_LIMIT),
        ("workspace", f"{_KEY_PREFIX}:{workspace_id}", ESTIMATE_RENDER_WORKSPACE_LIMIT),
        ("platform", f"{_KEY_PREFIX}:platform", ESTIMATE_RENDER_PLATFORM_LIMIT),
    )


async def enforce_estimate_render_rate_limit(workspace_id: uuid.UUID, user_id: int) -> None:
    """Bound billable image generation per user, workspace, and platform each hour."""
    blocked: tuple[str, str, int, int] | None = None
    try:
        redis_client = cast(_RateLimitRedis, await get_redis())
        for scope, key, limit in _scopes(workspace_id, user_id):
            result = await redis_client.eval(
                INCREMENT_WITH_LIMIT_SCRIPT,
                1,
                key,
                limit,
                ESTIMATE_RENDER_WINDOW_SECONDS,
            )
            allowed = bool(int(result[0]))
            current = int(result[1])
            if not allowed:
                blocked = (scope, key, limit, current)
                break
    except (RedisError, ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "estimate_render_rate_limit_unavailable",
            workspace_id=str(workspace_id),
            error=str(exc),
        )
        raise ServiceUnavailableError(
            "AI rendering is temporarily unavailable. Please try again shortly."
        ) from exc

    if blocked is None:
        return

    scope, key, limit, current = blocked
    retry_after = ESTIMATE_RENDER_WINDOW_SECONDS
    try:
        ttl = await redis_client.ttl(key)
        if ttl is not None and ttl >= 0:
            retry_after = max(1, int(ttl))
    except (RedisError, ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "estimate_render_rate_limit_ttl_unavailable",
            workspace_id=str(workspace_id),
            scope=scope,
            error=str(exc),
        )

    logger.info(
        "estimate_render_rate_limit_exceeded",
        workspace_id=str(workspace_id),
        scope=scope,
        limit=limit,
        current=current,
        retry_after_seconds=retry_after,
        timestamp=datetime.now(UTC).isoformat(),
    )
    raise_rate_limited(
        retry_after,
        detail="The hourly AI render limit has been reached. Please try again later.",
    )
