"""Who may link a bookable staff row to a login.

``bookable_staff.user_id`` decides *whose* calendar a booking shows up on, so
relinking a staff row is a visibility change, not ordinary agent configuration:
without a gate, any workspace member could point somebody else's staff row at
their own login and read that person's appointments.

The rest of the pool stays membership-gated as before — only the ``user_id``
field carries the extra ``members:manage`` requirement.

Offline-mockable style (cf. ``test_jobs_api.py``): no real database.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import bookable_staff as staff_module

pytestmark = pytest.mark.asyncio

WS_ID = uuid.uuid4()
AGENT_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()
USER_ID = 7

# members:manage is the admin tier — the same gate the Team screen uses.
MAY_LINK = ["owner", "admin"]
MAY_NOT_LINK = ["manager", "dispatcher", "lead_technician", "technician", "sales_rep", "member"]


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _staff_row(user_id: int | None = None) -> MagicMock:
    now = datetime.now(UTC)
    row = MagicMock()
    row.id = STAFF_ID
    row.workspace_id = WS_ID
    row.agent_id = AGENT_ID
    row.name = "Estimator"
    row.email = None
    row.user_id = user_id
    row.calcom_event_type_id = None
    row.skills = []
    row.is_active = True
    row.priority = 0
    row.assignment_count = 0
    row.last_assigned_at = None
    row.created_at = now
    row.updated_at = now
    return row


@asynccontextmanager
async def _client(service: AsyncMock, role: str) -> AsyncIterator[AsyncClient]:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    membership = MagicMock()
    membership.workspace_id = WS_ID
    membership.user_id = USER_ID
    membership.role = role

    user = MagicMock()
    user.id = USER_ID
    user.is_active = True

    workspace = MagicMock()
    workspace.id = WS_ID
    workspace.is_active = True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_workspace] = lambda: workspace
    app.dependency_overrides[get_membership] = lambda: membership
    app.include_router(
        staff_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/agents/{agent_id}/staff",
    )

    with patch.object(staff_module, "BookableStaffService", return_value=service):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            yield ac


def _service() -> AsyncMock:
    service = AsyncMock()
    service.create_staff.return_value = _staff_row()
    service.update_staff.return_value = _staff_row()
    return service


def _base(path: str = "") -> str:
    return f"/api/v1/workspaces/{WS_ID}/agents/{AGENT_ID}/staff{path}"


class TestLinkGate:
    @pytest.mark.parametrize("role", MAY_NOT_LINK)
    async def test_create_with_user_id_refused(self, role: str) -> None:
        service = _service()
        async with _client(service, role) as client:
            response = await client.post(_base(), json={"name": "Estimator", "user_id": USER_ID})
        assert response.status_code == 403
        service.create_staff.assert_not_awaited()

    @pytest.mark.parametrize("role", MAY_NOT_LINK)
    async def test_update_with_user_id_refused(self, role: str) -> None:
        """Including the field at all is the privileged act — even to clear it."""
        service = _service()
        async with _client(service, role) as client:
            response = await client.put(_base(f"/{STAFF_ID}"), json={"user_id": None})
        assert response.status_code == 403
        service.update_staff.assert_not_awaited()

    @pytest.mark.parametrize("role", MAY_LINK)
    async def test_create_with_user_id_allowed_for_admins(self, role: str) -> None:
        service = _service()
        async with _client(service, role) as client:
            response = await client.post(_base(), json={"name": "Estimator", "user_id": USER_ID})
        assert response.status_code == 201
        service.create_staff.assert_awaited_once()

    @pytest.mark.parametrize("role", MAY_LINK)
    async def test_update_with_user_id_allowed_for_admins(self, role: str) -> None:
        service = _service()
        async with _client(service, role) as client:
            response = await client.put(_base(f"/{STAFF_ID}"), json={"user_id": USER_ID})
        assert response.status_code == 200
        service.update_staff.assert_awaited_once()


class TestUnrelatedEditsUnaffected:
    """The gate is on the link only; the rest of the pool keeps working."""

    @pytest.mark.parametrize("role", MAY_NOT_LINK)
    async def test_create_without_user_id_allowed(self, role: str) -> None:
        service = _service()
        async with _client(service, role) as client:
            response = await client.post(_base(), json={"name": "Estimator"})
        assert response.status_code == 201

    @pytest.mark.parametrize("role", MAY_NOT_LINK)
    async def test_update_without_user_id_allowed(self, role: str) -> None:
        service = _service()
        async with _client(service, role) as client:
            response = await client.put(_base(f"/{STAFF_ID}"), json={"priority": 5})
        assert response.status_code == 200


async def test_response_exposes_the_link() -> None:
    """The calendar needs to read the link back to show who is booked."""
    service = _service()
    service.create_staff.return_value = _staff_row(user_id=USER_ID)
    async with _client(service, "owner") as client:
        response = await client.post(_base(), json={"name": "Estimator", "user_id": USER_ID})
    assert response.status_code == 201
    assert response.json()["user_id"] == USER_ID
