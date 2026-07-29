"""Contract tests for the unsold-quote follow-up settings endpoints.

Covers the operator-owned half of the quiet-quote sequence: a PUT/GET
round-trips an edited cadence, a partial update merges instead of clobbering, a
corrupt stored blob still reads as usable (and **disabled**) defaults rather
than 500ing, an impossible cadence is rejected at the edge, and an
unauthenticated caller is refused.

DB-free via dependency overrides + a stateful fake workspace whose ``settings``
dict persists across requests, mirroring
:mod:`tests.api.test_attach_rules_settings_api`.
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


def _make_workspace(settings: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings=settings or {})


def _auth_app(workspace: SimpleNamespace) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    async def override_get_workspace() -> SimpleNamespace:
        return workspace

    async def override_get_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=1, is_active=True, email="op@example.com")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


def _client(workspace: SimpleNamespace) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=_auth_app(workspace)),
        base_url="http://testserver",
    )


@pytest.fixture
def workspace() -> SimpleNamespace:
    return _make_workspace()


@pytest.fixture
async def auth_client(workspace: SimpleNamespace) -> AsyncIterator[AsyncClient]:
    async with _client(workspace) as ac:
        yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/unsold-quotes"


async def test_get_returns_a_described_but_disabled_sequence(auth_client: AsyncClient) -> None:
    """The 30/60/90 plan is pre-written; sending it is an explicit decision."""
    resp = await auth_client.get(_url())

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert [touch["day_offset"] for touch in body["touches"]] == [30, 60, 90]
    assert [touch["hook"] for touch in body["touches"]] == [
        "price_validity",
        "seasonal",
        "financing",
    ]
    assert body["value_threshold"] == 5000.0
    assert body["quiet_hours_start"] == "21:00"


async def test_put_then_get_round_trips_the_cadence(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        _url(),
        json={
            "enabled": True,
            "value_threshold": 12000,
            "touches": [
                {
                    "day_offset": 21,
                    "hook": "seasonal",
                    "template_name": "Spring nudge",
                    "high_value_template_name": "Spring nudge (large job)",
                },
                {"day_offset": 45, "hook": "financing"},
            ],
        },
    )
    assert resp.status_code == 200

    body = (await auth_client.get(_url())).json()
    assert body["enabled"] is True
    assert body["value_threshold"] == 12000
    assert [touch["day_offset"] for touch in body["touches"]] == [21, 45]
    assert body["touches"][0]["template_name"] == "Spring nudge"


async def test_partial_update_merges_without_clobbering(auth_client: AsyncClient) -> None:
    await auth_client.put(
        _url(),
        json={"enabled": True, "touches": [{"day_offset": 14, "hook": "price_validity"}]},
    )
    # Pausing the sequence must not wipe the cadence the operator tuned.
    await auth_client.put(_url(), json={"enabled": False})

    body = (await auth_client.get(_url())).json()
    assert body["enabled"] is False
    assert [touch["day_offset"] for touch in body["touches"]] == [14]


async def test_touches_are_sorted_and_de_duplicated_at_the_edge(
    auth_client: AsyncClient,
) -> None:
    """The worker walks this list in order, so day 90 must never precede day 30."""
    await auth_client.put(
        _url(),
        json={
            "touches": [
                {"day_offset": 90, "hook": "financing"},
                {"day_offset": 30, "hook": "price_validity"},
                {"day_offset": 30, "hook": "seasonal"},
            ]
        },
    )

    body = (await auth_client.get(_url())).json()
    assert [touch["day_offset"] for touch in body["touches"]] == [30, 90]
    assert body["touches"][0]["hook"] == "price_validity"


@pytest.mark.parametrize(
    "payload",
    [
        {"touches": [{"day_offset": 0}]},
        {"touches": [{"day_offset": 30, "hook": "pester"}]},
        {"max_touches": 99},
        {"value_threshold": -5},
        {"quiet_hours_start": "9pm"},
    ],
)
async def test_impossible_config_is_rejected(auth_client: AsyncClient, payload: dict) -> None:
    resp = await auth_client.put(_url(), json=payload)
    assert resp.status_code == 422


async def test_corrupt_blob_reads_as_disabled_defaults_not_a_500() -> None:
    """A hand-edited settings row must not 500 the settings page — or start sending."""
    workspace = _make_workspace({"unsold_quotes": {"touches": "not-a-list", "enabled": "yes"}})

    async with _client(workspace) as ac:
        resp = await ac.get(_url())

    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


async def test_unauthenticated_rejected() -> None:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(settings_module.router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        resp = await ac.get(_url())
    assert resp.status_code in (401, 403)
