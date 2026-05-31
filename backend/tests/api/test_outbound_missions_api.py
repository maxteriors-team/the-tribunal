"""API tests for the Outbound Mission / Lead Miner endpoints.

Two layers of coverage:

* **Auth + validation** (no real DB): asserts that every route requires
  authentication and that query/body validators reject bad inputs.
* **Happy-path mocked** (no real DB): overrides ``get_db`` / ``get_workspace`` /
  ``get_current_user`` and patches ``paginate`` so we can drive the handlers
  end-to-end with deterministic fixtures.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import outbound_missions as outbound_missions_module
from app.db.pagination import PaginationResult
from app.models.lead_discovery_job import DiscoveryJobStatus, DiscoverySourceType
from app.models.lead_prospect import (
    EnrichmentProvider,
    EnrichmentResultStatus,
    ProspectIdentityKind,
    ProspectStatus,
)
from app.models.outbound_mission import MissionStatus
from app.models.outbound_sequence import (
    OutboundSequenceStatus,
    SequenceEnrollmentStatus,
)

WS_ID = uuid.uuid4()
MISSION_ID = uuid.uuid4()
PROSPECT_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
SEQUENCE_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Lifecycle / fixtures
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Minimal lifespan that skips workers, Redis, and DB setup."""
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
    user.email = "tester@example.com"
    return user


