"""Which tier gets a scoped calendar, on both job and appointment reads.

The calendar shows jobs and appointments on one surface, so both routes must
draw the same line: ``jobs:write`` (owner / admin / manager / dispatcher) runs
the board and reads all of it; everyone below is confined server-side to the
entries they are on.

Offline-mockable style (cf. ``test_jobs_api.py``): no real database. The service
layer is replaced with an ``AsyncMock`` so these tests assert *what the route
asks the service for* — the ``visible_to_user_id`` it forwards per role — while
``tests/services/test_calendar_visibility.py`` proves the predicate itself
against a real database.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import appointments as appointments_module
from app.api.v1 import jobs as jobs_module
from app.models.field_service import JobStatus

pytestmark = pytest.mark.asyncio

WS_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
APPOINTMENT_ID = 99
USER_ID = 7

# The dispatch line: everyone here holds jobs:write and reads the whole board.
PRIVILEGED_ROLES = ["owner", "admin", "manager", "dispatcher"]
# Everyone below it sees only their own entries.
SCOPED_ROLES = ["member", "lead_technician", "technician", "sales_rep"]


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_user() -> MagicMock:
    user = MagicMock()
    user.id = USER_ID
    user.is_active = True
    user.email = "worker@example.com"
    return user


def _make_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    return ws


def _make_membership(role: str) -> MagicMock:
    membership = MagicMock()
    membership.workspace_id = WS_ID
    membership.user_id = USER_ID
    membership.role = role
    return membership


def _job_response() -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": str(JOB_ID),
        "workspace_id": str(WS_ID),
        "contact_id": 42,
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


def _appointment_response() -> dict[str, object]:
    """A serialized AppointmentResponse the mocked service returns."""
    now = datetime.now(UTC)
    return {
        "id": APPOINTMENT_ID,
        "workspace_id": str(WS_ID),
        "contact_id": 42,
        "contact": None,
        "agent_id": None,
        "message_id": None,
        "campaign_id": None,
        "business_location_id": None,
        "scheduled_at": now.isoformat(),
        "duration_minutes": 30,
        "status": "scheduled",
        "service_type": "Estimate",
        "notes": None,
        "google_calendar_event_id": None,
        "google_calendar_event_url": None,
        "sync_status": "pending",
        "last_synced_at": None,
        "sync_error": None,
        "reminder_sent_at": None,
        "reminders_sent": [],
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }


@asynccontextmanager
async def _client(module, service: AsyncMock, role: str, prefix: str) -> AsyncIterator[AsyncClient]:
    """A client authenticated as ``role`` with the route's service patched out."""
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_workspace] = _make_workspace
    app.dependency_overrides[get_membership] = lambda: _make_membership(role)
    app.include_router(module.router, prefix=prefix)

    service_name = "JobService" if module is jobs_module else "AppointmentService"
    with ExitStack() as stack:
        stack.enter_context(patch.object(module, service_name, return_value=service))
        if module is appointments_module:
            stack.enter_context(
                patch.object(module, "enforce_appointment_reminder_rate_limit", AsyncMock())
            )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as ac:
            yield ac


def _job_service() -> AsyncMock:
    service = AsyncMock()
    service.list.return_value = {"items": [_job_response()], "total": 1}
    service.get.return_value = _job_response()
    return service


def _appointment_service() -> AsyncMock:
    service = AsyncMock()
    service.create_appointment.return_value = _appointment_response()
    service.list_appointments.return_value = {
        "items": [_appointment_response()],
        "total": 1,
        "page": 1,
        "page_size": 50,
        "pages": 1,
    }
    service.get_appointment.return_value = _appointment_response()
    service.update_appointment.return_value = _appointment_response()
    service.send_reminder.return_value = {"success": True, "message": "sent"}
    service.get_stats.return_value = {
        "overall": {
            "total": 0,
            "scheduled": 0,
            "completed": 0,
            "no_show": 0,
            "cancelled": 0,
            "show_up_rate": 0.0,
        },
        "by_agent": [],
        "by_campaign": [],
    }
    return service


JOBS_PREFIX = "/api/v1/workspaces/{workspace_id}/jobs"
APPOINTMENTS_PREFIX = "/api/v1/workspaces/{workspace_id}/appointments"


