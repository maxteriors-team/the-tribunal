"""Validation tests for the authentication API endpoints.

These tests exercise request validation (Pydantic/OAuth2 form parsing) and
auth/authorization failures without touching a real database. Where a route
reaches the DB layer, we patch the rate-limit helper and the session factory.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Result

from app.api.v1 import auth as auth_module


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app registering only the auth router."""
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(auth_module.router, prefix="/api/v1/auth")
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Async HTTP client bound to the auth test app."""
    app = _make_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _mock_db_no_user() -> AsyncMock:
    """Return a mocked AsyncSession whose queries return no user."""
    mock_result = MagicMock(spec=Result)
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalar.return_value = 0

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)
    return mock_db


class TestLoginValidation:
    """Validation failures on POST /api/v1/auth/login."""

    async def test_login_missing_fields_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/login with no form fields returns 422."""
        response = await client.post("/api/v1/auth/login", data={})
        assert response.status_code == 422

    async def test_login_missing_password_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/login with no password returns 422."""
        response = await client.post(
            "/api/v1/auth/login",
            data={"username": "someone@example.com"},
        )
        assert response.status_code == 422

    async def test_login_missing_username_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/login with no username returns 422."""
        response = await client.post(
            "/api/v1/auth/login",
            data={"password": "hunter2password"},
        )
        assert response.status_code == 422

    async def test_login_with_json_body_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/login with JSON content-type (instead of form) returns 422.

        The endpoint expects OAuth2PasswordRequestForm (application/x-www-form-urlencoded).
        """
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "someone@example.com", "password": "hunter2password"},
        )
        assert response.status_code == 422


class TestRegisterValidation:
    """Validation failures on POST /api/v1/auth/register."""

    async def test_register_empty_body_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/register with empty body returns 422."""
        response = await client.post("/api/v1/auth/register", json={})
        assert response.status_code == 422

    async def test_register_invalid_email_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/register with an invalid email returns 422."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not-a-valid-email",
                "password": "validpassword123",
            },
        )
        assert response.status_code == 422

    async def test_register_short_password_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/register with a password shorter than 8 chars returns 422."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "valid@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 422

    async def test_register_missing_password_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/register without a password field returns 422."""
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": "valid@example.com"},
        )
        assert response.status_code == 422

    async def test_register_missing_email_returns_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/register without an email field returns 422."""
        response = await client.post(
            "/api/v1/auth/register",
            json={"password": "validpassword123"},
        )
        assert response.status_code == 422


class TestMeEndpointAuth:
    """Auth failures on GET /api/v1/auth/me."""

    async def test_me_without_token_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /auth/me without Authorization header returns 401."""
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401

    async def test_me_with_invalid_token_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /auth/me with a bogus bearer token returns 401."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-valid-jwt-token"},
        )
        assert response.status_code == 401

    async def test_me_with_malformed_auth_header_returns_401(
        self, client: AsyncClient
    ) -> None:
        """GET /auth/me with a malformed Authorization header returns 401."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "NotBearer foo"},
        )
        assert response.status_code == 401


class TestChangePasswordAuth:
    """Auth failures on POST /api/v1/auth/change-password."""

    async def test_change_password_without_token_returns_401(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/change-password without token returns 401."""
        response = await client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "oldpassword123",
                "new_password": "newpassword123",
            },
        )
        assert response.status_code == 401

    async def test_change_password_short_new_password_returns_401_before_422(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/change-password without auth returns 401 regardless of body.

        Note: FastAPI runs auth dependency before body parsing, so 401 is returned
        even when the new_password is too short.
        """
        response = await client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "oldpass", "new_password": "x"},
        )
        assert response.status_code == 401


class TestLoginFlow:
    """Happy/error paths on POST /api/v1/auth/login with mocked DB."""

    async def test_login_wrong_credentials_returns_401(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/login with unknown user returns 401 after DB lookup."""
        mock_db = _mock_db_no_user()

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=mock_db),
        ):
            response = await client.post(
                "/api/v1/auth/login",
                data={"username": "nobody@example.com", "password": "wrongpassword"},
            )

        assert response.status_code == 401


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh."""

    async def test_refresh_without_cookie_returns_401(
        self, client: AsyncClient
    ) -> None:
        """POST /auth/refresh with no refresh_token cookie returns 401."""
        mock_db = _mock_db_no_user()

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=mock_db),
        ):
            response = await client.post("/api/v1/auth/refresh")

        assert response.status_code == 401

    async def test_refresh_with_invalid_cookie_returns_401(self) -> None:
        """POST /auth/refresh with a bogus refresh_token cookie returns 401."""
        mock_db = _mock_db_no_user()
        app = _make_test_app()

        with (
            patch("app.api.v1.auth._check_auth_rate_limit", new=AsyncMock()),
            patch("app.db.session.AsyncSessionLocal", return_value=mock_db),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://testserver",
                cookies={"refresh_token": "not-a-real-refresh-token"},
            ) as ac:
                response = await ac.post("/api/v1/auth/refresh")

        assert response.status_code == 401