def _make_mock_mission(
    *,
    mission_id: uuid.UUID = MISSION_ID,
    workspace_id: uuid.UUID = WS_ID,
    mission_status: MissionStatus = MissionStatus.DRAFT,
    default_sequence_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a MagicMock that quacks like an OutboundMission row."""
    mission = MagicMock()
    mission.id = mission_id
    mission.workspace_id = workspace_id
    mission.created_by_id = 1
    mission.offer_id = None
    mission.default_agent_id = None
    mission.default_sequence_id = default_sequence_id
    mission.name = "Test Mission"
    mission.description = "desc"
    mission.objective = "book_call"
    mission.status = mission_status
    mission.target_audience = {}
    mission.discovery_config = {}
    mission.enrichment_config = {}
    mission.sequence_config = {}
    mission.default_from_phone_number = None
    mission.default_from_email = None
    mission.daily_prospect_cap = 100
    mission.daily_outreach_cap = 50
    mission.timezone = "America/New_York"
    mission.total_prospects_discovered = 50
    mission.total_prospects_enriched = 30
    mission.total_prospects_contacted = 20
    mission.total_prospects_replied = 5
    mission.total_prospects_qualified = 2
    mission.total_contacts_created = 1
    mission.total_appointments_booked = 1
    now = datetime.now(UTC)
    mission.started_at = None
    mission.paused_at = None
    mission.completed_at = None
    mission.archived_at = None
    mission.last_run_at = None
    mission.next_run_at = None
    mission.created_at = now
    mission.updated_at = now
    return mission


def _make_mock_prospect(
    *,
    prospect_id: uuid.UUID = PROSPECT_ID,
    workspace_id: uuid.UUID = WS_ID,
    mission_id: uuid.UUID = MISSION_ID,
    prospect_status: ProspectStatus = ProspectStatus.NEW,
) -> MagicMock:
    prospect = MagicMock()
    prospect.id = prospect_id
    prospect.workspace_id = workspace_id
    prospect.mission_id = mission_id
    prospect.discovery_job_id = None
    prospect.contact_id = None
    prospect.identity_kind = ProspectIdentityKind.MULTI
    prospect.first_name = "Jane"
    prospect.last_name = "Doe"
    prospect.full_name = "Jane Doe"
    prospect.title = None
    prospect.email = "jane@example.com"
    prospect.phone_number = "+15555550100"
    prospect.company_name = "Acme"
    prospect.website_url = "https://acme.example"
    prospect.website_host = "acme.example"
    prospect.linkedin_url = None
    prospect.country_code = "US"
    prospect.region = "CA"
    prospect.city = "SF"
    prospect.location_label = "SF, CA"
    prospect.source_type = "google_places"
    prospect.source_external_id = "ext-1"
    prospect.source_query = "plumbers"
    prospect.provenance = {"origin": "google_places"}
    prospect.evidence = [{"snippet": "Plumbing services since 1999"}]
    prospect.dedupe_key = "deadbeef"
    prospect.lead_score = 80
    prospect.qualification_score = 50
    prospect.status = prospect_status
    prospect.suppression_reason = None
    prospect.enrichment_attempts = 1
    now = datetime.now(UTC)
    prospect.last_enriched_at = now
    prospect.last_contacted_at = None
    prospect.last_replied_at = None
    prospect.last_failed_at = None
    prospect.reply_count = 0
    prospect.bounce_count = 0
    prospect.discovered_at = now
    prospect.promoted_at = None
    prospect.created_at = now
    prospect.updated_at = now
    return prospect


def _make_mock_discovery_job(
    *,
    job_id: uuid.UUID = JOB_ID,
    workspace_id: uuid.UUID = WS_ID,
    mission_id: uuid.UUID = MISSION_ID,
    job_status: DiscoveryJobStatus = DiscoveryJobStatus.SUCCEEDED,
) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.workspace_id = workspace_id
    job.mission_id = mission_id
    job.requested_by_id = 1
    job.source_type = DiscoverySourceType.GOOGLE_PLACES
    job.source_label = "Plumbers SF"
    job.query = "plumbers"
    job.params = {"radius": 5000}
    job.status = job_status
    job.requested_count = 100
    job.discovered_count = 80
    job.duplicate_count = 5
    job.invalid_count = 2
    now = datetime.now(UTC)
    job.started_at = now
    job.completed_at = now
    job.last_error = None
    job.error_count = 0
    job.created_at = now
    job.updated_at = now
    return job


def _make_mock_sequence(*, sequence_id: uuid.UUID = SEQUENCE_ID) -> MagicMock:
    sequence = MagicMock()
    sequence.id = sequence_id
    sequence.workspace_id = WS_ID
    sequence.name = "Default Sequence"
    sequence.description = "desc"
    sequence.status = OutboundSequenceStatus.ACTIVE
    sequence.is_default = True
    sequence.steps = [
        {"order": 0, "channel": "sms", "delay_hours": 0, "template": "hi"},
    ]
    sequence.channel_priority = None
    sequence.max_attempts_per_step = 1
    sequence.sending_hours_start = None
    sequence.sending_hours_end = None
    sequence.sending_days = None
    sequence.timezone = "America/New_York"
    sequence.total_enrollments = 0
    sequence.total_completed = 0
    sequence.total_replied = 0
    sequence.total_converted = 0
    now = datetime.now(UTC)
    sequence.created_at = now
    sequence.updated_at = now
    return sequence


def _make_mock_enrichment_result() -> MagicMock:
    row = MagicMock()
    row.id = uuid.uuid4()
    row.workspace_id = WS_ID
    row.prospect_id = PROSPECT_ID
    row.mission_id = MISSION_ID
    row.provider = EnrichmentProvider.GOOGLE_PLACES
    row.status = EnrichmentResultStatus.SUCCESS
    row.request_payload = {"q": "plumbers"}
    row.response_payload = {"hits": 1}
    row.extracted = {"website": "acme.example"}
    row.score_delta = 10
    row.cost_cents = 5
    row.duration_ms = 120
    row.error_message = None
    row.created_at = datetime.now(UTC)
    return row


def _make_auth_test_app(
    mock_db: AsyncMock, mock_workspace: MagicMock, mock_user: MagicMock
) -> FastAPI:
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

    app.include_router(
        outbound_missions_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/outbound-missions",
    )
    return app


def _make_noauth_test_app() -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    app.include_router(
        outbound_missions_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/outbound-missions",
    )
    return app


@pytest.fixture
def mock_db() -> AsyncMock:
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = MagicMock()
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
    app = _make_auth_test_app(mock_db, mock_workspace, mock_user)
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


# ---------------------------------------------------------------------------
# Helpers for mocking db.execute return values
# ---------------------------------------------------------------------------


def _scalar_one_result(value: Any) -> MagicMock:
    """Build a result whose ``scalar_one_or_none()`` returns ``value``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_all_result(values: list[Any]) -> MagicMock:
    """Build a result whose ``scalars().all()`` returns ``values``."""
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


def _rows_result(rows: list[tuple[Any, ...]]) -> MagicMock:
    """Build a result whose ``all()`` returns ``rows``."""
    result = MagicMock()
    result.all.return_value = rows
    return result


# ---------------------------------------------------------------------------
# Auth + validation tests
# ---------------------------------------------------------------------------


class TestMissionAuth:
    """Every mission route requires authentication."""

    async def test_list_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions")
        assert response.status_code == 401

    async def test_create_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions",
            json={"name": "x"},
        )
        assert response.status_code == 401

    async def test_get_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}"
        )
        assert response.status_code == 401

    async def test_delete_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.delete(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}"
        )
        assert response.status_code == 401

    async def test_start_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/start"
        )
        assert response.status_code == 401

    async def test_stats_without_auth_returns_401(self, noauth_client: AsyncClient) -> None:
        response = await noauth_client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/stats"
        )
        assert response.status_code == 401

    async def test_list_prospects_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        response = await noauth_client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/prospects"
        )
        assert response.status_code == 401

    async def test_discovery_jobs_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        response = await noauth_client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/discovery-jobs"
        )
        assert response.status_code == 401

    async def test_enrichment_status_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        response = await noauth_client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/enrichment-status"
        )
        assert response.status_code == 401

    async def test_sequence_overview_without_auth_returns_401(
        self, noauth_client: AsyncClient
    ) -> None:
        response = await noauth_client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/sequence"
        )
        assert response.status_code == 401


