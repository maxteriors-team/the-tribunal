"""Bistro pricing inventory mappings stay active, local, and behavior-safe."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _payload(**overrides: object) -> dict[str, object]:
    bistro: dict[str, object] = {
        "enabled": True,
        "minimum": 500,
        "temporary": {
            "label": "Temporary Bistro Lighting",
            "lights_per_ft": 10,
            "poles_per_ft": 4,
            "lights_inventory_sku": "BISTRO-TEMP-200FT",
            "poles_inventory_sku": "BISTRO-TEMP-POLE",
            "stock_feet_per_light_unit": 200,
        },
        "permanent": {
            "label": "Permanent Bistro Lighting",
            "lights_per_ft": 20,
            "poles_per_ft": 6,
            "lights_inventory_sku": "BISTRO-PERM-FT",
            "poles_inventory_sku": "BISTRO-PERM-POLE",
            "stock_feet_per_light_unit": 1,
        },
    }
    bistro.update(overrides)
    return {"bistro": bistro}


@pytest.fixture
async def client() -> AsyncIterator[tuple[AsyncClient, AsyncMock, SimpleNamespace]]:
    workspace = SimpleNamespace(id=WS_ID, name="Bistro", is_active=True, settings={})
    db = AsyncMock()
    app = FastAPI(lifespan=_lifespan)

    async def override_db() -> AsyncIterator[AsyncMock]:
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_workspace] = lambda: workspace
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1, is_active=True, email="owner@example.com"
    )
    app.dependency_overrides[get_membership] = lambda: SimpleNamespace(
        role="owner", workspace_id=WS_ID
    )
    app.include_router(settings_module.router, prefix="/api/v1")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http:
        yield http, db, workspace


def _active_skus(db: AsyncMock, *skus: str) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = list(skus)
    db.execute.return_value = result


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/pricing"


async def test_active_workspace_skus_round_trip(
    client: tuple[AsyncClient, AsyncMock, SimpleNamespace],
) -> None:
    http, db, workspace = client
    _active_skus(
        db,
        "BISTRO-TEMP-200FT",
        "BISTRO-TEMP-POLE",
        "BISTRO-PERM-FT",
        "BISTRO-PERM-POLE",
    )

    response = await http.put(_url(), json=_payload())

    assert response.status_code == 200
    assert response.json()["bistro"]["temporary"]["stock_feet_per_light_unit"] == 200
    assert (
        workspace.settings["pricing"]["bistro"]["permanent"]["lights_inventory_sku"]
        == "BISTRO-PERM-FT"
    )


async def test_missing_or_cross_workspace_sku_fails_without_writing(
    client: tuple[AsyncClient, AsyncMock, SimpleNamespace],
) -> None:
    http, db, workspace = client
    _active_skus(db, "BISTRO-TEMP-200FT")

    response = await http.put(_url(), json=_payload())

    assert response.status_code == 422
    assert "BISTRO-PERM-FT" in response.json()["detail"]["missing_skus"]
    assert workspace.settings == {}
    db.commit.assert_not_awaited()


async def test_same_sku_cannot_be_consumable_and_reusable(
    client: tuple[AsyncClient, AsyncMock, SimpleNamespace],
) -> None:
    http, db, workspace = client
    payload = _payload()
    payload["bistro"]["temporary"]["lights_inventory_sku"] = " SHARED-BISTRO "  # type: ignore[index]
    payload["bistro"]["permanent"]["lights_inventory_sku"] = "SHARED-BISTRO"  # type: ignore[index]

    response = await http.put(_url(), json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]["conflicting_skus"] == ["SHARED-BISTRO"]
    assert workspace.settings == {}
    db.execute.assert_not_awaited()
