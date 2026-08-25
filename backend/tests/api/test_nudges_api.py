"""Validation and auth tests for the nudges API endpoints.

Complements `test_nudges.py` by focusing on validation failures, auth failures,
and edge-case error paths rather than happy-path flows.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import postgresql

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import nudges as nudges_module

WS_ID = uuid.uuid4()
NUDGE_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
    yield


def _make_mock_workspace() -> MagicMock:
    """Build a mock Workspace."""
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    ws.settings = {"nudge_settings": {"enabled": True, "lead_days": 3}}
    return ws


def _make_mock_user() -> MagicMock:
    """Build a mock active User."""
    user = MagicMock()
    user.id = 1
    user.is_active = True
    user.email = "tester@example.com"
    return user


def _make_auth_test_app(
    mock_db: AsyncMock,
    mock_workspace: MagicMock,
    mock_user: MagicMock,
    *,
    role: str = "owner",
) -> FastAPI:
    """Create test app with auth/workspace/db dependencies overridden."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield mock_db

    async def override_get_workspace() -> MagicMock:
        return mock_workspace

    async def override_get_current_user() -> MagicMock:
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = lambda: MagicMock(role=role, workspace_id=WS_ID)

    app.include_router(
        nudges_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/nudges",
    )
    app.include_router(
        nudges_module.settings_router,
        prefix="/api/v1/workspaces/{workspace_id}/nudge-settings",
    )
    return app


def _make_noauth_test_app() -> FastAPI:
    """Create a test app without dependency overrides (auth fails)."""
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(
        nudges_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/nudges",
    )
    app.include_router(
        nudges_module.settings_router,
        prefix="/api/v1/workspaces/{workspace_id}/nudge-settings",
    )
    return app


@pytest.fixture
def mock_db() -> AsyncMock:
    """Async DB session mock."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_workspace() -> MagicMock:
    """Mock Workspace."""
    return _make_mock_workspace()


@pytest.fixture
def mock_user() -> MagicMock:
    """Mock User."""
    return _make_mock_user()


@pytest.fixture
async def client(
    mock_db: AsyncMock, mock_workspace: MagicMock, mock_user: MagicMock
) -> AsyncIterator[AsyncClient]:
    """Authenticated client (dependency overrides active)."""
    app = _make_auth_test_app(mock_db, mock_workspace, mock_user)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    """Unauthenticated client (no overrides)."""
    app = _make_noauth_test_app()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


def _compiled_sql(statement: object) -> str:
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


class TestNudgeVisibility:
    def test_sales_only_see_their_assigned_nudges(self) -> None:
        sql = _compiled_sql(nudges_module._nudge_visibility(WS_ID, 1, "sales_rep"))

        assert "human_nudges.workspace_id" in sql
        assert "human_nudges.assigned_to_user_id = 1" in sql
        assert "IS NULL" not in sql

    def test_manager_can_also_handle_legacy_global_nudges(self) -> None:
        sql = _compiled_sql(nudges_module._nudge_visibility(WS_ID, 1, "manager"))

        assert "human_nudges.assigned_to_user_id = 1" in sql
        assert "human_nudges.assigned_to_user_id IS NULL" in sql


class TestListNudgesAuth:
    """Auth and pagination validation for GET /nudges."""

    async def test_list_nudges_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """GET /nudges without auth returns 401."""
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/nudges")
        assert response.status_code == 401

    async def test_list_nudges_invalid_page_returns_422(self, client: AsyncClient) -> None:
        """GET /nudges with page=0 (violates ge=1) returns 422."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges?page=0")
        assert response.status_code == 422

    async def test_list_nudges_page_size_over_limit_returns_422(self, client: AsyncClient) -> None:
        """GET /nudges with page_size=101 (violates le=100) returns 422."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges?page_size=101")
        assert response.status_code == 422

    async def test_list_nudges_negative_page_returns_422(self, client: AsyncClient) -> None:
        """GET /nudges with page=-1 returns 422."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges?page=-1")
        assert response.status_code == 422


class TestGetStatsAuth:
    """Auth for GET /nudges/stats."""

    async def test_get_stats_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """GET /nudges/stats without auth returns 401."""
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/nudges/stats")
        assert response.status_code == 401


class TestClearAllNudges:
    async def test_clear_all_is_one_scoped_active_status_update(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = [uuid.uuid4(), uuid.uuid4()]
        mock_db.execute = AsyncMock(return_value=result)

        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/clear-all")

        assert response.status_code == 200
        assert response.json() == {"dismissed_count": 2}
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()
        sql = _compiled_sql(mock_db.execute.await_args.args[0])
        assert sql.startswith("UPDATE human_nudges")
        assert "human_nudges.workspace_id" in sql
        assert "human_nudges.assigned_to_user_id = 1" in sql
        assert "human_nudges.assigned_to_user_id IS NULL" in sql
        assert "pending" in sql and "sent" in sql and "snoozed" in sql
        assert "RETURNING human_nudges.id" in sql

    async def test_sales_clear_all_excludes_global_nudges(
        self, mock_db: AsyncMock, mock_workspace: MagicMock, mock_user: MagicMock
    ) -> None:
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=result)
        app = _make_auth_test_app(mock_db, mock_workspace, mock_user, role="sales_rep")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/clear-all")

        assert response.status_code == 200
        sql = _compiled_sql(mock_db.execute.await_args.args[0])
        assert "human_nudges.assigned_to_user_id = 1" in sql
        assert "IS NULL" not in sql


