"""Validation contract for the missed-call text-back settings endpoint.

Bad quiet-hours / timezone config used to be accepted silently and then
disable the compliance guard at runtime (a bad clock string makes the parser
return ``None`` -> no quiet hours -> 24/7 texting; an unknown timezone falls
back to UTC -> quiet hours against the wrong wall clock). These now 422 at the
write boundary. DB-free via dependency overrides.
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
BASE = f"/api/v1/workspaces/{WS_ID}/missed-call-textback"


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


def _auth_app(mock_db: AsyncMock) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        ws = MagicMock()
        ws.id = WS_ID
        ws.is_active = True
        ws.settings = {}
        return ws

    async def override_get_current_user() -> MagicMock:
        user = MagicMock()
        user.id = 1
        user.is_active = True
        return user

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


@pytest.mark.parametrize(
    "payload",
    [
        {"quiet_hours_start": "9pm"},
        {"quiet_hours_start": "24:00"},
        {"quiet_hours_end": "12:60"},
        {"timezone": "Mars/Phobos"},
        {"template": "   "},
    ],
)
async def test_invalid_config_rejected(auth_client: AsyncClient, payload: dict[str, str]) -> None:
    resp = await auth_client.put(BASE, json=payload)
    assert resp.status_code == 422, resp.text


async def test_valid_config_accepted(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(
        BASE,
        json={
            "enabled": True,
            "quiet_hours_start": "21:00",
            "quiet_hours_end": "08:00",
            "timezone": "America/New_York",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["quiet_hours_start"] == "21:00"
    assert body["quiet_hours_end"] == "08:00"
    assert body["timezone"] == "America/New_York"


async def test_empty_string_clears_quiet_hours(auth_client: AsyncClient) -> None:
    """A blank clock value normalizes to null rather than 422 (explicit clear)."""
    resp = await auth_client.put(BASE, json={"quiet_hours_start": ""})
    assert resp.status_code == 200, resp.text
    assert resp.json()["quiet_hours_start"] is None
