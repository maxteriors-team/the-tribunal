"""Fail-closed spend and concurrency limits for paid calling paths."""

from __future__ import annotations

from datetime import UTC, datetime
from inspect import isawaitable

import structlog

from app.core.config import settings
from app.core.encryption import hash_phone
from app.core.metrics import set_inbound_active_calls
from app.db.redis import get_redis

logger = structlog.get_logger()

_INCREMENT_WITH_LIMIT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
  return {0, current}
end
current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return {1, current}
"""

_RESERVE_CONCURRENT_CALL = """
local key = KEYS[1]
local member = ARGV[1]
local now = tonumber(ARGV[2])
local expires_at = tonumber(ARGV[3])
local limit = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZSCORE', key, member) then
  redis.call('ZADD', key, expires_at, member)
  redis.call('EXPIRE', key, ttl)
  return {1, redis.call('ZCARD', key)}
end
local current = redis.call('ZCARD', key)
if current >= limit then
  return {0, current}
end
redis.call('ZADD', key, expires_at, member)
redis.call('EXPIRE', key, ttl)
return {1, current + 1}
"""


class SoftphoneRateLimitError(RuntimeError):
    """Raised when an operator or workspace exhausts its call allowance."""


class SoftphoneRateLimitUnavailableError(RuntimeError):
    """Raised when spend protection cannot be checked."""


class InboundCallerRateLimitError(SoftphoneRateLimitError):
    """Raised when one anonymous caller exceeds the pilot's hourly allowance."""


class InboundCallCapacityError(SoftphoneRateLimitError):
    """Raised when a workspace has no remaining concurrent inbound slot."""


async def enforce_softphone_token_limit(*, user_id: int) -> None:
    """Limit short-lived credential minting to ten tokens per user-hour."""
    now = datetime.now(UTC)
    await _check(
        key=f"softphone:token:{user_id}:{now:%Y%m%d%H}",
        limit=10,
        ttl_seconds=3600,
    )


async def enforce_softphone_call_limits(*, workspace_id: str, user_id: int) -> None:
    """Reserve every paid start against operator and workspace call budgets."""
    now = datetime.now(UTC)
    checks = (
        (f"softphone:call:user-hour:{user_id}:{now:%Y%m%d%H}", 60, 3600),
        (f"softphone:call:workspace-hour:{workspace_id}:{now:%Y%m%d%H}", 300, 3600),
        (f"softphone:call:user-day:{user_id}:{now:%Y%m%d}", 300, 86400),
        (f"softphone:call:workspace-day:{workspace_id}:{now:%Y%m%d}", 1500, 86400),
    )
    for key, limit, ttl_seconds in checks:
        await _check(key=key, limit=limit, ttl_seconds=ttl_seconds)


async def enforce_inbound_call_limits(*, workspace_id: str, caller_phone: str) -> None:
    """Reserve anonymous inbound starts without storing caller PII in Redis."""
    now = datetime.now(UTC)
    caller_hash = hash_phone(caller_phone)
    try:
        await _check(
            key=f"inbound-call:caller-hour:{workspace_id}:{caller_hash}:{now:%Y%m%d%H}",
            limit=settings.inbound_voice_caller_hour_limit,
            ttl_seconds=3600,
        )
    except SoftphoneRateLimitError as exc:
        raise InboundCallerRateLimitError(str(exc)) from exc

    checks = (
        (
            f"inbound-call:workspace-hour:{workspace_id}:{now:%Y%m%d%H}",
            settings.inbound_voice_workspace_hour_limit,
            3600,
        ),
        (
            f"inbound-call:workspace-day:{workspace_id}:{now:%Y%m%d}",
            settings.inbound_voice_workspace_day_limit,
            86400,
        ),
    )
    for key, limit, ttl_seconds in checks:
        await _check(key=key, limit=limit, ttl_seconds=ttl_seconds)


async def reserve_inbound_call_capacity(*, workspace_id: str, call_control_id: str) -> None:
    """Atomically reserve one expiring concurrent pilot-call slot."""
    if not call_control_id or len(call_control_id) > 200:
        raise SoftphoneRateLimitUnavailableError("Invalid provider call identifier")

    now = int(datetime.now(UTC).timestamp())
    ttl_seconds = settings.voice_max_call_duration_seconds * 2
    try:
        redis = await get_redis()
        evaluation = redis.eval(
            _RESERVE_CONCURRENT_CALL,
            1,
            f"inbound-call:active:{workspace_id}",
            call_control_id,
            now,
            now + ttl_seconds,
            settings.inbound_voice_workspace_max_concurrent,
            ttl_seconds,
        )
        result = await evaluation if isawaitable(evaluation) else evaluation
        reserved = bool(int(result[0]))
        set_inbound_active_calls(workspace_id, int(result[1]))
    except Exception as exc:
        logger.error(
            "inbound_call_capacity_unavailable",
            error_type=type(exc).__name__,
        )
        raise SoftphoneRateLimitUnavailableError(
            "Calling is unavailable while concurrency protection is offline"
        ) from exc

    if not reserved:
        raise InboundCallCapacityError("Concurrent inbound call limit reached")


async def release_inbound_call_capacity(*, workspace_id: str, call_control_id: str) -> None:
    """Best-effort release; the reservation also expires after the call duration cap."""
    try:
        redis = await get_redis()
        await redis.zrem(f"inbound-call:active:{workspace_id}", call_control_id)
        count_result = redis.zcard(f"inbound-call:active:{workspace_id}")
        count = await count_result if isawaitable(count_result) else count_result
        set_inbound_active_calls(workspace_id, int(count))
    except Exception as exc:
        logger.warning(
            "inbound_call_capacity_release_failed",
            error_type=type(exc).__name__,
        )


async def _check(*, key: str, limit: int, ttl_seconds: int) -> None:
    try:
        redis = await get_redis()
        evaluation = redis.eval(_INCREMENT_WITH_LIMIT, 1, key, limit, ttl_seconds)
        result = await evaluation if isawaitable(evaluation) else evaluation
    except Exception as exc:
        logger.error(
            "call_rate_limit_unavailable",
            error_type=type(exc).__name__,
        )
        raise SoftphoneRateLimitUnavailableError(
            "Calling is unavailable while spend protection is offline"
        ) from exc

    if not bool(int(result[0])):
        raise SoftphoneRateLimitError("Calling limit reached; try again later")