class TestActOnNudgeValidation:
    """Validation for PUT /nudges/{id}/act."""

    async def test_act_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """PUT /nudges/{id}/act without auth returns 401."""
        response = await noauth_client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/act")
        assert response.status_code == 401

    async def test_act_invalid_nudge_uuid_returns_422(self, client: AsyncClient) -> None:
        """PUT /nudges/{id}/act with non-UUID nudge_id returns 422."""
        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/not-a-uuid/act")
        assert response.status_code == 422

    async def test_act_missing_nudge_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        """PUT /nudges/{id}/act with unknown nudge returns 404."""
        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{uuid.uuid4()}/act")
        assert response.status_code == 404


class TestDismissNudgeValidation:
    """Validation for PUT /nudges/{id}/dismiss."""

    async def test_dismiss_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """PUT /nudges/{id}/dismiss without auth returns 401."""
        response = await noauth_client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/dismiss")
        assert response.status_code == 401

    async def test_dismiss_invalid_uuid_returns_422(self, client: AsyncClient) -> None:
        """PUT /nudges/{id}/dismiss with non-UUID returns 422."""
        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/abc/dismiss")
        assert response.status_code == 422

    async def test_dismiss_nonexistent_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        """Another user's nudge is invisible and therefore returns 404."""
        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{uuid.uuid4()}/dismiss")

        assert response.status_code == 404
        sql = _compiled_sql(mock_db.execute.await_args.args[0])
        assert "human_nudges.workspace_id" in sql
        assert "human_nudges.assigned_to_user_id = 1" in sql


class TestSnoozeNudgeValidation:
    """Validation for PUT /nudges/{id}/snooze."""

    async def test_snooze_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """PUT /nudges/{id}/snooze without auth returns 401."""
        response = await noauth_client.put(
            f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/snooze",
            json={"snooze_until": datetime.now(UTC).isoformat()},
        )
        assert response.status_code == 401

    async def test_snooze_missing_body_returns_422(self, client: AsyncClient) -> None:
        """PUT /nudges/{id}/snooze without body returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/snooze",
        )
        assert response.status_code == 422

    async def test_snooze_missing_snooze_until_returns_422(self, client: AsyncClient) -> None:
        """PUT /nudges/{id}/snooze without snooze_until field returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/snooze",
            json={},
        )
        assert response.status_code == 422

    async def test_snooze_invalid_datetime_returns_422(self, client: AsyncClient) -> None:
        """PUT /nudges/{id}/snooze with invalid datetime returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/snooze",
            json={"snooze_until": "not-a-datetime"},
        )
        assert response.status_code == 422

    async def test_snooze_nonexistent_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        """PUT /nudges/{id}/snooze with unknown id returns 404."""
        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        snooze_until = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudges/{uuid.uuid4()}/snooze",
            json={"snooze_until": snooze_until},
        )
        assert response.status_code == 404


class TestNudgeSettingsAuth:
    """Auth + validation for /nudge-settings endpoints."""

    async def test_get_settings_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        """GET /nudge-settings without auth returns 401."""
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/nudge-settings")
        assert response.status_code == 401

    async def test_update_settings_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        """PUT /nudge-settings without auth returns 401."""
        response = await noauth_client.put(
            f"/api/v1/workspaces/{WS_ID}/nudge-settings",
            json={"enabled": False},
        )
        assert response.status_code == 401

    async def test_update_settings_lead_days_out_of_range_returns_422(
        self, client: AsyncClient
    ) -> None:
        """PUT /nudge-settings with lead_days=0 (violates ge=1) returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudge-settings",
            json={"lead_days": 0},
        )
        assert response.status_code == 422

    async def test_update_settings_lead_days_too_high_returns_422(
        self, client: AsyncClient
    ) -> None:
        """PUT /nudge-settings with lead_days=31 (violates le=30) returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudge-settings",
            json={"lead_days": 31},
        )
        assert response.status_code == 422

    async def test_update_settings_cooling_days_too_low_returns_422(
        self, client: AsyncClient
    ) -> None:
        """PUT /nudge-settings with cooling_days=6 (violates ge=7) returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudge-settings",
            json={"cooling_days": 6},
        )
        assert response.status_code == 422

    async def test_update_settings_cooling_days_too_high_returns_422(
        self, client: AsyncClient
    ) -> None:
        """PUT /nudge-settings with cooling_days=400 (violates le=365) returns 422."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudge-settings",
            json={"cooling_days": 400},
        )
        assert response.status_code == 422


class TestInvalidWorkspaceId:
    """Validate workspace_id path parameter is UUID (via real dependency)."""

    async def test_invalid_workspace_uuid_rejected(self, noauth_client: AsyncClient) -> None:
        """Non-UUID workspace_id is rejected (401 from auth or 422 from path).

        FastAPI runs dependencies in declaration order; the OAuth2 scheme may
        raise 401 before `get_workspace` validates the UUID. Either outcome
        is acceptable — the request never reaches the handler.
        """
        response = await noauth_client.get("/api/v1/workspaces/not-a-uuid/nudges")
        assert response.status_code in (401, 422)
