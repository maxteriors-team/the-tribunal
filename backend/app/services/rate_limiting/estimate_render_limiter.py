"""Workspace spend cap for AI estimate renders."""

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

ESTIMATE_RENDER_LIMIT = 12
ESTIMATE_RENDER_WINDOW_SECONDS = 3600
_KEY_PREFIX = "rate_limit:estimate_render"


class _RateLimitRedis(Protocol):
    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]: ...

    async def ttl(self, key: str) -> int: ...


def _key(workspace_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}:{workspace_id}"


async def enforce_estimate_render_rate_limit(workspace_id: uuid.UUID) -> None:
    """Allow at most twelve billable image generations per workspace each hour."""
    try:
        redis_client = cast(_RateLimitRedis, await get_redis())
        result = await redis_client.eval(
            INCREMENT_WITH_LIMIT_SCRIPT,
            1,
            _key(workspace_id),
            ESTIMATE_RENDER_LIMIT,
            ESTIMATE_RENDER_WINDOW_SECONDS,
        )
        allowed = bool(int(result[0]))
        current = int(result[1])
    except (RedisError, ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "estimate_render_rate_limit_unavailable",
            workspace_id=str(workspace_id),
            error=str(exc),
        )
        raise ServiceUnavailableError(
            "AI rendering is temporarily unavailable. Please try again shortly."
        ) from exc

    if allowed:
        return

    retry_after = ESTIMATE_RENDER_WINDOW_SECONDS
    try:
        ttl = await redis_client.ttl(_key(workspace_id))
        if ttl is not None and ttl >= 0:
            retry_after = max(1, int(ttl))
    except (RedisError, ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "estimate_render_rate_limit_ttl_unavailable",
            workspace_id=str(workspace_id),
            error=str(exc),
        )

    logger.info(
        "estimate_render_rate_limit_exceeded",
        workspace_id=str(workspace_id),
        limit=ESTIMATE_RENDER_LIMIT,
        current=current,
        retry_after_seconds=retry_after,
        timestamp=datetime.now(UTC).isoformat(),
    )
    raise_rate_limited(
        retry_after,
        detail="This workspace has reached its hourly AI render limit. Please try again later.",
    )
