"""Auth, validation, and routing tests for the field-service job routes.

Offline-mockable style (cf. ``test_lead_sources_api.py``): no real database. The
``JobService`` is replaced with an ``AsyncMock`` so these tests assert the HTTP
contract \u2014 auth gating, role gating, body validation, status codes, and that the
router forwards the right arguments \u2014 rather than service internals (covered by
``tests/services/jobs/test_job_service.py``).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_current_user,
    get_db,
    get_membership,
    get_transactional_db,
    get_workspace,
)
from app.api.v1 import jobs as jobs_module
from app.models.field_service import JobStatus

WS_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
TECH_ID = uuid.uuid4()
CONTACT_ID = 42


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _mount(app: FastAPI) -> None:
    app.include_router(jobs_module.router, prefix="/api/v1/workspaces/{workspace_id}/jobs")


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = 7
    user.is_active = True
    user.email = "dispatcher@example.com"
    return user


def _make_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    return ws


def _make_membership() -> MagicMock:
    membership = MagicMock()
    membership.workspace_id = WS_ID
    membership.user_id = 7
    membership.role = "dispatcher"
    return membership


def _job_response(**overrides: object) -> dict[str, object]:
    """A serialized JobResponse the mocked service returns through the schema."""
    now = datetime.now(UTC)
    base: dict[str, object] = {
        "id": str(JOB_ID),
        "workspace_id": str(WS_ID),
        "contact_id": CONTACT_ID,
        "service_location_id": None,
        "crew_id": None,
        "title": "Fix HVAC",
        "description": None,
        "status": JobStatus.UNSCHEDULED.value,
        "scheduled_start": None,
        "scheduled_end": None,
        "external_source": None,
        "external_id": None,
        "technicians": [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    base.update(overrides)
    return base


@pytest.fixture
def mock_service() -> AsyncMock:
    """A JobService stand-in returning canned responses for every method."""
    service = AsyncMock()
    service.list.return_value = {"items": [_job_response()], "total": 1}
    service.list_for_user.return_value = {"items": [], "total": 0}
    service.get.return_value = _job_response()
    service.create.return_value = _job_response()
    service.update.return_value = _job_response(title="Updated")
    service.schedule.return_value = _job_response(status=JobStatus.SCHEDULED.value)
    service.assign_technicians.return_value = _job_response()
    service.unassign_technician.return_value = _job_response()
    service.delete.return_value = None
    return service


@pytest.fixture
async def client(mock_service: AsyncMock) -> AsyncIterator[AsyncClient]:
    """Authenticated dispatcher client with the service patched out."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_transactional_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: _make_user()
    app.dependency_overrides[get_workspace] = lambda: _make_workspace()
    app.dependency_overrides[get_membership] = lambda: _make_membership()
    _mount(app)

    with patch.object(jobs_module, "JobService", return_value=mock_service):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    """Unauthenticated client: the real auth dependency runs (expects 401)."""
    app = FastAPI(lifespan=_test_lifespan)
    _mount(app)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


def _base(path: str = "") -> str:
    return f"/api/v1/workspaces/{WS_ID}/jobs{path}"


