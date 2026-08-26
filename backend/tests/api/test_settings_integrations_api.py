"""Settings integrations endpoint contract test.

Verifies that the workspace integrations status list surfaces Follow Up Boss
alongside the other known providers, so it has a durable management surface in
Settings -> Integrations (RF-006). DB-free via dependency overrides.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
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
from app.models.workspace import WorkspaceIntegration
from app.schemas.integration import IntegrationTestResult

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


async def test_integrations_list_includes_quo(auth_client: AsyncClient) -> None:
    resp = await auth_client.get(f"/api/v1/workspaces/{WS_ID}/integrations")
    assert resp.status_code == 200

    by_type = {item["integration_type"]: item for item in resp.json()["integrations"]}
    assert by_type["quo"] == {
        "integration_type": "quo",
        "is_connected": False,
        "display_name": "Quo",
        "description": "Business phone and messaging",
    }


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


async def test_create_quo_validates_and_encrypts_workspace_credentials(
    mock_db: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_key = "quo_api_key_that_must_not_leak"
    organization_id = "OR123"
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    mock_db.add = MagicMock()
    validated_credentials = {"api_key": api_key, "organization_id": organization_id}
    validated = AsyncMock(return_value=validated_credentials)
    provisioned_credentials = {
        **validated_credentials,
        "webhook_id": "12345",
        "webhook_signing_key": "whsec_signing_key",
        "webhook_api_version": "2026-03-30",
    }
    provision = AsyncMock(return_value=provisioned_credentials)
    monkeypatch.setattr(credentials_module, "_validate_quo_credentials", validated)
    monkeypatch.setattr(credentials_module, "_provision_quo_webhook", provision)

    async def refresh(integration: WorkspaceIntegration) -> None:
        now = datetime.now(UTC)
        integration.created_at = now
        integration.updated_at = now

    mock_db.refresh = AsyncMock(side_effect=refresh)

    async with AsyncClient(
        transport=ASGITransport(app=_credentials_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        resp = await ac.post(
            f"/api/v1/workspaces/{WS_ID}/integrations",
            json={
                "integration_type": "quo",
                "credentials": {"api_key": api_key},
                "is_active": True,
            },
        )

    assert resp.status_code == 201
    validated.assert_awaited_once_with({"api_key": api_key})
    integration = mock_db.add.call_args.args[0]
    provision.assert_awaited_once_with(
        validated_credentials,
        integration_id=integration.id,
        expected_organization_id=organization_id,
    )
    assert integration.workspace_id == WS_ID
    assert integration.credentials == provisioned_credentials
    assert api_key not in integration.encrypted_credentials
    assert provisioned_credentials["webhook_signing_key"] not in resp.text
    assert api_key not in resp.text
    assert resp.json()["masked_credentials"]["api_key"] != api_key


async def test_stored_quo_test_is_tenant_scoped_and_persists_returned_organization_id(
    mock_db: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    api_key = "quo_stored_secret"
    integration = WorkspaceIntegration(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        integration_type="quo",
        encrypted_credentials=credentials_module.encrypt_json({"api_key": api_key}),
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=integration))
    )
    run_test = AsyncMock(
        return_value=IntegrationTestResult(
            success=True,
            message="Successfully connected to Quo",
            details={"organization_id": "OR456"},
        )
    )
    monkeypatch.setattr(credentials_module, "_run_integration_test", run_test)

    async with AsyncClient(
        transport=ASGITransport(app=_credentials_app(mock_db)),
        base_url="http://testserver",
    ) as ac:
        resp = await ac.post(f"/api/v1/workspaces/{WS_ID}/integrations/quo/test")

    assert resp.status_code == 200
    assert api_key not in resp.text
    assert integration.credentials == {"api_key": api_key, "organization_id": "OR456"}
    assert api_key not in integration.encrypted_credentials
    mock_db.commit.assert_awaited_once()

    statement = mock_db.execute.await_args.args[0]
    params = statement.compile().params.values()
    assert WS_ID in params
    assert "quo" in params
