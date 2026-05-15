"""Tests for the voice WebSocket connection-limit primitives.

Covers:
- Global semaphore rejects with WS_1013 when full and releases on exit.
- Per-workspace Redis cap admits up to N and rejects the N+1th session.
- Redis outages fail open (admit the connection).
- HeartbeatMonitor closes the socket after the inactivity timeout.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status

from app.websockets.connection_limits import (
    HeartbeatMonitor,
    acquire_connection_slot,
    acquire_workspace_slot,
)


def _fake_ws() -> MagicMock:
    """Build a WebSocket double with the surface we touch."""
    ws = MagicMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    ws.application_state = MagicMock()
    return ws


class TestAcquireConnectionSlot:
    async def test_admits_when_slots_available(self) -> None:
        sem = asyncio.Semaphore(1)
        ws = _fake_ws()
        log = MagicMock()

        async with acquire_connection_slot(ws, sem, log, endpoint="t") as ok:
            assert ok is True

        ws.close.assert_not_called()
        # Slot was released after the context exited.
        assert sem._value == 1  # type: ignore[attr-defined]

    async def test_rejects_with_1013_when_full(self) -> None:
        sem = asyncio.Semaphore(1)
        await sem.acquire()  # exhaust the pool
        ws = _fake_ws()
        log = MagicMock()

        async with acquire_connection_slot(ws, sem, log, endpoint="t") as ok:
            assert ok is False

        ws.close.assert_awaited_once_with(code=status.WS_1013_TRY_AGAIN_LATER)

    async def test_releases_slot_on_exception_inside_scope(self) -> None:
        sem = asyncio.Semaphore(1)
        ws = _fake_ws()
        log = MagicMock()

        with pytest.raises(RuntimeError):
            async with acquire_connection_slot(ws, sem, log, endpoint="t") as ok:
                assert ok is True
                raise RuntimeError("boom")

        assert sem._value == 1  # type: ignore[attr-defined]


class TestAcquireWorkspaceSlot:
    async def test_admits_when_no_workspace_id(self) -> None:
        ws = _fake_ws()
        log = MagicMock()
        async with acquire_workspace_slot(ws, None, log) as (ok, sid):
            assert ok is True
            assert sid is None
        ws.close.assert_not_called()

    async def test_rejects_when_workspace_at_cap(self) -> None:
        ws = _fake_ws()
        log = MagicMock()

        fake_client = AsyncMock()
        fake_client.scard = AsyncMock(return_value=10)

        async def fake_get_redis() -> Any:
            return fake_client

        with (
            patch(
                "app.websockets.connection_limits.get_redis",
                new=fake_get_redis,
            ),
            patch(
                "app.websockets.connection_limits.settings.voice_workspace_max_sessions",
                10,
            ),
        ):
            async with acquire_workspace_slot(ws, "ws-1", log) as (ok, sid):
                assert ok is False
                assert sid is None

        ws.close.assert_awaited_once_with(code=status.WS_1013_TRY_AGAIN_LATER)

    async def test_admits_and_releases_under_cap(self) -> None:
        ws = _fake_ws()
        log = MagicMock()

        fake_client = AsyncMock()
        fake_client.scard = AsyncMock(return_value=2)
        fake_client.sadd = AsyncMock(return_value=1)
        fake_client.expire = AsyncMock(return_value=True)
        fake_client.srem = AsyncMock(return_value=1)

        async def fake_get_redis() -> Any:
            return fake_client

        with patch(
            "app.websockets.connection_limits.get_redis", new=fake_get_redis
        ):
            async with acquire_workspace_slot(ws, "ws-1", log) as (ok, sid):
                assert ok is True
                assert isinstance(sid, str) and sid

        fake_client.sadd.assert_awaited()
        fake_client.srem.assert_awaited()
        ws.close.assert_not_called()

    async def test_fails_open_on_redis_outage(self) -> None:
        ws = _fake_ws()
        log = MagicMock()

        async def fake_get_redis() -> Any:
            raise ConnectionError("redis down")

        with patch(
            "app.websockets.connection_limits.get_redis", new=fake_get_redis
        ):
            async with acquire_workspace_slot(ws, "ws-1", log) as (ok, sid):
                # Cache outage \u2192 admit the connection. Global semaphore is still
                # in force upstream.
                assert ok is True
                assert sid is not None

        ws.close.assert_not_called()


class TestHeartbeatMonitor:
    async def test_closes_on_inactivity_timeout(self) -> None:
        ws = _fake_ws()
        log = MagicMock()

        monitor = HeartbeatMonitor(
            ws, log, interval=0.01, timeout=0.02, send_ping=False
        )
        monitor.start()
        # Sleep past the timeout without marking activity.
        await asyncio.sleep(0.1)
        await monitor.stop()

        ws.close.assert_awaited()
        # The first positional/kwarg should be the 1011 internal-error code.
        call = ws.close.await_args
        assert call.kwargs.get("code") == status.WS_1011_INTERNAL_ERROR

    async def test_does_not_close_when_activity_keeps_resetting(self) -> None:
        ws = _fake_ws()
        log = MagicMock()

        monitor = HeartbeatMonitor(
            ws, log, interval=0.01, timeout=0.05, send_ping=False
        )
        monitor.start()
        # Mark activity faster than the timeout repeatedly.
        for _ in range(10):
            await asyncio.sleep(0.01)
            monitor.mark_activity()
        await monitor.stop()

        ws.close.assert_not_called()