class TestMissionValidation:
    """Validator coverage for request bodies and query params."""

    async def test_create_missing_name_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions",
            json={},
        )
        assert response.status_code == 422

    async def test_create_blank_name_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions",
            json={"name": ""},
        )
        assert response.status_code == 422

    async def test_create_negative_cap_returns_422(self, client: AsyncClient) -> None:
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions",
            json={"name": "x", "daily_prospect_cap": -1},
        )
        assert response.status_code == 422

    async def test_list_page_zero_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions?page=0")
        assert response.status_code == 422

    async def test_list_page_size_too_high_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions?page_size=101")
        assert response.status_code == 422

    async def test_list_invalid_status_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions?status=not-a-status"
        )
        assert response.status_code == 422

    async def test_get_invalid_mission_uuid_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions/not-a-uuid")
        assert response.status_code == 422

    async def test_get_nonexistent_mission_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(None))
        response = await client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_list_prospects_invalid_score_returns_422(self, client: AsyncClient) -> None:
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/prospects?min_score=-1"
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Happy-path mission CRUD + lifecycle
# ---------------------------------------------------------------------------


class TestCreateMission:
    async def test_create_minimal_returns_201(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        # No FKs supplied → _validate_mission_fks is a no-op.
        async def fake_refresh(obj: Any) -> None:
            # Populate the fields the response model requires that aren't
            # already set by the ``OutboundMission(**mission_in.model_dump())``
            # call. SQLAlchemy column defaults (status, counters, timestamps)
            # only apply on a real INSERT, which the mocked session skips.
            template = _make_mock_mission(mission_id=uuid.uuid4())
            for attr in [
                "id",
                "created_by_id",
                "status",
                "started_at",
                "paused_at",
                "completed_at",
                "archived_at",
                "last_run_at",
                "next_run_at",
                "created_at",
                "updated_at",
                "total_prospects_discovered",
                "total_prospects_enriched",
                "total_prospects_contacted",
                "total_prospects_replied",
                "total_prospects_qualified",
                "total_contacts_created",
                "total_appointments_booked",
            ]:
                setattr(obj, attr, getattr(template, attr))

        mock_db.refresh = AsyncMock(side_effect=fake_refresh)

        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions",
            json={"name": "New mission", "objective": "qualify"},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["name"] == "New mission"
        assert body["objective"] == "qualify"
        assert body["status"] == MissionStatus.DRAFT.value
        mock_db.commit.assert_awaited()

    async def test_create_with_unknown_offer_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(None))
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions",
            json={"name": "x", "offer_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Offer not found"


class TestListMissions:
    async def test_list_returns_pagination(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission()
        with patch(
            "app.services.outbound.mission_service.paginate", new_callable=AsyncMock
        ) as mock_paginate:
            mock_paginate.return_value = PaginationResult(
                items=[mission], total=1, page=1, page_size=50, pages=1
            )
            response = await client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["page"] == 1
        assert body["pages"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["status"] == MissionStatus.DRAFT.value


class TestGetMission:
    async def test_get_returns_mission(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission()
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        response = await client.get(f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}")
        assert response.status_code == 200
        assert response.json()["id"] == str(MISSION_ID)


class TestMissionLifecycle:
    """start / pause / resume / complete / archive transitions."""

    async def test_start_from_draft_returns_active(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.DRAFT)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/start"
        )

        assert response.status_code == 200
        assert mission.status == MissionStatus.ACTIVE
        assert mission.started_at is not None

    async def test_start_from_active_returns_400(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.ACTIVE)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/start"
        )
        assert response.status_code == 400

    async def test_pause_from_active(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.ACTIVE)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/pause"
        )
        assert response.status_code == 200
        assert mission.status == MissionStatus.PAUSED
        assert mission.paused_at is not None

    async def test_resume_from_paused(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.PAUSED)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/resume"
        )
        assert response.status_code == 200
        assert mission.status == MissionStatus.ACTIVE

    async def test_complete_from_active(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.ACTIVE)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/complete"
        )
        assert response.status_code == 200
        assert mission.status == MissionStatus.COMPLETED
        assert mission.completed_at is not None

    async def test_archive_from_draft(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.DRAFT)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/archive"
        )
        assert response.status_code == 200
        assert mission.status == MissionStatus.ARCHIVED
        assert mission.archived_at is not None

    async def test_archive_already_archived_returns_400(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.ARCHIVED)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/archive"
        )
        assert response.status_code == 400


