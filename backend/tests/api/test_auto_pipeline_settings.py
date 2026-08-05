"""Contract tests for the auto-pipeline settings endpoints.

Auto-opening a pipeline card for every inbound lead is **off** by default —
raw leads belong in Contacts until someone has contacted them and booked a call
or demo. That makes this endpoint the only way back on, so it is worth pinning:
GET reports the default without any stored setting, PUT/GET round-trips the
flag, the write is namespaced (it must not clobber neighbouring settings), a
corrupt stored blob reads as off instead of 500ing, and an unauthenticated
caller is refused.

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
    return f"/api/v1/workspaces/{WS_ID}/auto-pipeline"


async def test_get_defaults_to_off(auth_client: AsyncClient) -> None:
    """No stored setting means inbound leads stay off the sales board."""
    resp = await auth_client.get(_url())

    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


async def test_put_then_get_round_trips_the_flag(
    auth_client: AsyncClient, workspace: SimpleNamespace
) -> None:
    resp = await auth_client.put(_url(), json={"enabled": True})

    assert resp.status_code == 200
    assert resp.json() == {"enabled": True}
    assert workspace.settings["auto_pipeline"] == {"enabled": True}
    assert (await auth_client.get(_url())).json() == {"enabled": True}

    # And back off again.
    assert (await auth_client.put(_url(), json={"enabled": False})).json() == {"enabled": False}
    assert (await auth_client.get(_url())).json() == {"enabled": False}


async def test_write_is_namespaced_and_keeps_neighbouring_settings() -> None:
    """The flag lives under one key; saving it must not wipe unrelated config."""
    workspace = _make_workspace(
        {"lead_source_capture": {"require_lead_source_on_manual_create": True}}
    )

    async with _client(workspace) as ac:
        resp = await ac.put(_url(), json={"enabled": True})

    assert resp.status_code == 200
    assert workspace.settings["lead_source_capture"] == {
        "require_lead_source_on_manual_create": True
    }
    assert workspace.settings["auto_pipeline"] == {"enabled": True}


async def test_corrupt_blob_reads_as_off_not_a_500() -> None:
    """A hand-edited settings row must not 500 the settings page."""
    workspace = _make_workspace({"auto_pipeline": "yes please"})

    async with _client(workspace) as ac:
        resp = await ac.get(_url())

    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


async def test_non_boolean_payload_rejected(auth_client: AsyncClient) -> None:
    resp = await auth_client.put(_url(), json={"enabled": "sometimes"})
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
        get_resp = await ac.get(_url())
        put_resp = await ac.put(_url(), json={"enabled": True})
    assert get_resp.status_code in (401, 403)
    assert put_resp.status_code in (401, 403)