class TestAuth:
    """Every job route requires authentication."""

    async def test_list_requires_auth(self, noauth_client: AsyncClient) -> None:
        assert (await noauth_client.get(_base())).status_code == 401

    async def test_create_requires_auth(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(_base(), json={"contact_id": CONTACT_ID, "title": "X"})
        assert response.status_code == 401

    async def test_calendar_mine_requires_auth(self, noauth_client: AsyncClient) -> None:
        assert (await noauth_client.get(_base("/calendar/mine"))).status_code == 401


class TestListAndGet:
    async def test_list_returns_items(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.get(_base())
        assert response.status_code == 200
        assert response.json()["total"] == 1
        mock_service.list.assert_awaited_once()

    async def test_list_forwards_filters(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        response = await client.get(
            _base(), params={"status": "scheduled", "technician_id": str(TECH_ID)}
        )
        assert response.status_code == 200
        kwargs = mock_service.list.await_args.kwargs
        assert kwargs["status"] == JobStatus.SCHEDULED
        assert kwargs["technician_id"] == TECH_ID

    async def test_get_returns_job(self, client: AsyncClient) -> None:
        response = await client.get(_base(f"/{JOB_ID}"))
        assert response.status_code == 200
        assert response.json()["id"] == str(JOB_ID)

    async def test_calendar_mine_resolves_current_user(
        self, client: AsyncClient, mock_service: AsyncMock
    ) -> None:
        response = await client.get(_base("/calendar/mine"))
        assert response.status_code == 200
        # Router passes the signed-in user's id as the second positional arg.
        assert mock_service.list_for_user.await_args.args[1] == 7


class TestCreateValidation:
    async def test_create_valid(self, client: AsyncClient) -> None:
        response = await client.post(_base(), json={"contact_id": CONTACT_ID, "title": "Fix"})
        assert response.status_code == 201

    async def test_create_missing_title_422(self, client: AsyncClient) -> None:
        response = await client.post(_base(), json={"contact_id": CONTACT_ID})
        assert response.status_code == 422

    async def test_create_half_window_422(self, client: AsyncClient) -> None:
        start = datetime.now(UTC) + timedelta(days=1)
        response = await client.post(
            _base(),
            json={
                "contact_id": CONTACT_ID,
                "title": "Fix",
                "scheduled_start": start.isoformat(),
            },
        )
        assert response.status_code == 422

    async def test_create_end_before_start_422(self, client: AsyncClient) -> None:
        start = datetime.now(UTC) + timedelta(days=1)
        response = await client.post(
            _base(),
            json={
                "contact_id": CONTACT_ID,
                "title": "Fix",
                "scheduled_start": start.isoformat(),
                "scheduled_end": (start - timedelta(hours=1)).isoformat(),
            },
        )
        assert response.status_code == 422


class TestScheduleAndAssign:
    async def test_schedule_valid(self, client: AsyncClient) -> None:
        start = datetime.now(UTC) + timedelta(days=1)
        response = await client.post(
            _base(f"/{JOB_ID}/schedule"),
            json={
                "scheduled_start": start.isoformat(),
                "scheduled_end": (start + timedelta(hours=2)).isoformat(),
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == JobStatus.SCHEDULED.value

    async def test_schedule_end_before_start_422(self, client: AsyncClient) -> None:
        start = datetime.now(UTC) + timedelta(days=1)
        response = await client.post(
            _base(f"/{JOB_ID}/schedule"),
            json={
                "scheduled_start": start.isoformat(),
                "scheduled_end": (start - timedelta(hours=2)).isoformat(),
            },
        )
        assert response.status_code == 422

    async def test_assign_requires_at_least_one(self, client: AsyncClient) -> None:
        response = await client.post(_base(f"/{JOB_ID}/assignments"), json={"technician_ids": []})
        assert response.status_code == 422

    async def test_assign_valid(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.post(
            _base(f"/{JOB_ID}/assignments"), json={"technician_ids": [str(TECH_ID)]}
        )
        assert response.status_code == 200
        assert mock_service.assign_technicians.await_args.args[2] == [TECH_ID]

    async def test_unassign(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.delete(_base(f"/{JOB_ID}/assignments/{TECH_ID}"))
        assert response.status_code == 200
        mock_service.unassign_technician.assert_awaited_once()


class TestUpdateAndDelete:
    async def test_patch_updates(self, client: AsyncClient) -> None:
        response = await client.patch(_base(f"/{JOB_ID}"), json={"title": "Updated"})
        assert response.status_code == 200
        assert response.json()["title"] == "Updated"

    async def test_delete_returns_204(self, client: AsyncClient, mock_service: AsyncMock) -> None:
        response = await client.delete(_base(f"/{JOB_ID}"))
        assert response.status_code == 204
        mock_service.delete.assert_awaited_once()