class TestDeleteMission:
    async def test_delete_draft_returns_204(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.DRAFT)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.delete(f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}")
        assert response.status_code == 204
        mock_db.delete.assert_awaited_with(mission)

    async def test_delete_active_returns_400(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.ACTIVE)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.delete(f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}")
        assert response.status_code == 400


class TestUpdateMission:
    async def test_update_draft_succeeds(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.DRAFT)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}",
            json={"name": "Renamed", "daily_outreach_cap": 25},
        )
        assert response.status_code == 200
        assert mission.name == "Renamed"
        assert mission.daily_outreach_cap == 25

    async def test_update_active_returns_400(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission(mission_status=MissionStatus.ACTIVE)
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))
        response = await client.put(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}",
            json={"name": "Renamed"},
        )
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class TestMissionStats:
    async def test_stats_computes_rates(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission()
        # contacted=20, replied=5, qualified=2, booked=1
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/stats"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mission_id"] == str(MISSION_ID)
        assert body["total_prospects_contacted"] == 20
        assert body["reply_rate"] == pytest.approx(0.25)
        assert body["qualification_rate"] == pytest.approx(0.1)
        assert body["booking_rate"] == pytest.approx(0.05)

    async def test_stats_zero_contacted_rates_zero(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        mission.total_prospects_contacted = 0
        mission.total_prospects_replied = 0
        mission.total_prospects_qualified = 0
        mission.total_appointments_booked = 0
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/stats"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["reply_rate"] == 0
        assert body["qualification_rate"] == 0
        assert body["booking_rate"] == 0


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------


class TestProspects:
    async def test_list_prospects_paginated(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect()
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        with patch(
            "app.services.outbound.mission_service.paginate", new_callable=AsyncMock
        ) as mock_paginate:
            mock_paginate.return_value = PaginationResult(
                items=[prospect], total=1, page=1, page_size=50, pages=1
            )
            response = await client.get(
                f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/prospects"
                "?has_email=true&min_score=10"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["company_name"] == "Acme"
        assert body["items"][0]["evidence"] == [{"snippet": "Plumbing services since 1999"}]
        assert body["items"][0]["provenance"] == {"origin": "google_places"}

    async def test_get_prospect_belongs_to_mission(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/prospects/{PROSPECT_ID}"
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(PROSPECT_ID)

    async def test_get_prospect_wrong_mission_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect(mission_id=uuid.uuid4())
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/prospects/{PROSPECT_ID}"
        )
        assert response.status_code == 404

    async def test_select_prospect_sets_queued(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )

        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/"
            f"{MISSION_ID}/prospects/{PROSPECT_ID}/select"
        )
        assert response.status_code == 200
        assert prospect.status == ProspectStatus.QUEUED

    async def test_select_suppressed_prospect_returns_400(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect(prospect_status=ProspectStatus.SUPPRESSED)
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )

        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/"
            f"{MISSION_ID}/prospects/{PROSPECT_ID}/select"
        )
        assert response.status_code == 400

    async def test_suppress_prospect_records_reason(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
            ]
        )

        response = await client.post(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/"
            f"{MISSION_ID}/prospects/{PROSPECT_ID}/suppress?reason=do-not-contact"
        )
        assert response.status_code == 200
        assert prospect.status == ProspectStatus.SUPPRESSED
        assert prospect.suppression_reason == "do-not-contact"

    async def test_enrichment_results_lists_audit_rows(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        prospect = _make_mock_prospect()
        enrichment = _make_mock_enrichment_result()

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(prospect),
                _scalars_all_result([enrichment]),
            ]
        )

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/"
            f"{MISSION_ID}/prospects/{PROSPECT_ID}/enrichment"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["provider"] == EnrichmentProvider.GOOGLE_PLACES.value
        assert body[0]["status"] == EnrichmentResultStatus.SUCCESS.value
        # Provenance / evidence-ish payloads serialize as-is.
        assert body[0]["extracted"] == {"website": "acme.example"}


