"""CORS regression tests for customer-hosted public agent embeds."""

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from app.main import PUBLIC_EMBED_PATH_PREFIX, PublicEmbedCORSMiddleware
from app.services.embed.access import EMBED_PARENT_ORIGIN_HEADER

FRONTEND = "https://app.example-crm.com"
CUSTOMER_SITE = "https://customer.example"


def _build_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/p/embed/{public_id}/config")
    async def config(public_id: str) -> dict[str, str]:
        return {"public_id": public_id}

    @app.post("/api/v1/p/embed/{public_id}/chat")
    async def chat(public_id: str) -> dict[str, str]:
        return {"public_id": public_id}

    @app.post("/api/v1/workspaces/{workspace_id}/contacts")
    async def private_route(workspace_id: str) -> dict[str, str]:
        return {"workspace_id": workspace_id}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    app.add_middleware(PublicEmbedCORSMiddleware)
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app()),
        base_url="http://test",
    ) as test_client:
        yield test_client


def _preflight_headers(origin: str) -> dict[str, str]:
    return {
        "Origin": origin,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": EMBED_PARENT_ORIGIN_HEADER,
    }


class TestPublicEmbedPreflight:
    async def test_customer_origin_and_parent_header_pass_preflight(
        self, client: AsyncClient
    ) -> None:
        response = await client.options(
            "/api/v1/p/embed/demo-public-id/config",
            headers=_preflight_headers(CUSTOMER_SITE),
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == CUSTOMER_SITE
        assert (
            EMBED_PARENT_ORIGIN_HEADER.lower()
            in response.headers["access-control-allow-headers"].lower()
        )
        assert "access-control-allow-credentials" not in response.headers

    async def test_private_routes_keep_strict_cors(self, client: AsyncClient) -> None:
        response = await client.options(
            "/api/v1/workspaces/ws1/contacts",
            headers=_preflight_headers(CUSTOMER_SITE),
        )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


class TestPublicEmbedResponses:
    async def test_customer_response_is_readable_without_credentials(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(
            "/api/v1/p/embed/demo-public-id/config",
            headers={
                "Origin": CUSTOMER_SITE,
                EMBED_PARENT_ORIGIN_HEADER: CUSTOMER_SITE,
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == CUSTOMER_SITE
        assert "access-control-allow-credentials" not in response.headers
        assert "origin" in response.headers.get("vary", "").lower()

    async def test_frontend_response_is_also_credentialless(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/p/embed/demo-public-id/config",
            headers={"Origin": FRONTEND, EMBED_PARENT_ORIGIN_HEADER: FRONTEND},
        )

        assert response.headers.get_list("access-control-allow-origin") == [FRONTEND]
        assert "access-control-allow-credentials" not in response.headers

    async def test_no_origin_gets_no_cors_grant(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/p/embed/demo-public-id/config")

        assert "access-control-allow-origin" not in response.headers

    async def test_prefix_constant_matches_router_mount(self) -> None:
        assert PUBLIC_EMBED_PATH_PREFIX == "/api/v1/p/embed/"
