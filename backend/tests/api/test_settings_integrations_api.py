"""Settings integrations endpoint contract test.

Verifies that the workspace integrations status list surfaces Follow Up Boss
alongside the other known providers, so it has a durable management surface in
Settings -> Integrations (RF-006). DB-free via dependency overrides.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_mock_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    return ws


def _make_mock_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.is_active = True
    return user


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    # get_integrations iterates result.scalars().all(); no rows -> nothing connected.
    scalars = MagicMock()
    scalars.all.return_value = []
    result = MagicMock()
    result.scalars.return_value = scalars
    db.execute = AsyncMock(return_value=result)
    return db


def _auth_app(mock_db: AsyncMock) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return _make_mock_workspace()

    async def override_get_current_user() -> MagicMock:
        return _make_mock_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


@pytest.fixture
async def auth_client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        yield ac


async def test_integrations_list_includes_followupboss(auth_client: AsyncClient) -> None:
    resp = await auth_client.get(f"/api/v1/workspaces/{WS_ID}/integrations")
    assert resp.status_code == 200

    integrations = resp.json()["integrations"]
    by_type = {i["integration_type"]: i for i in integrations}

    assert "followupboss" in by_type, "Follow Up Boss must be a known integration"
    fub = by_type["followupboss"]
    assert fub["display_name"] == "Follow Up Boss"
    assert fub["description"] == "Lead CRM sync"
    assert fub["is_connected"] is False
