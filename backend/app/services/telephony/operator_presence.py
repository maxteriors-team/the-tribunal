"""Which operators' browsers are currently able to take an inbound call.

Presence is a **heartbeat in Redis**, not a connection the backend holds: the
dashboard registers its browser headset and then re-asserts availability every
~60 seconds via ``POST /calls/presence``. A closed tab, a suspended laptop, or a
crashed replica therefore expires on its own within :data:`PRESENCE_TTL_SECONDS`
instead of leaving a phantom operator that absorbs rings into silence.

Two markers per operator:

* ``voice:presence:{workspace_id}:{user_id}`` — available, heartbeat TTL.
* ``voice:presence:busy:{workspace_id}:{user_id}`` — already on a bridged call,
  so a second simultaneous inbound call must not ring the same headset.

Both keys embed the workspace id, and every lookup is scanned under the
workspace's own prefix, so one tenant's roster can never surface another's.
Webhooks can land on any replica, so none of this may live in process memory.
"""

from __future__ import annotations

import structlog

from app.db.redis import get_redis

logger = structlog.get_logger()

_PRESENCE_PREFIX = "voice:presence:"
_BUSY_PREFIX = "voice:presence:busy:"

# Slightly over one missed heartbeat: the dashboard re-asserts presence every
# ~60s, so 75s tolerates one late beat without keeping a closed tab ringable.
PRESENCE_TTL_SECONDS = 75

# A bridged operator call can legitimately run long, so the busy marker outlives
# any plausible conversation. It is cleared explicitly on hangup; the TTL exists
# only so a lost hangup webhook cannot strand an operator as permanently busy.
BUSY_TTL_SECONDS = 3600


def _presence_key(workspace_id: str, user_id: int) -> str:
    return f"{_PRESENCE_PREFIX}{workspace_id}:{user_id}"


def _busy_key(workspace_id: str, user_id: int) -> str:
    return f"{_BUSY_PREFIX}{workspace_id}:{user_id}"


async def mark_available(workspace_id: str, user_id: int) -> None:
    """Record (or refresh) this operator as ready to be rung."""
    try:
        client = await get_redis()
        await client.set(
            _presence_key(workspace_id, user_id),
            str(user_id),
            ex=PRESENCE_TTL_SECONDS,
        )
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_presence_mark_available_failed", error=str(exc))


async def mark_unavailable(workspace_id: str, user_id: int) -> None:
    """Drop this operator from the ringable roster immediately."""
    try:
        client = await get_redis()
        await client.delete(_presence_key(workspace_id, user_id))
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_presence_mark_unavailable_failed", error=str(exc))


async def list_available(workspace_id: str) -> list[int]:
    """Return the user ids of available operators in this workspace only.

    Scanning is bounded to the workspace's own key prefix. Keys whose suffix is
    not an integer user id are ignored rather than raising: presence is an
    availability hint, and a malformed key must not break call routing.
    """
    prefix = f"{_PRESENCE_PREFIX}{workspace_id}:"
    user_ids: list[int] = []
    try:
        client = await get_redis()
        async for key in client.scan_iter(match=f"{prefix}*", count=100):
            suffix = str(key)[len(prefix) :]
            try:
                user_ids.append(int(suffix))
            except ValueError:
                continue
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_presence_list_failed", error=str(exc))
        return []
    return sorted(set(user_ids))


async def mark_busy(workspace_id: str, user_id: int) -> None:
    """Flag an operator as on a call so concurrent inbound calls skip them."""
    try:
        client = await get_redis()
        await client.set(
            _busy_key(workspace_id, user_id),
            str(user_id),
            ex=BUSY_TTL_SECONDS,
        )
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_presence_mark_busy_failed", error=str(exc))


async def clear_busy(workspace_id: str, user_id: int) -> None:
    """Release the busy flag once the operator's call has ended."""
    try:
        client = await get_redis()
        await client.delete(_busy_key(workspace_id, user_id))
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_presence_clear_busy_failed", error=str(exc))


async def is_busy(workspace_id: str, user_id: int) -> bool:
    """Return True when this operator is already on a bridged call."""
    try:
        client = await get_redis()
        return bool(await client.exists(_busy_key(workspace_id, user_id)))
    except Exception as exc:  # pragma: no cover - Redis best-effort
        logger.warning("operator_presence_is_busy_failed", error=str(exc))
        return False


async def list_idle_available(workspace_id: str) -> list[int]:
    """Return available operators in this workspace who are not already on a call."""
    available = await list_available(workspace_id)
    idle: list[int] = []
    for user_id in available:
        if not await is_busy(workspace_id, user_id):
            idle.append(user_id)
    return idle
