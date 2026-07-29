"""Tests for the per-user Redis rate limits on authenticated auth endpoints.

Pins the security contract added alongside
``app.services.rate_limiting.auth_limiter``:

- ``POST /auth/change-password`` is capped at 5 attempts per user per hour.
- ``POST /auth/ws-ticket`` is capped at 30 tickets per user per minute.

The route handlers go through the shared ``CurrentUser`` dependency to identify
the caller, then delegate the limit check to the auth limiter. These tests
override the ``CurrentUser`` dependency with a fake user and patch
``_check_and_increment`` (the only thing that talks to Redis) so the suite is
hermetic — no Redis, no DB, no network.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.api.v1 import auth as auth_module
from app.services.rate_limiting import auth_limiter


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


class _FakeUser:
    """Minimal stand-in for ``app.models.user.User`` for auth-route tests."""

    def __init__(self, user_id: int = 42) -> None:
        self.id = user_id
        self.email = "user@example.com"
        self.full_name = "Test User"
        self.is_active = True
        # Argon2id-style placeholder; the change-password route only calls
        # ``verify_password`` against this when the rate limit lets it through.
        self.hashed_password = "not-a-real-hash"


def _make_test_app(user: _FakeUser) -> FastAPI:
    """Build a test app with the auth router and a fake current-user override."""
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(auth_module.router, prefix="/api/v1/auth")
    app.dependency_overrides[get_current_user] = lambda: user
    return app


@pytest.fixture
def fake_user() -> _FakeUser:
    return _FakeUser(user_id=42)


@pytest.fixture
async def client(fake_user: _FakeUser) -> AsyncIterator[AsyncClient]:
    app = _make_test_app(fake_user)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class _Counter:
    """Drop-in replacement for ``auth_limiter._check_and_increment``.

    Tracks per-(scope, user_id) counts the same way the real Lua script does,
    so we can exercise the route at the limit boundary without Redis.
    """

    def __init__(self) -> None:
        self.counts: dict[tuple[str, int], int] = {}

    async def __call__(
        self,
        scope: str,
        user_id: int,
        limit: int,
        window_seconds: int,
    ) -> tuple[bool, int]:
        del window_seconds  # not asserted on here; window is a config concern
        key = (scope, user_id)
        current = self.counts.get(key, 0)
        if current >= limit:
            return False, current
        self.counts[key] = current + 1
        return True, self.counts[key]


class TestChangePasswordRateLimit:
    """``POST /auth/change-password`` — 5 per user per hour."""

    async def test_returns_429_after_limit(self, client: AsyncClient, fake_user: _FakeUser) -> None:
        """6th attempt within the window returns 429 with the expected detail."""
        counter = _Counter()

        # Patch the limiter primitive and short-circuit the route body for the
        # successful path so we're only exercising the limit gate.
        with (
            patch.object(auth_limiter, "_check_and_increment", new=counter),
            patch(
                "app.api.v1.auth.verify_password", return_value=False
            ),  # generic 400, doesn't matter — we only care about the 429 cutover
        ):
            # First 5 calls are allowed by the limiter (they then fail with 400
            # because verify_password returns False — that's fine).
            for i in range(auth_limiter.CHANGE_PASSWORD_LIMIT):
                resp = await client.post(
                    "/api/v1/auth/change-password",
                    json={
                        "current_password": "old-password",
                        "new_password": "new-password-123!",
                    },
                )
                assert resp.status_code != 429, (
                    f"request {i + 1} should pass the rate limit, "
                    f"got {resp.status_code}: {resp.text}"
                )

            # 6th call within the window must be rejected at the limiter.
            resp = await client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "old-password",
                    "new_password": "new-password-123!",
                },
            )

        assert resp.status_code == 429
        assert resp.json()["detail"] == "Too many password change attempts. Please try again later."
        # All recorded attempts were tagged with the authenticated user's id.
        assert counter.counts[("change_password", fake_user.id)] == (
            auth_limiter.CHANGE_PASSWORD_LIMIT
        )

    async def test_keys_by_user_id_not_ip(self, client: AsyncClient, fake_user: _FakeUser) -> None:
        """The limiter is invoked with the current user's id, not an IP string."""
        spy = AsyncMock()

        # Patch the symbol the route actually references.
        with patch("app.api.v1.auth.enforce_change_password_rate_limit", new=spy):
            await client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "old-password",
                    "new_password": "new-password-123!",
                },
            )

        spy.assert_awaited_once_with(fake_user.id)


