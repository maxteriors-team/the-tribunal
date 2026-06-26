"""Auth, validation, and cache-invalidation tests for the lead-source routes.

Covers the manual-spend, attribution-campaign, and unattributed-queue routers
without a real database. Auth-failure paths rely on the real ``get_current_user``
dependency; happy paths override it and patch the module-level ``get_workspace``
(which these routes call directly rather than via ``Depends``) plus the dashboard
cache invalidation hook.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db
from app.api.v1 import lead_sources as lead_sources_module
from app.schemas.lead_source import LeadSourceResponse

WS_ID = uuid.uuid4()
LEAD_SOURCE_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _mount(app: FastAPI) -> None:
    """Mount the three lead-source routers at their production prefixes."""
    app.include_router(
        lead_sources_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/lead-sources",
    )
    app.include_router(
        lead_sources_module.campaigns_router,
        prefix="/api/v1/workspaces/{workspace_id}/lead-source-campaigns",
    )
    app.include_router(
        lead_sources_module.spend_router,
        prefix="/api/v1/workspaces/{workspace_id}/lead-source-spend",
    )


def _make_mock_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.is_active = True
    user.email = "tester@example.com"
    return user


def _make_mock_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    ws.settings = {}
    return ws


@pytest.fixture
def mock_db() -> AsyncMock:
    """AsyncMock DB session that populates server-side fields on refresh."""
    db = AsyncMock()
    db.add = MagicMock()  # AsyncSession.add is synchronous
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    # db.execute(...) returns a sync Result object; model its accessors so the
    # ownership lookup resolves to a truthy lead source without spurious
    # un-awaited-coroutine warnings from AsyncMock's default children.
    result = MagicMock()
    result.scalar_one_or_none.return_value = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=result)

    async def _refresh(obj: object, *args: object, **kwargs: object) -> None:
        # Stand in for DB-assigned defaults so response serialization succeeds.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()  # type: ignore[attr-defined]
        now = datetime.now(UTC)
        obj.created_at = now  # type: ignore[attr-defined]
        obj.updated_at = now  # type: ignore[attr-defined]

    db.refresh = AsyncMock(side_effect=_refresh)
    return db


@pytest.fixture
async def client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    """Authenticated client: get_current_user + get_db overridden."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_current_user() -> MagicMock:
        return _make_mock_user()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    """Unauthenticated client (no overrides): real auth dependency runs."""
    app = FastAPI(lifespan=_test_lifespan)
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


def _valid_spend_body() -> dict[str, object]:
    return {
        "lead_source_id": str(LEAD_SOURCE_ID),
        "spend_starts_on": "2025-01-01",
        "spend_ends_on": "2025-01-31",
        "amount": 1500.5,
        "currency": "usd",
    }


class TestSpendAuth:
    """Auth failures for the manual-spend router."""

    async def test_list_spend_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/lead-source-spend")
        assert response.status_code == 401

    async def test_create_spend_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/lead-source-spend",
            json=_valid_spend_body(),
        )
        assert response.status_code == 401

    async def test_delete_spend_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.delete(
            f"/api/v1/workspaces/{WS_ID}/lead-source-spend/{uuid.uuid4()}"
        )
        assert response.status_code == 401


class TestSpendValidation:
    """Body validation for POST /lead-source-spend (auth bypassed)."""

    async def test_end_before_start_returns_422(self, client: AsyncClient) -> None:
        body = _valid_spend_body()
        body["spend_starts_on"] = "2025-02-01"
        body["spend_ends_on"] = "2025-01-01"
        response = await client.post(f"/api/v1/workspaces/{WS_ID}/lead-source-spend", json=body)
        assert response.status_code == 422

    async def test_negative_amount_returns_422(self, client: AsyncClient) -> None:
        body = _valid_spend_body()
        body["amount"] = -10.0
        response = await client.post(f"/api/v1/workspaces/{WS_ID}/lead-source-spend", json=body)
        assert response.status_code == 422

    async def test_bad_currency_length_returns_422(self, client: AsyncClient) -> None:
        body = _valid_spend_body()
        body["currency"] = "US"
        response = await client.post(f"/api/v1/workspaces/{WS_ID}/lead-source-spend", json=body)
        assert response.status_code == 422

    async def test_missing_lead_source_id_returns_422(self, client: AsyncClient) -> None:
        body = _valid_spend_body()
        del body["lead_source_id"]
        response = await client.post(f"/api/v1/workspaces/{WS_ID}/lead-source-spend", json=body)
        assert response.status_code == 422