# ---------------------------------------------------------------------------
# Discovery jobs
# ---------------------------------------------------------------------------


class TestDiscoveryJobs:
    async def test_list_jobs_paginated(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission()
        job = _make_mock_discovery_job()
        mock_db.execute = AsyncMock(return_value=_scalar_one_result(mission))

        with patch(
            "app.services.outbound.mission_service.paginate", new_callable=AsyncMock
        ) as mock_paginate:
            mock_paginate.return_value = PaginationResult(
                items=[job], total=1, page=1, page_size=50, pages=1
            )
            response = await client.get(
                f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/discovery-jobs"
            )

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["source_type"] == DiscoverySourceType.GOOGLE_PLACES.value

    async def test_get_job_belongs_to_mission(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        job = _make_mock_discovery_job()
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(job),
            ]
        )
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/discovery-jobs/{JOB_ID}"
        )
        assert response.status_code == 200
        assert response.json()["id"] == str(JOB_ID)

    async def test_get_job_wrong_mission_returns_404(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        job = _make_mock_discovery_job(mission_id=uuid.uuid4())
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(job),
            ]
        )
        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/discovery-jobs/{JOB_ID}"
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Enrichment status aggregate
# ---------------------------------------------------------------------------


class TestEnrichmentStatus:
    async def test_groups_by_provider_and_status(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission()
        rows = [
            (EnrichmentProvider.GOOGLE_PLACES, EnrichmentResultStatus.SUCCESS, 7),
            (EnrichmentProvider.GOOGLE_PLACES, EnrichmentResultStatus.FAILED, 1),
            (
                EnrichmentProvider.AI_CONTENT_ANALYZER,
                EnrichmentResultStatus.PARTIAL,
                2,
            ),
        ]
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _rows_result(rows),
            ]
        )

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/enrichment-status"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mission_id"] == str(MISSION_ID)
        assert body["total_prospects_enriched"] == 30
        assert body["by_provider"] == {
            EnrichmentProvider.GOOGLE_PLACES.value: {
                EnrichmentResultStatus.SUCCESS.value: 7,
                EnrichmentResultStatus.FAILED.value: 1,
            },
            EnrichmentProvider.AI_CONTENT_ANALYZER.value: {
                EnrichmentResultStatus.PARTIAL.value: 2,
            },
        }


