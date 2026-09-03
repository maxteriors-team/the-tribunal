"""API contract for Permanent Lighting's nested GreenSky settings."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


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
    app.dependency_overrides[get_membership] = lambda: SimpleNamespace(
        role="owner", workspace_id=WS_ID
    )
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


@pytest.fixture
async def auth_client() -> AsyncIterator[AsyncClient]:
    workspace = SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings={})
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app(workspace)),
        base_url="http://testserver",
    ) as client:
        yield client


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/pricing"


def _green_sky(**overrides: object) -> dict[str, object]:
    block: dict[str, object] = {
        "provider": "GreenSky",
        "plan_number": "6124",
        "apr": 0,
        "term_months": 24,
        "merchant_fee_rate": 0.1525,
        "sales_commission_rate": 0.07,
    }
    block.update(overrides)
    return block


async def _put_financing(client: AsyncClient, financing: dict[str, object]):
    permanent = (await client.get(_url())).json()["permanent"]
    permanent["financing"] = financing
    return await client.put(_url(), json={"permanent": permanent})


async def test_defaults_are_green_sky_plan_6124(auth_client: AsyncClient) -> None:
    financing = (await auth_client.get(_url())).json()["permanent"]["financing"]

    assert financing == _green_sky()


async def test_nested_terms_round_trip_without_clobbering_permanent_pricing(
    auth_client: AsyncClient,
) -> None:
    await auth_client.put(_url(), json={"tax": {"enabled": True, "rate": 0.07}})
    before = (await auth_client.get(_url())).json()["permanent"]

    response = await _put_financing(
        auth_client,
        _green_sky(
            plan_number="7000",
            apr=0.055,
            term_months=36,
            merchant_fee_rate=0.14,
            sales_commission_rate=0.08,
        ),
    )

    assert response.status_code == 200
    body = (await auth_client.get(_url())).json()
    assert body["permanent"]["financing"] == _green_sky(
        plan_number="7000",
        apr=0.055,
        term_months=36,
        merchant_fee_rate=0.14,
        sales_commission_rate=0.08,
    )
    assert body["permanent"]["packages"] == before["packages"]
    assert body["permanent"]["easy_markup"] == before["easy_markup"]
    assert body["tax"]["rate"] == 0.07


@pytest.mark.parametrize(
    "override",
    [
        {"plan_number": "not-a-plan"},
        {"term_months": 0},
        {"apr": 1.01},
        {"merchant_fee_rate": 1},
        {"sales_commission_rate": -0.01},
        {"provider": "Another provider"},
    ],
)
async def test_invalid_green_sky_terms_are_rejected(
    auth_client: AsyncClient, override: dict[str, object]
) -> None:
    response = await _put_financing(auth_client, _green_sky(**override))

    assert response.status_code == 422


async def test_legacy_top_level_financing_remains_storable(auth_client: AsyncClient) -> None:
    legacy = {
        "enabled": True,
        "provider": "Legacy provider",
        "max_amount": 25000,
        "terms": [12],
        "default_term": 12,
        "apr": 0,
        "fee_buffer": 0.25,
    }

    response = await auth_client.put(_url(), json={"financing": legacy})

    assert response.status_code == 200
    body = (await auth_client.get(_url())).json()
    assert body["financing"]["provider"] == "Legacy provider"
    assert body["financing"]["fee_buffer"] == 0.25
    assert body["permanent"]["financing"] == _green_sky()
