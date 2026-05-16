"""Tests for ``auth_limiter`` — Retry-After contract on the 429 path.

Authenticated routes (``/change-password``, ``/ws-ticket``) emit per-user 429s
through this limiter; the header must always be present and reflect the live
Redis TTL when available.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.rate_limiting import auth_limiter


class TestEnforceAuthRateLimit:
    async def test_allows_under_limit(self) -> None:
        async def fake_check(
            scope: str, user_id: int, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return True, 1

        with patch.object(auth_limiter, "_check_and_increment", new=fake_check):
            await auth_limiter.enforce_change_password_rate_limit(user_id=42)

    async def test_change_password_429_carries_retry_after(self) -> None:
        async def fake_check(
            scope: str, user_id: int, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return False, 6

        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(return_value=2700)

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(auth_limiter, "_check_and_increment", new=fake_check),
            patch.object(auth_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_limiter.enforce_change_password_rate_limit(user_id=42)

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "2700"

    async def test_ws_ticket_429_carries_retry_after(self) -> None:
        async def fake_check(
            scope: str, user_id: int, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return False, 31

        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(return_value=15)

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(auth_limiter, "_check_and_increment", new=fake_check),
            patch.object(auth_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_limiter.enforce_ws_ticket_rate_limit(user_id=99)

        assert exc_info.value.status_code == 429
        assert exc_info.value.headers is not None
        assert exc_info.value.headers["Retry-After"] == "15"

    async def test_retry_after_falls_back_to_window_when_ttl_missing(self) -> None:
        async def fake_check(
            scope: str, user_id: int, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return False, 6

        fake_redis = AsyncMock()
        # TTL -2 = key missing; -1 = no expire set. Both must fall back.
        fake_redis.ttl = AsyncMock(return_value=-2)

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(auth_limiter, "_check_and_increment", new=fake_check),
            patch.object(auth_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_limiter.enforce_change_password_rate_limit(user_id=42)

        assert exc_info.value.headers is not None
        # Falls back to the configured change-password window.
        assert exc_info.value.headers["Retry-After"] == str(
            auth_limiter.CHANGE_PASSWORD_WINDOW_SECONDS
        )

    async def test_retry_after_falls_back_on_ttl_error(self) -> None:
        async def fake_check(
            scope: str, user_id: int, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return False, 31

        fake_redis = AsyncMock()
        fake_redis.ttl = AsyncMock(side_effect=RuntimeError("redis blip"))

        async def fake_get_redis() -> AsyncMock:
            return fake_redis

        with (
            patch.object(auth_limiter, "_check_and_increment", new=fake_check),
            patch.object(auth_limiter, "get_redis", new=fake_get_redis),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_limiter.enforce_ws_ticket_rate_limit(user_id=99)

        assert exc_info.value.headers is not None
        assert int(exc_info.value.headers["Retry-After"]) > 0

    async def test_fails_open_on_check_redis_error(self) -> None:
        async def boom(
            scope: str, user_id: int, limit: int, window_seconds: int
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            raise RuntimeError("redis down")

        with patch.object(auth_limiter, "_check_and_increment", new=boom):
            # Must NOT raise.
            await auth_limiter.enforce_change_password_rate_limit(user_id=42)
            await auth_limiter.enforce_ws_ticket_rate_limit(user_id=42)
