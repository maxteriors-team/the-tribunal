"""Settings integration catalog and credential-test contracts."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_current_user,
    get_db,
    get_membership,
    get_workspace,
    get_workspace_admin,
)
from app.api.v1 import settings as settings_module
from app.api.v1.integrations import credentials as credentials_module

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
    app.dependency_overrides[get_membership] = lambda: SimpleNamespace(
        role="owner", workspace_id=WS_ID
    )
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


@pytest.fixture
async def auth_client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        yield ac


async def test_integrations_list_excludes_followupboss(auth_client: AsyncClient) -> None:
    """FUB was removed from the catalog — a home-service CRM has no realtor lead sync."""
    resp = await auth_client.get(f"/api/v1/workspaces/{WS_ID}/integrations")
    assert resp.status_code == 200

    integrations = resp.json()["integrations"]
    by_type = {i["integration_type"]: i for i in integrations}

    assert "followupboss" not in by_type


async def test_integrations_list_excludes_quo(auth_client: AsyncClient) -> None:
    resp = await auth_client.get(f"/api/v1/workspaces/{WS_ID}/integrations")
    assert resp.status_code == 200

    integration_types = {item["integration_type"] for item in resp.json()["integrations"]}
    assert "quo" not in integration_types


def _credentials_app(mock_db: AsyncMock) -> FastAPI:
    """Mount the integrations credentials router with overridden auth/db deps."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return _make_mock_workspace()

    async def override_get_current_user() -> MagicMock:
        return _make_mock_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_workspace_admin] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = lambda: MagicMock(role="owner", workspace_id=WS_ID)
    app.include_router(
        credentials_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/integrations",
    )
    return app


class _FakeAsyncClient:
    """Minimal httpx.AsyncClient stand-in returning a canned response."""

    def __init__(self, status_code: int, payload: dict) -> None:
        self._status_code = status_code
        self._payload = payload

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, *args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=self._status_code,
            json=lambda: self._payload,
        )


async def test_test_integration_validates_candidate_key_without_stored_row(
    mock_db: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pasted key is validated before saving: no stored row -> provider error, not 404."""
    # No stored integration row exists for this workspace.
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    # Telnyx rejects the bad key with 401; the test must surface that, not 404.
    monkeypatch.setattr(
        credentials_module.httpx,
        "AsyncClient",
        lambda *a, **k: _FakeAsyncClient(401, {}),
    )

    async with AsyncClient(
        transport=ASGITransport(app=_credentials_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{WS_ID}/integrations/telnyx/test",
            json={"credentials": {"api_key": "KEY_invalid"}},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "401" in body["message"]


async def test_test_integration_without_body_requires_stored_row(
    mock_db: AsyncMock,
) -> None:
    """Without candidate credentials and no stored row, the endpoint still 404s."""
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )

    async with AsyncClient(
        transport=ASGITransport(app=_credentials_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{WS_ID}/integrations/telnyx/test",
        )

    assert resp.status_code == 404


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "quo", None),
        ("PUT", "quo", {}),
        ("DELETE", "quo", None),
        ("POST", "quo/test", {"credentials": {"api_key": "retired"}}),
    ],
)
async def test_retired_quo_credential_routes_return_not_found(
    mock_db: AsyncMock,
    method: str,
    suffix: str,
    body: dict[str, object] | None,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_credentials_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        resp = await ac.request(
            method,
            f"/api/v1/workspaces/{WS_ID}/integrations/{suffix}",
            json=body,
        )

    assert resp.status_code == 404
    assert resp.json() == {"detail": "Integration 'quo' not found"}
    mock_db.execute.assert_not_awaited()


async def test_retired_quo_credentials_cannot_be_created(mock_db: AsyncMock) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_credentials_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{WS_ID}/integrations",
            json={
                "integration_type": "quo",
                "credentials": {"api_key": "retired"},
                "is_active": True,
            },
        )

    assert resp.status_code == 422
    mock_db.execute.assert_not_awaited()
