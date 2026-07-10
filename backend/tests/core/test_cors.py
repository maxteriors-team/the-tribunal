"""Tests for the CORS origin allow-list.

Credentialed CORS (``allow_credentials=True``) is pinned to an **exact**
allow-list of origins (``settings.cors_origins`` + ``frontend_url``). It must
never fall back to an ``allow_origin_regex`` that matches ``*.vercel.app`` or a
team-slug pattern: any tenant able to deploy a matching origin could then drive
cookie-authenticated requests against this API. A previous build shipped a
regex scoped to a foreign Vercel team (``ngrout70-6776s-projects``); these tests
lock in that such origins are now rejected.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.main import app as production_app


def _build_allow_origins_from_settings() -> list[str]:
    """Rebuild the exact allow-list the same way ``app.main`` does, in isolation.

    Mirrors the construction in ``backend/app/main.py`` so the test exercises the
    real allow-list shape without depending on import-time middleware order.
    """
    from app.core.config import settings

    origins = set(settings.cors_origins)
    if settings.frontend_url:
        origins.add(settings.frontend_url)
    return list(origins)


def _make_cors_app() -> FastAPI:
    """Build a minimal app with the production CORS allow-list attached."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_build_allow_origins_from_settings(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        # Mirror the production allow-list. Auth flows through httpOnly
        # cookies (gated by ``Access-Control-Allow-Credentials``, not
        # ``Access-Control-Allow-Headers``), so the only request header the
        # frontend ever sends cross-origin is ``Content-Type``. See
        # ``backend/app/main.py`` for the per-header rationale.
        allow_headers=["Content-Type"],
    )

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "ok"}

    return app


@pytest.fixture
async def cors_client() -> AsyncIterator[AsyncClient]:
    """HTTP client bound to a minimal app wired with the production CORS allow-list."""
    app = _make_cors_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


async def _preflight(
    client: AsyncClient, origin: str, *, request_headers: str = "content-type"
) -> str | None:
    """Send a CORS preflight and return the echoed ``access-control-allow-origin``.

    Returns ``None`` when the middleware refuses to echo the origin (the
    origin itself is rejected by the allow-list).

    ``request_headers`` is the value of ``Access-Control-Request-Headers``.
    Starlette echoes the origin even when a requested header isn't in
    ``allow_headers`` — it instead returns a 400 status code. Use
    :func:`_preflight_status` to assert on header-allow-list behaviour.
    """
    response = await client.options(
        "/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": request_headers,
        },
    )
    value = response.headers.get("access-control-allow-origin")
    return value if value is None else str(value)


async def _preflight_status(client: AsyncClient, origin: str, *, request_headers: str) -> int:
    """Send a CORS preflight and return the HTTP status code.

    Starlette's ``CORSMiddleware`` returns ``200`` when every requested
    header is in ``allow_headers`` and ``400`` otherwise. The browser
    treats anything non-2xx as a failed preflight and blocks the actual
    request, so asserting on status is the correct way to verify the
    allow-list shape.
    """
    response = await client.options(
        "/ping",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": request_headers,
        },
    )
    return response.status_code


class TestCorsAllowList:
    """Credentialed CORS trusts only the exact configured origins."""

    async def test_configured_origin_is_allowed(self, cors_client: AsyncClient) -> None:
        """The default ``http://localhost:3000`` origin remains allowed."""
        origin = "http://localhost:3000"
        echoed = await _preflight(cors_client, origin)
        assert echoed == origin

    async def test_foreign_team_preview_is_rejected(self, cors_client: AsyncClient) -> None:
        """The removed foreign-team implant origin is NOT echoed back.

        Regression guard for the stripped ``ngrout70-6776s-projects`` regex:
        a preview under that (foreign) team must no longer be trusted.
        """
        origin = "https://aicrm-abc123-ngrout70-6776s-projects.vercel.app"
        echoed = await _preflight(cors_client, origin)
        assert echoed is None, (
            f"Foreign Vercel team origin {origin} must not be allowed by CORS; "
            f"got Access-Control-Allow-Origin={echoed!r}"
        )

    async def test_arbitrary_vercel_origin_is_rejected(self, cors_client: AsyncClient) -> None:
        """Any ``*.vercel.app`` origin not in the allow-list is rejected."""
        origin = "https://evil-attacker.vercel.app"
        echoed = await _preflight(cors_client, origin)
        assert echoed is None

    async def test_unconfigured_origin_is_rejected(self, cors_client: AsyncClient) -> None:
        """An origin that isn't in ``CORS_ORIGINS`` is rejected outright."""
        origin = "https://not-configured.example.com"
        echoed = await _preflight(cors_client, origin)
        assert echoed is None


