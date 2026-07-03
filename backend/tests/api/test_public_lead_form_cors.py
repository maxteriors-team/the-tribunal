"""CORS tests for the public lead-form surface (``/api/v1/p/leads/*``).

Regression coverage for the bug where a browser on a customer domain
(permholidaylights.com) failed the app-wide CORS preflight with 400 before the
per-lead-source ``allowed_domains`` check ever ran — the lead POST was never
sent, and curl-based verification missed it because curl skips preflight.

Uses a minimal app that reproduces main.py's middleware ordering exactly
(strict credentialed ``CORSMiddleware`` inner, ``PublicLeadFormCORSMiddleware``
outer) with stub routes, so the interplay is tested without booting the CRM.
"""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.main import PUBLIC_LEAD_FORM_PATH_PREFIX, PublicLeadFormCORSMiddleware

FRONTEND = "https://app.example-crm.com"
CUSTOMER_SITE = "https://permholidaylights.com"


def _build_app() -> FastAPI:
    """Mirror main.py: strict CORS added first, public lead-form CORS after."""
    app = FastAPI()

    @app.post("/api/v1/p/leads/{public_key}")
    async def submit(public_key: str) -> dict[str, bool]:
        return {"success": True}

    @app.get("/api/v1/p/leads/{public_key}/proof")
    async def proof(public_key: str) -> dict[str, int]:
        return {"median_seconds": 42}

    @app.post("/api/v1/workspaces/{workspace_id}/contacts")
    async def private_route(workspace_id: str) -> dict[str, bool]:
        return {"success": True}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(PublicLeadFormCORSMiddleware)
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=_build_app())
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }


class TestPublicLeadFormPreflight:
    async def test_customer_origin_passes_preflight(self, client: AsyncClient) -> None:
        """The regression: arbitrary customer domains must clear preflight."""
        r = await client.options(
            "/api/v1/p/leads/ls_abc123", headers=_preflight_headers(CUSTOMER_SITE)
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == CUSTOMER_SITE
        assert "content-type" in r.headers["access-control-allow-headers"].lower()
        assert "POST" in r.headers["access-control-allow-methods"]

    async def test_preflight_never_grants_credentials(self, client: AsyncClient) -> None:
        """Reflection must be strictly weaker than the allowlisted policy."""
        r = await client.options(
            "/api/v1/p/leads/ls_abc123", headers=_preflight_headers(CUSTOMER_SITE)
        )
        assert "access-control-allow-credentials" not in r.headers

    async def test_private_routes_still_reject_foreign_origins(self, client: AsyncClient) -> None:
        """The strict app-wide policy must be untouched outside /p/leads/."""
        r = await client.options(
            "/api/v1/workspaces/ws1/contacts", headers=_preflight_headers(CUSTOMER_SITE)
        )
        assert r.status_code == 400
        assert "access-control-allow-origin" not in r.headers


class TestPublicLeadFormResponses:
    async def test_post_response_reflects_customer_origin(self, client: AsyncClient) -> None:
        r = await client.post(
            "/api/v1/p/leads/ls_abc123", headers={"Origin": CUSTOMER_SITE}, json={}
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == CUSTOMER_SITE
        assert "access-control-allow-credentials" not in r.headers
        assert "origin" in r.headers.get("vary", "").lower()

    async def test_proof_get_reflects_customer_origin(self, client: AsyncClient) -> None:
        r = await client.get("/api/v1/p/leads/ls_abc123/proof", headers={"Origin": CUSTOMER_SITE})
        assert r.headers["access-control-allow-origin"] == CUSTOMER_SITE

    async def test_frontend_origin_not_double_stamped(self, client: AsyncClient) -> None:
        """Allowlisted origins keep the inner middleware's credentialed grant."""
        r = await client.post("/api/v1/p/leads/ls_abc123", headers={"Origin": FRONTEND}, json={})
        # Exactly one ACAO header, from the inner CORSMiddleware.
        assert r.headers.get_list("access-control-allow-origin") == [FRONTEND]
        assert r.headers.get("access-control-allow-credentials") == "true"

    async def test_no_origin_header_means_no_cors_headers(self, client: AsyncClient) -> None:
        """curl/server-to-server traffic stays exactly as before."""
        r = await client.post("/api/v1/p/leads/ls_abc123", json={})
        assert "access-control-allow-origin" not in r.headers

    async def test_prefix_constant_matches_the_mounted_route(self) -> None:
        """Guard against the router prefix drifting away from the middleware."""
        assert PUBLIC_LEAD_FORM_PATH_PREFIX == "/api/v1/p/leads/"
