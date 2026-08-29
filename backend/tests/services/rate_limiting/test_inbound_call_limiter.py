"""Anonymous inbound spend and concurrent-capacity limits."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.rate_limiting import softphone_limiter as limiter

pytestmark = pytest.mark.asyncio


async def test_inbound_budget_keys_hash_the_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = SimpleNamespace(eval=AsyncMock(return_value=[1, 1]))
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis))
    caller = "+12025550123"

    await limiter.enforce_inbound_call_limits(workspace_id=str(uuid.uuid4()), caller_phone=caller)

    assert redis.eval.await_count == 3
    assert caller not in str(redis.eval.await_args_list)
    assert "caller-hour" in str(redis.eval.await_args_list[0])
    assert "workspace-hour" in str(redis.eval.await_args_list[1])
    assert "workspace-day" in str(redis.eval.await_args_list[2])


async def test_caller_limit_has_a_distinct_busy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = SimpleNamespace(eval=AsyncMock(return_value=[0, 6]))
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis))

    with pytest.raises(limiter.InboundCallerRateLimitError):
        await limiter.enforce_inbound_call_limits(
            workspace_id=str(uuid.uuid4()), caller_phone="+12025550123"
        )


async def test_workspace_limit_remains_a_fallback_path(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = SimpleNamespace(eval=AsyncMock(side_effect=([1, 1], [0, 60])))
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis))

    with pytest.raises(limiter.SoftphoneRateLimitError) as exc:
        await limiter.enforce_inbound_call_limits(
            workspace_id=str(uuid.uuid4()), caller_phone="+12025550123"
        )

    assert not isinstance(exc.value, limiter.InboundCallerRateLimitError)


async def test_concurrent_reservation_is_atomic_and_idempotency_keyed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = SimpleNamespace(eval=AsyncMock(return_value=[1, 2]))
    set_active = MagicMock()
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(limiter, "set_inbound_active_calls", set_active)
    workspace_id = str(uuid.uuid4())

    await limiter.reserve_inbound_call_capacity(
        workspace_id=workspace_id, call_control_id="provider-call-id"
    )

    args = redis.eval.await_args.args
    assert "ZREMRANGEBYSCORE" in args[0]
    assert "provider-call-id" in args
    set_active.assert_called_once_with(workspace_id, 2)


async def test_concurrent_limit_and_redis_outage_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = SimpleNamespace(eval=AsyncMock(return_value=[0, 2]))
    monkeypatch.setattr(limiter, "get_redis", AsyncMock(return_value=redis))
    monkeypatch.setattr(limiter, "set_inbound_active_calls", lambda *_: None)

    with pytest.raises(limiter.InboundCallCapacityError):
        await limiter.reserve_inbound_call_capacity(
            workspace_id=str(uuid.uuid4()), call_control_id="provider-call-id"
        )

    monkeypatch.setattr(limiter, "get_redis", AsyncMock(side_effect=RuntimeError("offline")))
    with pytest.raises(limiter.SoftphoneRateLimitUnavailableError):
        await limiter.reserve_inbound_call_capacity(
            workspace_id=str(uuid.uuid4()), call_control_id="provider-call-id"
        )
