"""Connection limits and lifecycle guards for voice WebSocket endpoints.

This module centralises the backpressure primitives used by both
``voice_bridge`` (Telnyx <-> AI provider) and ``voice_test`` (browser <-> AI
provider) sockets:

- Global semaphores cap total concurrent connections per endpoint. New
  arrivals are rejected with ``WS_1013_TRY_AGAIN_LATER`` once full.
- A per-workspace Redis SET tracks active sessions so a single tenant can't
  exhaust the global pool. The cap holds across multiple backend replicas.
- A heartbeat loop pings the peer on a fixed cadence and closes the socket
  if no pong arrives within the timeout.
- An absolute duration cap acts as a last-resort backstop for stuck sessions.

All helpers degrade gracefully: Redis failures log a warning and admit the
connection rather than tearing down a real call over an infra hiccup.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import WebSocket, status
from starlette.websockets import WebSocketState

from app.core.config import settings
from app.db.redis import get_redis

logger = structlog.get_logger()

# Module-level semaphores. Sized from settings on first import so test suites
# that monkeypatch settings before importing this module get the expected
# value. Re-sizing at runtime would require coordinating with in-flight
# acquirers, so we treat these as immutable for the process lifetime.
_voice_bridge_semaphore = asyncio.Semaphore(settings.voice_bridge_max_connections)
_voice_test_semaphore = asyncio.Semaphore(settings.voice_test_max_connections)


def voice_bridge_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore guarding the Telnyx voice bridge."""
    return _voice_bridge_semaphore


def voice_test_semaphore() -> asyncio.Semaphore:
    """Return the module-level semaphore guarding the browser voice test."""
    return _voice_test_semaphore


def _workspace_set_key(workspace_id: str) -> str:
    """Redis key holding the set of active session IDs for a workspace."""
    return f"voice:active_sessions:{workspace_id}"


async def _workspace_session_count(workspace_id: str) -> int | None:
    """Return the current active session count for a workspace, or None on error."""
    try:
        client = await get_redis()
        # SCARD is O(1) and returns 0 for a missing key.
        return int(await client.scard(_workspace_set_key(workspace_id)))  # type: ignore[misc]
    except Exception as exc:
        logger.warning(
            "workspace_session_count_failed",
            workspace_id=workspace_id,
            error=str(exc),
        )
        return None


async def _register_workspace_session(workspace_id: str, session_id: str) -> bool:
    """Add ``session_id`` to the workspace's active set. Returns True on success."""
    try:
        client = await get_redis()
        key = _workspace_set_key(workspace_id)
        await client.sadd(key, session_id)  # type: ignore[misc]
        # Safety expiry: if a worker crashes mid-session the set will self-clean
        # well after any legitimate call could still be alive.
        await client.expire(key, settings.voice_max_call_duration_seconds * 2)
        return True
    except Exception as exc:
        logger.warning(
            "workspace_session_register_failed",
            workspace_id=workspace_id,
            session_id=session_id,
            error=str(exc),
        )
        return False


async def _release_workspace_session(workspace_id: str, session_id: str) -> None:
    """Remove ``session_id`` from the workspace's active set. Best-effort."""
    try:
        client = await get_redis()
        await client.srem(_workspace_set_key(workspace_id), session_id)  # type: ignore[misc]
    except Exception as exc:
        logger.warning(
            "workspace_session_release_failed",
            workspace_id=workspace_id,
            session_id=session_id,
            error=str(exc),
        )


async def reject_overloaded(websocket: WebSocket, reason: str, log: Any) -> None:
    """Reject a connection because a capacity limit is full.

    ``WS_1013_TRY_AGAIN_LATER`` is the canonical close code for transient
    server overload. Telnyx and well-behaved browser clients should retry.
    """
    log.warning("voice_ws_overloaded_rejected", reason=reason)
    # The socket may or may not be accepted yet. ``close()`` handles both.
    with contextlib.suppress(Exception):
        await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)


@asynccontextmanager
async def acquire_connection_slot(
    websocket: WebSocket,
    semaphore: asyncio.Semaphore,
    log: Any,
    *,
    endpoint: str,
) -> AsyncIterator[bool]:
    """Try to acquire a slot from ``semaphore`` without blocking.

    Yields ``True`` if the slot was acquired (caller is responsible for the
    rest of the connection lifecycle) and ``False`` if the socket was rejected
    with ``WS_1013_TRY_AGAIN_LATER`` (caller should return immediately).

    The semaphore is released on context exit regardless of outcome path.
    """
    # Non-blocking acquire. ``asyncio.Semaphore`` exposes ``locked()`` (True
    # when no slots remain) but not a public ``try_acquire``. Reading the
    # private ``_value`` and acquiring is safe in single-event-loop code
    # because asyncio scheduling is cooperative — nothing can preempt us
    # between the check and the call.
    acquired = False
    try:
        if semaphore.locked():
            await reject_overloaded(
                websocket,
                reason=f"{endpoint}_global_limit",
                log=log,
            )
            yield False
            return
        await semaphore.acquire()
        acquired = True

        log.info(
            "voice_ws_slot_acquired",
            endpoint=endpoint,
            remaining=getattr(semaphore, "_value", -1),
        )
        yield True
    finally:
        if acquired:
            semaphore.release()
            log.info(
                "voice_ws_slot_released",
                endpoint=endpoint,
                remaining=getattr(semaphore, "_value", -1),
            )


