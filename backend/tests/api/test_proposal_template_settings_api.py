"""Contract tests for the proposal-template settings endpoints.

Covers the self-serve extensibility layer that lets an operator restyle client
proposals without a code change: a PUT/GET round-trips edited branding + terms,
a partial update merges (never clobbers other keys), a bad color is rejected at
the edge, and an unauthenticated caller is rejected. DB-free via dependency
overrides + a stateful fake workspace whose ``settings`` dict persists across
requests.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_workspace() -> SimpleNamespace:
    # A real dict for ``settings`` so the merge logic actually mutates + persists
    # across requests (refresh is a no-op under the mocked db).
    return SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings={})


def _make_user() -> SimpleNamespace:
    return SimpleNamespace(id=1, is_active=True, email="op@example.com")


def _auth_app(workspace: SimpleNamespace) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    async def override_get_workspace() -> SimpleNamespace:
        return workspace

    async def override_get_current_user() -> SimpleNamespace:
        return _make_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


@pytest.fixture
def workspace() -> SimpleNamespace:
    return _make_workspace()


@pytest.fixture
async def auth_client(workspace: SimpleNamespace) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app(workspace)),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/proposal-template"


async def test_get_returns_defaults_with_business_name_fallback(
    auth_client: AsyncClient,
) -> None:
    resp = await auth_client.get(_url())
    assert resp.status_code == 200
    body = resp.json()
    # business_name falls back to the workspace name when unset.
    assert body["business_name"] == "Maxteriors"
    assert body["brand_color"] == "#0F172A"
    assert body["accent_color"] == "#2563EB"


async def test_put_then_get_round_trips_edits(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        _url(),
        json={
            "business_name": "Maxteriors Lighting",
            "brand_color": "#123abc",
            "default_terms": "50% deposit due on approval.",
        },
    )
    assert resp.status_code == 200

    got = await auth_client.get(_url())
    body = got.json()
    assert body["business_name"] == "Maxteriors Lighting"
    assert body["brand_color"] == "#123abc"
    assert body["default_terms"] == "50% deposit due on approval."


async def test_partial_update_merges_without_clobbering(
    auth_client: AsyncClient,
) -> None:
    await auth_client.put(
        _url(),
        json={"brand_color": "#111111", "business_phone": "+1 555 0100"},
    )
    # A second update touching only the footer must not wipe the earlier keys.
    await auth_client.put(_url(), json={"footer": "Licensed & insured."})

    body = (await auth_client.get(_url())).json()
    assert body["brand_color"] == "#111111"
    assert body["business_phone"] == "+1 555 0100"
    assert body["footer"] == "Licensed & insured."


async def test_invalid_color_rejected(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(_url(), json={"brand_color": "not-a-color"})
    assert resp.status_code == 422


async def test_unauthenticated_rejected() -> None:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    # Only the db is overridden; the real auth dependencies run and reject the
    # tokenless request before any workspace lookup.
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(settings_module.router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        resp = await ac.get(_url())
    assert resp.status_code in (401, 403)