class TestSpendCacheInvalidation:
    """Recording or removing spend must bust the dashboard cache."""

    async def test_create_spend_normalizes_currency_and_busts_cache(
        self, client: AsyncClient
    ) -> None:
        with (
            patch.object(lead_sources_module, "get_workspace", new=AsyncMock(return_value=None)),
            patch.object(
                lead_sources_module,
                "invalidate_dashboard_cache",
                new=AsyncMock(),
            ) as invalidate,
        ):
            response = await client.post(
                f"/api/v1/workspaces/{WS_ID}/lead-source-spend",
                json=_valid_spend_body(),
            )

        assert response.status_code == 201
        # Currency normalized to uppercase on the way through the schema.
        assert response.json()["currency"] == "USD"
        invalidate.assert_awaited_once_with(WS_ID)

    async def test_delete_spend_busts_cache(self, client: AsyncClient) -> None:
        with (
            patch.object(lead_sources_module, "get_workspace", new=AsyncMock(return_value=None)),
            patch.object(
                lead_sources_module,
                "invalidate_dashboard_cache",
                new=AsyncMock(),
            ) as invalidate,
        ):
            response = await client.delete(
                f"/api/v1/workspaces/{WS_ID}/lead-source-spend/{uuid.uuid4()}"
            )

        assert response.status_code == 204
        invalidate.assert_awaited_once_with(WS_ID)


def _valid_lead_source_response() -> LeadSourceResponse:
    """A serializable response so PUT tests focus on cache behavior, not I/O."""
    now = datetime.now(UTC)
    return LeadSourceResponse(
        id=LEAD_SOURCE_ID,
        workspace_id=WS_ID,
        name="Test Source",
        public_key="pub_testkey",
        allowed_domains=[],
        enabled=True,
        source_type="google_ads",
        action="create_contact",
        action_config={},
        created_at=now,
        updated_at=now,
        endpoint_url="http://localhost:8000/api/v1/p/leads/pub_testkey",
    )


class TestLeadSourceMutationCacheInvalidation:
    """Lead-source edits that change ROI must bust the dashboard cache."""

    async def test_update_source_type_busts_cache(self, client: AsyncClient) -> None:
        with (
            patch.object(lead_sources_module, "get_workspace", new=AsyncMock(return_value=None)),
            patch.object(
                lead_sources_module, "_to_response", return_value=_valid_lead_source_response()
            ),
            patch.object(
                lead_sources_module, "invalidate_dashboard_cache", new=AsyncMock()
            ) as invalidate,
        ):
            response = await client.put(
                f"/api/v1/workspaces/{WS_ID}/lead-sources/{LEAD_SOURCE_ID}",
                json={"source_type": "google_ads"},
            )

        assert response.status_code == 200
        invalidate.assert_awaited_once_with(WS_ID)

    async def test_update_without_source_type_does_not_bust_cache(
        self, client: AsyncClient
    ) -> None:
        # Renaming a source does not change ROI, so the cache must be left alone.
        with (
            patch.object(lead_sources_module, "get_workspace", new=AsyncMock(return_value=None)),
            patch.object(
                lead_sources_module, "_to_response", return_value=_valid_lead_source_response()
            ),
            patch.object(
                lead_sources_module, "invalidate_dashboard_cache", new=AsyncMock()
            ) as invalidate,
        ):
            response = await client.put(
                f"/api/v1/workspaces/{WS_ID}/lead-sources/{LEAD_SOURCE_ID}",
                json={"name": "Renamed Source"},
            )

        assert response.status_code == 200
        invalidate.assert_not_awaited()

    async def test_delete_lead_source_busts_cache(self, client: AsyncClient) -> None:
        # Deleting a source cascade-deletes its spend entries, changing ROI.
        with (
            patch.object(lead_sources_module, "get_workspace", new=AsyncMock(return_value=None)),
            patch.object(
                lead_sources_module, "invalidate_dashboard_cache", new=AsyncMock()
            ) as invalidate,
        ):
            response = await client.delete(
                f"/api/v1/workspaces/{WS_ID}/lead-sources/{LEAD_SOURCE_ID}"
            )

        assert response.status_code == 204
        invalidate.assert_awaited_once_with(WS_ID)


class TestUnattributedQueueAuth:
    """Auth + validation for GET /lead-sources/unattributed."""

    async def test_unattributed_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/lead-sources/unattributed")
        assert response.status_code == 401

    async def test_unattributed_limit_too_large_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/lead-sources/unattributed?limit=1000"
        )
        assert response.status_code == 422


class TestCampaignAuth:
    """Auth for the attribution-campaign router."""

    async def test_create_campaign_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/lead-source-campaigns",
            json={"lead_source_id": str(LEAD_SOURCE_ID), "name": "Spring Promo"},
        )
        assert response.status_code == 401

    async def test_delete_campaign_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        response = await noauth_client.delete(
            f"/api/v1/workspaces/{WS_ID}/lead-source-campaigns/{uuid.uuid4()}"
        )
        assert response.status_code == 401