# ---------------------------------------------------------------------------
# Sequence overview + enrollments
# ---------------------------------------------------------------------------


class TestSequenceOverview:
    async def test_overview_with_default_sequence(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        sequence = _make_mock_sequence()
        mission = _make_mock_mission(default_sequence_id=sequence.id)
        enrollment_rows = [
            (SequenceEnrollmentStatus.ACTIVE, 3),
            (SequenceEnrollmentStatus.COMPLETED, 2),
        ]
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalar_one_result(sequence),
                _rows_result(enrollment_rows),
            ]
        )

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/sequence"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["mission_id"] == str(MISSION_ID)
        assert body["default_sequence"] is not None
        assert body["default_sequence"]["id"] == str(sequence.id)
        assert body["enrollment_counts"] == {
            SequenceEnrollmentStatus.ACTIVE.value: 3,
            SequenceEnrollmentStatus.COMPLETED.value: 2,
        }
        assert body["total_enrollments"] == 5

    async def test_overview_without_default_sequence(
        self, client: AsyncClient, mock_db: AsyncMock
    ) -> None:
        mission = _make_mock_mission(default_sequence_id=None)
        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _rows_result([]),
            ]
        )

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/sequence"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["default_sequence"] is None
        assert body["total_enrollments"] == 0
        assert body["enrollment_counts"] == {}

    async def test_list_enrollments(self, client: AsyncClient, mock_db: AsyncMock) -> None:
        mission = _make_mock_mission()
        enrollment = MagicMock()
        enrollment.id = uuid.uuid4()
        enrollment.workspace_id = WS_ID
        enrollment.mission_id = MISSION_ID
        enrollment.sequence_id = SEQUENCE_ID
        enrollment.prospect_id = PROSPECT_ID
        enrollment.status = SequenceEnrollmentStatus.ACTIVE
        enrollment.current_step = 1
        now = datetime.now(UTC)
        enrollment.next_step_at = now
        enrollment.last_attempt_at = None
        enrollment.last_outcome = None
        enrollment.cancel_reason = None
        enrollment.attempts_made = 1
        enrollment.successful_attempts = 1
        enrollment.failed_attempts = 0
        enrollment.enrolled_at = now
        enrollment.completed_at = None
        enrollment.paused_until = None
        enrollment.created_at = now
        enrollment.updated_at = now

        mock_db.execute = AsyncMock(
            side_effect=[
                _scalar_one_result(mission),
                _scalars_all_result([enrollment]),
            ]
        )

        response = await client.get(
            f"/api/v1/workspaces/{WS_ID}/outbound-missions/{MISSION_ID}/enrollments"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["status"] == SequenceEnrollmentStatus.ACTIVE.value