class TestCorsAllowedHeaders:
    """The allow-list must be the minimum the frontend actually sends.

    Auth is cookie-based (``access_token`` / ``refresh_token`` httpOnly
    cookies), so ``Authorization`` is no longer expected on cross-origin
    requests to this API. Trimming the allow-list shrinks the surface a
    malicious page can exercise via the browser.
    """

    async def test_content_type_is_allowed(self, cors_client: AsyncClient) -> None:
        """``Content-Type`` is the only request header the frontend sets."""
        origin = "http://localhost:3000"
        status = await _preflight_status(cors_client, origin, request_headers="content-type")
        assert status == 200

    async def test_authorization_is_rejected(self, cors_client: AsyncClient) -> None:
        """Preflights asking for ``Authorization`` fail with 400.

        Regression guard: the previous allow-list included ``Authorization``
        even though no browser code path sends it to this backend (the two
        ``Authorization`` headers in the frontend go directly to
        ``api.openai.com``). Re-adding it without a real need re-opens that
        surface to any compromised origin.
        """
        origin = "http://localhost:3000"
        status = await _preflight_status(cors_client, origin, request_headers="authorization")
        assert status == 400, (
            "Authorization must not be CORS-allowed: the frontend authenticates "
            "via httpOnly cookies and never sends an Authorization header to "
            f"this backend. Got preflight status {status}."
        )

    async def test_x_requested_with_is_rejected(self, cors_client: AsyncClient) -> None:
        """``X-Requested-With`` was in the old list but nothing sends it."""
        origin = "http://localhost:3000"
        status = await _preflight_status(cors_client, origin, request_headers="x-requested-with")
        assert status == 400


class TestProductionAppCorsWiring:
    """Sanity check that the live ``app.main`` app uses the locked-down allow-list."""

    def test_app_uses_exact_allow_list_without_regex(self) -> None:
        """The real app must use ``allow_origins`` (exact list), never a regex."""
        cors_layers = [
            m
            for m in production_app.user_middleware
            if getattr(m.cls, "__name__", None) == CORSMiddleware.__name__
        ]
        assert cors_layers, "Production app must register CORSMiddleware"
        kwargs = cors_layers[0].kwargs

        assert kwargs.get("allow_origin_regex") is None, (
            "Production CORSMiddleware must not use allow_origin_regex with "
            "credentialed CORS; use an exact allow_origins list."
        )
        allow_origins = kwargs.get("allow_origins")
        assert isinstance(allow_origins, list) and allow_origins, (
            "Production CORSMiddleware must use a non-empty allow_origins list"
        )
        # The stripped foreign-team implant must not reappear in any form.
        assert not any("ngrout70" in origin for origin in allow_origins)
        assert not any("vercel.app" in origin for origin in allow_origins if "*" in origin)

    def test_app_allow_headers_is_minimal(self) -> None:
        """The production app must not re-introduce ``Authorization`` etc.

        Auth flows through httpOnly cookies; ``Content-Type`` is the only
        request header the frontend ever sets cross-origin. Re-adding
        ``Authorization``, ``X-Requested-With``, ``Accept``, or ``Origin``
        without a real need widens the CORS surface.
        """
        cors_layers = [
            m
            for m in production_app.user_middleware
            if getattr(m.cls, "__name__", None) == CORSMiddleware.__name__
        ]
        assert cors_layers, "Production app must register CORSMiddleware"
        allow_headers = cors_layers[0].kwargs.get("allow_headers")
        assert allow_headers == ["Content-Type"], (
            "Production CORS allow_headers must be exactly ['Content-Type']; "
            f"got {allow_headers!r}. If you need to add a header, document why "
            "in app/main.py and update this test."
        )
