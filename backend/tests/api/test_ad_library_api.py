"""API tests for the Ad Library endpoints.

Two layers (no real DB):

* **Auth + validation** — every route requires authentication; the search body
  validator rejects a request with no search target.
* **Happy-path mocked** — overrides ``get_db`` / ``get_workspace`` /
  ``get_current_user`` and patches the service so the handlers are exercised
  end-to-end with deterministic fixtures, including workspace-scoped 404s.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import ad_library as ad_library_module
from app.models.lead_discovery_job import DiscoveryJobStatus, DiscoverySourceType
from app.services.ad_intelligence.errors import AdLibraryNotFoundError

WS_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
ADV_ID = uuid.uuid4()
PREFIX = f"/api/v1/workspaces/{WS_ID}/ad-library"


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _mock_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    return ws


def _mock_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.is_active = True
    return user


def _mock_job() -> MagicMock:
    now = datetime.now(UTC)
    job = MagicMock()
    job.id = JOB_ID
    job.workspace_id = WS_ID
    job.mission_id = None
    job.requested_by_id = 1
    job.source_type = DiscoverySourceType.META_AD_LIBRARY
    job.source_label = "roofing"
    job.query = "roofing"
    job.params = {"platform": "meta", "country": "US"}
    job.status = DiscoveryJobStatus.PENDING
    job.requested_count = 25
    job.discovered_count = 0
    job.duplicate_count = 0
    job.invalid_count = 0
    job.started_at = None
    job.completed_at = None
    job.last_error = None
    job.error_count = 0
    job.created_at = now
    job.updated_at = now
    return job


def _make_app(*, with_auth: bool) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    if with_auth:
        db = AsyncMock()

        async def override_get_db() -> AsyncIterator[AsyncMock]:
            yield db

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_workspace] = lambda: _mock_workspace()
        app.dependency_overrides[get_current_user] = lambda: _mock_user()
    app.include_router(
        ad_library_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/ad-library",
    )
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _make_app(with_auth=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(with_auth=False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as ac:
        yield ac


class TestAdLibraryAuth:
    async def test_search_without_auth_401(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.post(
            f"{PREFIX}/search",
            json={"platform": "meta", "country": "US", "search_terms": "x"},
        )
        assert resp.status_code == 401

    async def test_advertisers_without_auth_401(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"{PREFIX}/advertisers")
        assert resp.status_code == 401

    async def test_monitors_without_auth_401(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"{PREFIX}/monitors")
        assert resp.status_code == 401


class TestAdLibraryValidation:
    async def test_search_requires_target(self, client: AsyncClient) -> None:
        # No search_terms / page_id / page_name -> 422 from the model validator.
        resp = await client.post(
            f"{PREFIX}/search", json={"platform": "meta", "country": "US"}
        )
        assert resp.status_code == 422


class TestAdLibraryHappyPath:
    async def test_search_enqueues_job(self, client: AsyncClient) -> None:
        with patch.object(
            ad_library_module.AdLibraryService,
            "create_search_job",
            new=AsyncMock(return_value=_mock_job()),
        ):
            resp = await client.post(
                f"{PREFIX}/search",
                json={"platform": "meta", "country": "US", "search_terms": "roofing"},
            )
        assert resp.status_code == 202
        body = resp.json()
        assert body["id"] == str(JOB_ID)
        assert body["status"] == "pending"

    async def test_get_unknown_job_404(self, client: AsyncClient) -> None:
        with patch.object(
            ad_library_module.AdLibraryService,
            "get_job",
            new=AsyncMock(side_effect=AdLibraryNotFoundError("nope")),
        ):
            resp = await client.get(f"{PREFIX}/jobs/{uuid.uuid4()}")
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "ad_library_not_found"

    async def test_get_unknown_advertiser_404(self, client: AsyncClient) -> None:
        with patch.object(
            ad_library_module.AdLibraryService,
            "get_advertiser_detail",
            new=AsyncMock(side_effect=AdLibraryNotFoundError("nope")),
        ):
            resp = await client.get(f"{PREFIX}/advertisers/{ADV_ID}")
        assert resp.status_code == 404
