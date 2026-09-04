"""Auth and validation tests for the receptionist scorecard endpoint."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import scorecard as scorecard_module
from app.schemas.scorecard import (
    OfficeRepScorecardRow,
    ReceptionistScorecard,
    TechnicianActivityScorecardRow,
)

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_mock_workspace() -> MagicMock:
    ws = MagicMock()
    ws.id = WS_ID
    ws.is_active = True
    ws.settings = {"timezone": "America/New_York"}
    return ws


def _make_mock_user() -> MagicMock:
    user = MagicMock()
    user.id = 1
    user.is_active = True
    return user


def _make_app(*, authed: bool, role: str = "admin") -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    if authed:

        async def override_get_db() -> AsyncIterator[AsyncMock]:
            yield AsyncMock()

        async def override_get_workspace() -> MagicMock:
            return _make_mock_workspace()

        async def override_get_current_user() -> MagicMock:
            return _make_mock_user()

        async def override_get_membership() -> MagicMock:
            membership = MagicMock()
            membership.workspace_id = WS_ID
            membership.user_id = 1
            membership.role = role
            return membership

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_workspace] = override_get_workspace
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_membership] = override_get_membership

    app.include_router(
        scorecard_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/scorecard",
    )
    return app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = _make_app(authed=True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def noauth_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(authed=False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


@pytest.fixture
async def member_client() -> AsyncIterator[AsyncClient]:
    app = _make_app(authed=True, role="member")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


class TestScorecardAuth:
    async def test_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/scorecard")
        assert resp.status_code == 401

    async def test_invalid_workspace_uuid(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get("/api/v1/workspaces/not-a-uuid/scorecard")
        assert resp.status_code in (401, 422)

    @pytest.mark.parametrize("path", ["technicians", "office-reps"])
    async def test_requires_reports_capability(self, member_client: AsyncClient, path: str) -> None:
        resp = await member_client.get(f"/api/v1/workspaces/{WS_ID}/scorecard/{path}")
        assert resp.status_code == 403


class TestScorecardValidation:
    async def test_invalid_start_date_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/workspaces/{WS_ID}/scorecard?start_date=not-a-date")
        assert resp.status_code == 422

    async def test_office_range_over_366_days_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/workspaces/{WS_ID}/scorecard/office-reps"
            "?start_date=2025-01-01&end_date=2026-01-02"
        )
        assert resp.status_code == 422


class TestScorecardHappyPath:
    async def test_returns_scorecard(self, client: AsyncClient) -> None:
        sample = ReceptionistScorecard(
            start_date="2026-01-01",
            end_date="2026-01-31",
            calls_total=10,
            calls_answered=8,
            answer_rate=80.0,
            missed_calls=2,
            missed_calls_textback_sent=2,
            missed_calls_recovered=1,
            recovery_rate=50.0,
            appointments_booked=3,
            revenue_booked=1500.0,
            deposits_booked=500.0,
            currency="USD",
            after_hours_calls=4,
            after_hours_answered=3,
            after_hours_coverage_rate=75.0,
            avg_handle_time_seconds=120.0,
            top_call_reasons=[],
            new_leads_total=3,
            new_leads_by_day=[
                {"date": "2026-01-01", "count": 2},
                {"date": "2026-01-02", "count": 1},
            ],
            avg_new_leads_per_day=1.5,
        )
        with pytest.MonkeyPatch().context() as mp:
            mock_get = AsyncMock(return_value=sample)
            mp.setattr(scorecard_module.ScorecardService, "get_scorecard", mock_get)
            resp = await client.get(
                f"/api/v1/workspaces/{WS_ID}/scorecard?start_date=2026-01-01&end_date=2026-01-31"
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["calls_total"] == 10
        assert body["answer_rate"] == 80.0
        assert body["missed_calls_recovered"] == 1
        assert body["currency"] == "USD"
        assert body["new_leads_total"] == 3
        assert body["avg_new_leads_per_day"] == 1.5
        # Serialized as ISO date strings the chart can bucket directly.
        assert body["new_leads_by_day"] == [
            {"date": "2026-01-01", "count": 2},
            {"date": "2026-01-02", "count": 1},
        ]

    async def test_returns_pause_adjusted_technician_activity(self, client: AsyncClient) -> None:
        sample = [
            TechnicianActivityScorecardRow(
                id=uuid.uuid4(),
                name="Taylor Tech",
                active=True,
                assigned_jobs=4,
                completed_job_time_entries=3,
                job_logged_seconds=9_000,
                attendance_worked_seconds=14_400,
                attendance_paused_seconds=1_800,
            )
        ]
        with pytest.MonkeyPatch().context() as mp:
            mock_get = AsyncMock(return_value=sample)
            mp.setattr(
                scorecard_module.ScorecardService,
                "get_technician_activity",
                mock_get,
            )
            resp = await client.get(
                f"/api/v1/workspaces/{WS_ID}/scorecard/technicians"
                "?start_date=2026-01-01&end_date=2026-01-31"
            )

        assert resp.status_code == 200
        assert resp.json()[0] == {
            "id": str(sample[0].id),
            "name": "Taylor Tech",
            "active": True,
            "assigned_jobs": 4,
            "completed_job_time_entries": 3,
            "job_logged_seconds": 9_000,
            "attendance_worked_seconds": 14_400,
            "attendance_paused_seconds": 1_800,
        }

    async def test_returns_office_rep_profiles(self, client: AsyncClient) -> None:
        sample = [
            OfficeRepScorecardRow(
                user_id=7,
                name="Casey Admin",
                role="admin",
                avatar_url=None,
                attendance_days=18,
                attendance_worked_seconds=432_000,
                booked_jobs=12,
                cancelled_jobs=1,
                cancellation_rate=8.3,
                responses_measured=9,
                avg_response_time_seconds=92.0,
            )
        ]
        with pytest.MonkeyPatch().context() as mp:
            mock_get = AsyncMock(return_value=sample)
            mp.setattr(
                scorecard_module.ScorecardService,
                "get_office_rep_activity",
                mock_get,
            )
            resp = await client.get(
                f"/api/v1/workspaces/{WS_ID}/scorecard/office-reps"
                "?start_date=2026-01-01&end_date=2026-01-31"
            )

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "user_id": 7,
                "name": "Casey Admin",
                "role": "admin",
                "avatar_url": None,
                "attendance_days": 18,
                "attendance_worked_seconds": 432_000,
                "booked_jobs": 12,
                "cancelled_jobs": 1,
                "cancellation_rate": 8.3,
                "responses_measured": 9,
                "avg_response_time_seconds": 92.0,
            }
        ]
        mock_get.assert_awaited_once()