class TestWsTicketRateLimit:
    """``POST /auth/ws-ticket`` — 30 per user per minute."""

    async def test_returns_429_after_limit(self, client: AsyncClient, fake_user: _FakeUser) -> None:
        """31st ticket request within the window returns 429."""
        counter = _Counter()

        with patch.object(auth_limiter, "_check_and_increment", new=counter):
            for i in range(auth_limiter.WS_TICKET_LIMIT):
                resp = await client.post("/api/v1/auth/ws-ticket")
                assert resp.status_code == 200, (
                    f"request {i + 1} should succeed, got {resp.status_code}: {resp.text}"
                )
                assert "ticket" in resp.json()

            resp = await client.post("/api/v1/auth/ws-ticket")

        assert resp.status_code == 429
        assert resp.json()["detail"] == "Too many WebSocket ticket requests. Please slow down."
        assert counter.counts[("ws_ticket", fake_user.id)] == (auth_limiter.WS_TICKET_LIMIT)

    async def test_keys_by_user_id_not_ip(self, client: AsyncClient, fake_user: _FakeUser) -> None:
        spy = AsyncMock()

        with patch("app.api.v1.auth.enforce_ws_ticket_rate_limit", new=spy):
            resp = await client.post("/api/v1/auth/ws-ticket")

        assert resp.status_code == 200
        spy.assert_awaited_once_with(fake_user.id)


class TestAuthLimiterUnit:
    """Direct unit tests for the limiter helper."""

    async def test_enforce_change_password_raises_when_disallowed(self) -> None:
        from fastapi import HTTPException

        async def fake_check(
            scope: str,
            user_id: int,
            limit: int,
            window_seconds: int,
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return False, 999

        with (
            patch.object(auth_limiter, "_check_and_increment", new=fake_check),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_limiter.enforce_change_password_rate_limit(user_id=1)

        assert exc_info.value.status_code == 429

    async def test_enforce_ws_ticket_raises_when_disallowed(self) -> None:
        from fastapi import HTTPException

        async def fake_check(
            scope: str,
            user_id: int,
            limit: int,
            window_seconds: int,
        ) -> tuple[bool, int]:
            del scope, user_id, limit, window_seconds
            return False, 999

        with (
            patch.object(auth_limiter, "_check_and_increment", new=fake_check),
            pytest.raises(HTTPException) as exc_info,
        ):
            await auth_limiter.enforce_ws_ticket_rate_limit(user_id=1)

        assert exc_info.value.status_code == 429

    async def test_fails_open_on_redis_error(self) -> None:
        """Redis outages must not lock authenticated users out."""

        async def boom(**_: object) -> tuple[bool, int]:
            raise RuntimeError("redis down")

        with patch.object(auth_limiter, "_check_and_increment", new=boom):
            # Must NOT raise — fail-open keeps password rotation working.
            await auth_limiter.enforce_change_password_rate_limit(user_id=1)
            await auth_limiter.enforce_ws_ticket_rate_limit(user_id=1)


class TestAuthLimiterConfig:
    """Pin the documented limits so silent loosening trips CI."""

    def test_change_password_is_five_per_hour(self) -> None:
        assert auth_limiter.CHANGE_PASSWORD_LIMIT == 5
        assert auth_limiter.CHANGE_PASSWORD_WINDOW_SECONDS == 3600

    def test_ws_ticket_is_thirty_per_minute(self) -> None:
        assert auth_limiter.WS_TICKET_LIMIT == 30
        assert auth_limiter.WS_TICKET_WINDOW_SECONDS == 60
