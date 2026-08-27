"""Cost and outage behavior for the layered AI-render limiter."""

import uuid
from unittest.mock import AsyncMock, call, patch

import pytest
from fastapi import HTTPException

from app.services.exceptions import ServiceUnavailableError
from app.services.rate_limiting import estimate_render_limiter


@pytest.mark.asyncio
async def test_allows_render_below_all_hourly_caps() -> None:
    workspace_id = uuid.uuid4()
    user_id = 42
    redis = AsyncMock()
    redis.eval.side_effect = [[1, 1], [1, 1], [1, 1]]

    with patch.object(estimate_render_limiter, "get_redis", new=AsyncMock(return_value=redis)):
        await estimate_render_limiter.enforce_estimate_render_rate_limit(workspace_id, user_id)

    assert redis.eval.await_args_list == [
        call(
            estimate_render_limiter.INCREMENT_WITH_LIMIT_SCRIPT,
            1,
            f"rate_limit:estimate_render:user:{user_id}",
            estimate_render_limiter.ESTIMATE_RENDER_USER_LIMIT,
            estimate_render_limiter.ESTIMATE_RENDER_WINDOW_SECONDS,
        ),
        call(
            estimate_render_limiter.INCREMENT_WITH_LIMIT_SCRIPT,
            1,
            f"rate_limit:estimate_render:{workspace_id}",
            estimate_render_limiter.ESTIMATE_RENDER_WORKSPACE_LIMIT,
            estimate_render_limiter.ESTIMATE_RENDER_WINDOW_SECONDS,
        ),
        call(
            estimate_render_limiter.INCREMENT_WITH_LIMIT_SCRIPT,
            1,
            "rate_limit:estimate_render:platform",
            estimate_render_limiter.ESTIMATE_RENDER_PLATFORM_LIMIT,
            estimate_render_limiter.ESTIMATE_RENDER_WINDOW_SECONDS,
        ),
    ]


@pytest.mark.asyncio
async def test_user_cap_cannot_be_reset_with_a_new_workspace() -> None:
    user_id = 42
    redis = AsyncMock()
    redis.eval.return_value = [0, estimate_render_limiter.ESTIMATE_RENDER_USER_LIMIT]
    redis.ttl.return_value = 73

    with (
        patch.object(estimate_render_limiter, "get_redis", new=AsyncMock(return_value=redis)),
        pytest.raises(HTTPException),
    ):
        await estimate_render_limiter.enforce_estimate_render_rate_limit(uuid.uuid4(), user_id)

    redis.eval.assert_awaited_once_with(
        estimate_render_limiter.INCREMENT_WITH_LIMIT_SCRIPT,
        1,
        f"rate_limit:estimate_render:user:{user_id}",
        estimate_render_limiter.ESTIMATE_RENDER_USER_LIMIT,
        estimate_render_limiter.ESTIMATE_RENDER_WINDOW_SECONDS,
    )


@pytest.mark.asyncio
async def test_rejects_render_at_platform_cap_with_retry_after() -> None:
    redis = AsyncMock()
    redis.eval.side_effect = [
        [1, 1],
        [1, 1],
        [0, estimate_render_limiter.ESTIMATE_RENDER_PLATFORM_LIMIT],
    ]
    redis.ttl.return_value = 73

    with (
        patch.object(estimate_render_limiter, "get_redis", new=AsyncMock(return_value=redis)),
        pytest.raises(HTTPException) as exc_info,
    ):
        await estimate_render_limiter.enforce_estimate_render_rate_limit(uuid.uuid4(), 42)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "73"}
    redis.ttl.assert_awaited_once_with("rate_limit:estimate_render:platform")


@pytest.mark.asyncio
async def test_fails_closed_when_spend_counter_is_unavailable() -> None:
    with (
        patch.object(
            estimate_render_limiter,
            "get_redis",
            new=AsyncMock(side_effect=ConnectionError("redis unavailable")),
        ),
        pytest.raises(ServiceUnavailableError, match="temporarily unavailable"),
    ):
        await estimate_render_limiter.enforce_estimate_render_rate_limit(uuid.uuid4(), 42)
