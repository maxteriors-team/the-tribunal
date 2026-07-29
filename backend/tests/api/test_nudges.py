"""Tests for human nudge API endpoints.

Uses the test app pattern with dependency overrides — no real DB.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import nudges as nudges_module
from app.db.pagination import PaginationResult

WS_ID = uuid.uuid4()
NUDGE_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_mock_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    ws.settings = {"nudge_settings": {"enabled": True, "lead_days": 3}}
    return ws


def _make_mock_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.is_active = True
    user.email = "test@example.com"
    return user


def _make_mock_nudge(
    nudge_id: uuid.UUID = NUDGE_ID,
    workspace_id: uuid.UUID = WS_ID,
    status: str = "pending",
    nudge_type: str = "birthday",
) -> MagicMock:
    nudge = MagicMock()
    nudge.id = nudge_id
    nudge.workspace_id = workspace_id
    nudge.contact_id = 1
    nudge.nudge_type = nudge_type
    nudge.title = "🎂 Test birthday"
    nudge.message = "Birthday in 2 days"
    nudge.suggested_action = "send_card"
    nudge.priority = "medium"
    nudge.due_date = datetime.now(UTC) + timedelta(days=2)
    nudge.source_date_field = "birthday"
    nudge.status = status
    nudge.snoozed_until = None
    nudge.delivered_via = None
    nudge.delivered_at = None
    nudge.acted_at = None
    nudge.assigned_to_user_id = None
    nudge.created_at = datetime.now(UTC)

    # Mock contact relationship
    contact = MagicMock()
    contact.full_name = "Alice Smith"
    contact.phone_number = "+15551234567"
    contact.company_name = "Acme Inc"
    nudge.contact = contact

    return nudge


def _make_test_app(mock_db: AsyncMock, mock_workspace: MagicMock, mock_user: MagicMock) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db():
        yield mock_db

    async def override_get_workspace(workspace_id: uuid.UUID = WS_ID):
        return mock_workspace

    async def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user

    app.include_router(
        nudges_module.router,
        prefix=f"/api/v1/workspaces/{WS_ID}/nudges",
    )
    app.include_router(
        nudges_module.settings_router,
        prefix=f"/api/v1/workspaces/{WS_ID}/nudge-settings",
    )

    return app


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def mock_workspace() -> MagicMock:
    return _make_mock_workspace()


@pytest.fixture
def mock_user() -> MagicMock:
    return _make_mock_user()


@pytest.fixture
async def client(
    mock_db: AsyncMock, mock_workspace: MagicMock, mock_user: MagicMock
) -> AsyncIterator[AsyncClient]:
    app = _make_test_app(mock_db, mock_workspace, mock_user)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as ac:
        yield ac


class TestListNudges:
    async def test_list_nudges(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """GET /nudges → 200 with paginated list."""
        nudge = _make_mock_nudge()
        pagination_result = PaginationResult(items=[nudge], total=1, page=1, page_size=20, pages=1)

        with patch("app.api.v1.nudges.paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = pagination_result
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["nudge_type"] == "birthday"

    async def test_list_nudges_filter_status(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """GET /nudges?status=pending → filter applied."""
        pagination_result = PaginationResult(items=[], total=0, page=1, page_size=20, pages=1)

        with patch("app.api.v1.nudges.paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = pagination_result
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges?status=pending")

        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_list_nudges_filter_type(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """GET /nudges?nudge_type=birthday → filter applied."""
        pagination_result = PaginationResult(items=[], total=0, page=1, page_size=20, pages=1)

        with patch("app.api.v1.nudges.paginate", new_callable=AsyncMock) as mock_paginate:
            mock_paginate.return_value = pagination_result
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges?nudge_type=birthday")

        assert response.status_code == 200


class TestGetStats:
    async def test_get_stats(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """GET /nudges/stats → returns counts."""
        mock_result = MagicMock()
        mock_result.all.return_value = [
            ("pending", 5),
            ("sent", 3),
            ("acted", 2),
        ]
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudges/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["pending"] == 5
        assert data["sent"] == 3
        assert data["acted"] == 2
        assert data["dismissed"] == 0
        assert data["total"] == 10


class TestActOnNudge:
    async def test_act_on_nudge(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """PUT /nudges/{id}/act → status=acted."""
        nudge = _make_mock_nudge()

        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = nudge
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/act")

        assert response.status_code == 200
        assert nudge.status == "acted"
        assert nudge.acted_at is not None


class TestDismissNudge:
    async def test_dismiss_nudge(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """PUT /nudges/{id}/dismiss → status=dismissed."""
        nudge = _make_mock_nudge()

        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = nudge
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/dismiss")

        assert response.status_code == 200
        assert nudge.status == "dismissed"


class TestSnoozeNudge:
    async def test_snooze_nudge(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """PUT /nudges/{id}/snooze → status=snoozed."""
        nudge = _make_mock_nudge()
        snooze_time = (datetime.now(UTC) + timedelta(hours=4)).isoformat()

        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = nudge
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudges/{NUDGE_ID}/snooze",
            json={"snooze_until": snooze_time},
        )

        assert response.status_code == 200
        assert nudge.status == "snoozed"


class TestGetNudgeSettings:
    async def test_get_nudge_settings(self, client: AsyncClient, mock_workspace: MagicMock) -> None:
        """GET /nudge-settings → defaults returned."""
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/nudge-settings")

        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is True
        assert data["lead_days"] == 3


class TestUpdateNudgeSettings:
    async def test_update_nudge_settings(
        self, client: AsyncClient, mock_db: AsyncMock, mock_workspace: MagicMock
    ) -> None:
        """PUT /nudge-settings → settings updated."""
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/nudge-settings",
            json={"enabled": False, "lead_days": 7},
        )

        assert response.status_code == 200
        mock_db.commit.assert_awaited_once()


class TestCrossWorkspaceBlocked:
    async def test_cross_workspace_blocked(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        """Nudge from another workspace → 404."""
        other_ws_nudge_id = uuid.uuid4()

        mock_result = MagicMock()
        mock_result.unique.return_value.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        response = await client.put(f"/api/v1/workspaces/{WS_ID}/nudges/{other_ws_nudge_id}/act")

        assert response.status_code == 404
