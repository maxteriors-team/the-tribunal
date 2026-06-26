"""Tests for POST /contacts/{id}/lead-source (manual attribution from the queue).

Verifies auth, body validation, the not-found mapping, and that a successful
assignment busts the dashboard cache so ROI reflects the correction immediately.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import contacts as contacts_module
from app.services.lead_sources.attribution_service import AttributionCleanupError

WS_ID = uuid.uuid4()
LEAD_SOURCE_ID = uuid.uuid4()
CONTACT_ID = 42


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _mount(app: FastAPI) -> None:
    app.include_router(
        contacts_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/contacts",
    )


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
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
async def client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    """Authenticated client with auth + workspace dependencies overridden."""
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
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=_test_lifespan)
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/contacts/{CONTACT_ID}/lead-source"


class TestAssignAuthAndValidation:
    async def test_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(_url(), json={"lead_source_id": str(LEAD_SOURCE_ID)})
        assert response.status_code == 401

    async def test_missing_lead_source_id_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(_url(), json={})
        assert response.status_code == 422


class TestAssignBehavior:
    async def test_success_returns_204_and_busts_cache(self, client: AsyncClient) -> None:
        with (
            patch.object(
                contacts_module.AttributionCleanupService,
                "assign",
                new=AsyncMock(),
            ) as assign,
            patch.object(
                contacts_module, "invalidate_dashboard_cache", new=AsyncMock()
            ) as invalidate,
        ):
            response = await client.post(
                _url(),
                json={
                    "lead_source_id": str(LEAD_SOURCE_ID),
                    "source_type": "facebook_ads",
                },
            )

        assert response.status_code == 204
        assign.assert_awaited_once()
        assert assign.await_args.kwargs["contact_id"] == CONTACT_ID
        assert assign.await_args.kwargs["lead_source_id"] == LEAD_SOURCE_ID
        invalidate.assert_awaited_once_with(WS_ID)

    async def test_unknown_contact_returns_404_without_cache_bust(
        self, client: AsyncClient
    ) -> None:
        with (
            patch.object(
                contacts_module.AttributionCleanupService,
                "assign",
                new=AsyncMock(side_effect=AttributionCleanupError("Contact not found")),
            ),
            patch.object(
                contacts_module, "invalidate_dashboard_cache", new=AsyncMock()
            ) as invalidate,
        ):
            response = await client.post(_url(), json={"lead_source_id": str(LEAD_SOURCE_ID)})

        assert response.status_code == 404
        # A failed assignment changes nothing, so the cache must be left intact.
        invalidate.assert_not_awaited()