@asynccontextmanager
async def acquire_workspace_slot(
    websocket: WebSocket,
    workspace_id: str | None,
    log: Any,
) -> AsyncIterator[tuple[bool, str | None]]:
    """Enforce per-workspace concurrent session cap via Redis.

    Yields ``(ok, session_id)``:
    - ``ok=True`` means the slot was reserved; caller proceeds with the call.
    - ``ok=False`` means the workspace is at capacity and the socket has
      already been closed with ``WS_1013_TRY_AGAIN_LATER``. Caller must return.

    Redis outages fail open (admit the connection) so a transient cache blip
    can't tear down live voice traffic. The trade-off is intentional: the
    global semaphore still provides hard backpressure.
    """
    if not workspace_id:
        # No workspace context (e.g. agent lookup failed) — skip the per-tenant
        # check. The global semaphore is still in force.
        yield True, None
        return

    session_id = str(uuid.uuid4())
    count = await _workspace_session_count(workspace_id)
    if count is not None and count >= settings.voice_workspace_max_sessions:
        log.warning(
            "voice_ws_workspace_limit_reached",
            workspace_id=workspace_id,
            active_sessions=count,
            cap=settings.voice_workspace_max_sessions,
        )
        await reject_overloaded(websocket, reason="workspace_limit", log=log)
        yield False, None
        return

    registered = await _register_workspace_session(workspace_id, session_id)
    try:
        log.info(
            "voice_ws_workspace_slot_acquired",
            workspace_id=workspace_id,
            session_id=session_id,
            prior_count=count,
        )
        yield True, session_id
    finally:
        if registered:
            await _release_workspace_session(workspace_id, session_id)


class HeartbeatMonitor:
    """Send ``{"type":"ping"}`` periodically; close the socket on pong timeout.

    Intended for the browser test endpoint where the client speaks JSON. The
    Telnyx bridge has its own framing (``event: media``) and does not run a
    heartbeat — but we still want the duration cap to apply, so the bridge
    calls ``mark_activity()`` from its own message loop on every inbound frame
    and uses ``arm()`` to enable the timeout watchdog only.
    """

    def __init__(
        self,
        websocket: WebSocket,
        log: Any,
        *,
        interval: float = float(settings.voice_heartbeat_interval_seconds),
        timeout: float = float(settings.voice_pong_timeout_seconds),
        send_ping: bool = True,
    ) -> None:
        self._ws = websocket
        self._log = log
        self._interval = interval
        self._timeout = timeout
        self._send_ping = send_ping
        self._last_activity = time.monotonic()
        self._task: asyncio.Task[None] | None = None

    def mark_activity(self) -> None:
        """Reset the inactivity clock. Call on any received frame or pong."""
        self._last_activity = time.monotonic()

    def start(self) -> None:
        """Spawn the background heartbeat task. Idempotent."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="voice-heartbeat")

    async def stop(self) -> None:
        """Cancel the heartbeat task."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        self._task = None

    async def _run(self) -> None:
        try:
            while True:
                await asyncio.sleep(self._interval)
                # Timeout check
                idle = time.monotonic() - self._last_activity
                if idle >= self._timeout:
                    self._log.warning(
                        "voice_ws_pong_timeout",
                        idle_seconds=round(idle, 1),
                        timeout=self._timeout,
                    )
                    with contextlib.suppress(Exception):
                        await self._ws.close(code=status.WS_1011_INTERNAL_ERROR)
                    return
                # Send ping (best-effort; if the socket is gone the surrounding
                # task will tear down anyway).
                if self._send_ping and self._ws.application_state == WebSocketState.CONNECTED:
                    try:
                        await self._ws.send_json({"type": "ping"})
                    except Exception as exc:
                        self._log.debug("voice_ws_ping_send_failed", error=str(exc))
                        return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._log.exception("voice_heartbeat_loop_error", error=str(exc))


async def enforce_duration_cap(
    websocket: WebSocket,
    log: Any,
    *,
    max_seconds: int = settings.voice_max_call_duration_seconds,
) -> None:
    """Sleep ``max_seconds`` then force-close the socket.

    Run as a background task. The surrounding endpoint's main coroutine will
    observe the close and clean up. This is a backstop only — normal hangups
    are handled by the relay/message loops.
    """
    try:
        await asyncio.sleep(max_seconds)
        log.warning(
            "voice_ws_duration_cap_reached",
            max_seconds=max_seconds,
        )
        with contextlib.suppress(Exception):
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
    except asyncio.CancelledError:
        # Normal teardown path.
        raise
