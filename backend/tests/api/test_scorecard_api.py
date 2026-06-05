"""Auth and validation tests for the receptionist scorecard endpoint."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1 import scorecard as scorecard_module
from app.schemas.scorecard import ReceptionistScorecard

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


def _make_app(*, authed: bool) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    if authed:

        async def override_get_db() -> AsyncIterator[AsyncMock]:
            yield AsyncMock()

        async def override_get_workspace() -> MagicMock:
            return _make_mock_workspace()

        async def override_get_current_user() -> MagicMock:
            return _make_mock_user()

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_workspace] = override_get_workspace
        app.dependency_overrides[get_current_user] = override_get_current_user

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


class TestScorecardAuth:
    async def test_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/scorecard")
        assert resp.status_code == 401

    async def test_invalid_workspace_uuid(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get("/api/v1/workspaces/not-a-uuid/scorecard")
        assert resp.status_code in (401, 422)


class TestScorecardValidation:
    async def test_invalid_start_date_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/workspaces/{WS_ID}/scorecard?start_date=not-a-date")
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