class TestJobReadScope:
    @pytest.mark.parametrize("role", SCOPED_ROLES)
    async def test_list_is_scoped_to_caller(self, role: str) -> None:
        """Below the dispatch line, the list is confined to the caller's jobs."""
        service = _job_service()
        async with _client(jobs_module, service, role, JOBS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/jobs")
        assert response.status_code == 200
        assert service.list.await_args.kwargs["visible_to_user_id"] == USER_ID

    @pytest.mark.parametrize("role", PRIVILEGED_ROLES)
    async def test_list_is_unscoped_for_dispatch(self, role: str) -> None:
        """Dispatch and above read the whole board."""
        service = _job_service()
        async with _client(jobs_module, service, role, JOBS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/jobs")
        assert response.status_code == 200
        assert service.list.await_args.kwargs["visible_to_user_id"] is None

    async def test_unknown_role_fails_closed(self) -> None:
        """An unrecognised role gets the field tier, not the whole board."""
        service = _job_service()
        async with _client(jobs_module, service, "some_future_role", JOBS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/jobs")
        assert response.status_code == 200
        assert service.list.await_args.kwargs["visible_to_user_id"] == USER_ID

    async def test_scoped_filters_still_forwarded(self) -> None:
        """Scoping does not swallow the caller's filters."""
        service = _job_service()
        async with _client(jobs_module, service, "technician", JOBS_PREFIX) as client:
            response = await client.get(
                f"/api/v1/workspaces/{WS_ID}/jobs", params={"status": "scheduled"}
            )
        assert response.status_code == 200
        kwargs = service.list.await_args.kwargs
        assert kwargs["status"] == JobStatus.SCHEDULED
        assert kwargs["visible_to_user_id"] == USER_ID

    async def test_stats_carries_the_scope(self) -> None:
        service = _appointment_service()
        async with _client(
            appointments_module, service, "sales_rep", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/appointments/stats")
        assert response.status_code == 200
        assert service.get_stats.await_args.kwargs["visible_to_user_id"] == USER_ID

    async def test_deep_link_carries_the_scope(self) -> None:
        """``GET /jobs/{id}`` cannot be used to bypass the list filter."""
        service = _job_service()
        async with _client(jobs_module, service, "technician", JOBS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/jobs/{JOB_ID}")
        assert response.status_code == 200
        assert service.get.await_args.kwargs["visible_to_user_id"] == USER_ID

    async def test_deep_link_unscoped_for_dispatch(self) -> None:
        service = _job_service()
        async with _client(jobs_module, service, "dispatcher", JOBS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/jobs/{JOB_ID}")
        assert response.status_code == 200
        assert service.get.await_args.kwargs["visible_to_user_id"] is None


class TestAppointmentCreateScope:
    async def test_restricted_create_assigns_to_the_caller(self) -> None:
        """A technician's new appointment remains visible on their own calendar."""
        service = _appointment_service()
        async with _client(
            appointments_module, service, "technician", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.post(
                f"/api/v1/workspaces/{WS_ID}/appointments",
                json={
                    "contact_id": 42,
                    "scheduled_at": datetime.now(UTC).isoformat(),
                    "duration_minutes": 30,
                },
            )
        assert response.status_code == 201
        assert response.status_code == 201
        assert service.create_appointment.await_args.kwargs["booked_for_user_id"] == USER_ID

    async def test_restricted_create_cannot_choose_another_calendar_user(self) -> None:
        service = _appointment_service()
        async with _client(
            appointments_module, service, "technician", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.post(
                f"/api/v1/workspaces/{WS_ID}/appointments",
                json={
                    "contact_id": 42,
                    "scheduled_at": datetime.now(UTC).isoformat(),
                    "duration_minutes": 30,
                    "bookable_staff_id": str(uuid.uuid4()),
                },
            )

        assert response.status_code == 403
        service.create_appointment.assert_not_awaited()
    async def test_dispatch_create_stays_unassigned(self) -> None:
        """Dispatch can still create a board appointment for later routing."""
        service = _appointment_service()
        async with _client(
            appointments_module, service, "dispatcher", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.post(
                f"/api/v1/workspaces/{WS_ID}/appointments",
                json={
                    "contact_id": 42,
                    "scheduled_at": datetime.now(UTC).isoformat(),
                    "duration_minutes": 30,
                },
            )
        assert response.status_code == 201
        assert service.create_appointment.await_args.kwargs["booked_for_user_id"] is None

    async def test_dispatch_create_forwards_the_tagged_calendar_user(self) -> None:
        service = _appointment_service()
        staff_id = uuid.uuid4()
        async with _client(
            appointments_module, service, "dispatcher", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.post(
                f"/api/v1/workspaces/{WS_ID}/appointments",
                json={
                    "contact_id": 42,
                    "scheduled_at": datetime.now(UTC).isoformat(),
                    "duration_minutes": 30,
                    "bookable_staff_id": str(staff_id),
                },
            )

        assert response.status_code == 201
        request = service.create_appointment.await_args.args[1]
        assert request.bookable_staff_id == staff_id
        assert service.create_appointment.await_args.kwargs["booked_for_user_id"] is None


class TestAppointmentReadScope:
    @pytest.mark.parametrize("role", SCOPED_ROLES)
    async def test_list_is_scoped_to_caller(self, role: str) -> None:
        service = _appointment_service()
        async with _client(appointments_module, service, role, APPOINTMENTS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/appointments")
        assert response.status_code == 200
        assert service.list_appointments.await_args.kwargs["visible_to_user_id"] == USER_ID

    @pytest.mark.parametrize("role", PRIVILEGED_ROLES)
    async def test_list_is_unscoped_for_dispatch(self, role: str) -> None:
        service = _appointment_service()
        async with _client(appointments_module, service, role, APPOINTMENTS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/appointments")
        assert response.status_code == 200
        assert service.list_appointments.await_args.kwargs["visible_to_user_id"] is None

    async def test_deep_link_carries_the_scope(self) -> None:
        service = _appointment_service()
        async with _client(
            appointments_module, service, "technician", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/appointments/{APPOINTMENT_ID}")
        assert response.status_code == 200
        assert service.get_appointment.await_args.kwargs["visible_to_user_id"] == USER_ID

    async def test_deep_link_unscoped_for_dispatch(self) -> None:
        service = _appointment_service()
        async with _client(appointments_module, service, "manager", APPOINTMENTS_PREFIX) as client:
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/appointments/{APPOINTMENT_ID}")
        assert response.status_code == 200
        assert service.get_appointment.await_args.kwargs["visible_to_user_id"] is None


class TestAppointmentMutationScope:
    @pytest.mark.parametrize(
        ("method", "path", "json"),
        [
            ("put", f"/{APPOINTMENT_ID}", {"status": "completed"}),
            ("delete", f"/{APPOINTMENT_ID}", None),
            ("post", f"/{APPOINTMENT_ID}/send-reminder", None),
        ],
    )
    async def test_restricted_mutations_are_scoped_to_caller(
        self, method: str, path: str, json: dict[str, object] | None
    ) -> None:
        service = _appointment_service()
        async with _client(
            appointments_module, service, "technician", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.request(
                method, f"/api/v1/workspaces/{WS_ID}/appointments{path}", json=json
            )

        assert response.status_code in {200, 204}
        service_method = {
            "put": service.update_appointment,
            "delete": service.delete_appointment,
            "post": service.send_reminder,
        }[method]
        assert service_method.await_args.kwargs["visible_to_user_id"] == USER_ID

    async def test_restricted_user_cannot_reassign_an_appointment(self) -> None:
        service = _appointment_service()
        async with _client(
            appointments_module, service, "technician", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.put(
                f"/api/v1/workspaces/{WS_ID}/appointments/{APPOINTMENT_ID}",
                json={"bookable_staff_id": str(uuid.uuid4())},
            )

        assert response.status_code == 403
        service.update_appointment.assert_not_awaited()

    @pytest.mark.parametrize(
        ("method", "path", "json"),
        [
            ("put", f"/{APPOINTMENT_ID}", {"status": "completed"}),
            ("delete", f"/{APPOINTMENT_ID}", None),
            ("post", f"/{APPOINTMENT_ID}/send-reminder", None),
        ],
    )
    async def test_dispatch_mutations_remain_workspace_wide(
        self, method: str, path: str, json: dict[str, object] | None
    ) -> None:
        service = _appointment_service()
        async with _client(
            appointments_module, service, "dispatcher", APPOINTMENTS_PREFIX
        ) as client:
            response = await client.request(
                method, f"/api/v1/workspaces/{WS_ID}/appointments{path}", json=json
            )

        assert response.status_code in {200, 204}
        service_method = {
            "put": service.update_appointment,
            "delete": service.delete_appointment,
            "post": service.send_reminder,
        }[method]
        assert service_method.await_args.kwargs["visible_to_user_id"] is None

    async def test_reminder_send_enforces_workspace_rate_limit(self) -> None:
        service = _appointment_service()
        limiter = AsyncMock()
        async with _client(
            appointments_module, service, "dispatcher", APPOINTMENTS_PREFIX
        ) as client:
            with patch.object(
                appointments_module, "enforce_appointment_reminder_rate_limit", limiter
            ):
                response = await client.post(
                    f"/api/v1/workspaces/{WS_ID}/appointments/{APPOINTMENT_ID}/send-reminder"
                )

        assert response.status_code == 200
        limiter.assert_awaited_once_with(WS_ID, USER_ID)
