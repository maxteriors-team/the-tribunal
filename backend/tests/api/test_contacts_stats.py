"""Tests for the contacts stats endpoint and the new list sort keys.

The endpoint tests exercise route wiring, auth, and response shape without a
real database (the query service is mocked). ``_pct_change`` is tested directly
as a pure function. Ordering against a live database is covered by the
integration test in ``tests/services/test_contact_query_stats.py``.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import contacts as contacts_module
from app.services.contacts.query_service import _pct_change

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_auth_test_app(mock_db: AsyncMock) -> FastAPI:
    """Create a test app with auth + workspace dependencies overridden."""
    app = FastAPI(lifespan=_test_lifespan)

    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True

    user = MagicMock()
    user.id = 1
    user.is_active = True

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return ws

    async def override_get_current_user() -> MagicMock:
        return user

    async def override_get_membership() -> MagicMock:
        membership = MagicMock()
        membership.role = "owner"
        membership.workspace_id = WS_ID
        membership.user_id = user.id
        return membership

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = override_get_membership

    app.include_router(
        contacts_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/contacts",
    )
    return app


def _make_noauth_test_app() -> FastAPI:
    """Create a test app without dependency overrides (auth will fail)."""
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(
        contacts_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/contacts",
    )
    return app


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
async def client(mock_db: AsyncMock) -> AsyncIterator[AsyncClient]:
    app = _make_auth_test_app(mock_db)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    app = _make_noauth_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestPctChange:
    """Unit coverage for the preformatted percentage-change helper."""

    def test_positive_growth(self) -> None:
        assert _pct_change(62, 50) == "+24%"

    def test_negative_change(self) -> None:
        assert _pct_change(45, 50) == "-10%"

    def test_no_change_is_signed_zero(self) -> None:
        assert _pct_change(50, 50) == "+0%"

    def test_prev_zero_curr_positive_is_full_growth(self) -> None:
        assert _pct_change(5, 0) == "+100%"

    def test_both_zero_is_signed_zero(self) -> None:
        assert _pct_change(0, 0) == "+0%"

    def test_rounds_to_nearest_percent(self) -> None:
        # 400% growth mirrors the Jobber "new clients" example (1 -> 5).
        assert _pct_change(5, 1) == "+400%"


class TestContactStatsEndpoint:
    """Route wiring, auth, and response shape for GET /contacts/stats."""

    async def test_stats_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/contacts/stats")
        assert response.status_code == 401

    async def test_stats_returns_200_with_expected_shape(self, client: AsyncClient) -> None:
        stats = {
            "new_leads_30d": 52,
            "new_leads_change": "+24%",
            "new_clients_30d": 5,
            "new_clients_change": "+400%",
            "total_new_clients_ytd": 1618,
        }
        with patch.object(
            contacts_module.ContactQueryService,
            "get_stats",
            new=AsyncMock(return_value=stats),
        ):
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/contacts/stats")

        assert response.status_code == 200
        assert response.json() == stats

    async def test_stats_delegates_to_service_with_workspace(self, client: AsyncClient) -> None:
        get_stats_mock = AsyncMock(
            return_value={
                "new_leads_30d": 0,
                "new_leads_change": "+0%",
                "new_clients_30d": 0,
                "new_clients_change": "+0%",
                "total_new_clients_ytd": 0,
            }
        )
        with patch.object(contacts_module.ContactQueryService, "get_stats", new=get_stats_mock):
            await client.get(f"/api/v1/workspaces/{WS_ID}/contacts/stats")

        get_stats_mock.assert_awaited_once()
        assert get_stats_mock.call_args.kwargs["workspace_id"] == WS_ID


class TestListContactsNewSortKeys:
    """The list route accepts the new sortable-column keys (200, no 422)."""

    @pytest.mark.parametrize(
        "sort_by",
        ["name_asc", "name_desc", "last_activity_asc", "last_activity_desc"],
    )
    async def test_new_sort_key_returns_200(self, client: AsyncClient, sort_by: str) -> None:
        list_mock = AsyncMock(
            return_value={"items": [], "total": 0, "page": 1, "page_size": 50, "pages": 1}
        )
        with patch.object(contacts_module.ContactQueryService, "list_contacts", new=list_mock):
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/contacts?sort_by={sort_by}")

        assert response.status_code == 200
        assert list_mock.call_args.kwargs["sort_by"] == sort_by
