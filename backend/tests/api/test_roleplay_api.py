"""Auth + happy-path tests for the practice-arena (roleplay) router.

Uses dependency overrides (no real DB) and stubs ``RoleplayService`` methods so
routing, auth, and response serialization are exercised end-to-end.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import roleplay as roleplay_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_app(*, authed: bool) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    if authed:

        async def override_get_db() -> AsyncIterator[AsyncMock]:
            yield AsyncMock()

        async def override_get_workspace() -> MagicMock:
            return SimpleNamespace(id=WS_ID, is_active=True)

        async def override_get_current_user() -> MagicMock:
            return SimpleNamespace(id=1, is_active=True)

        async def override_get_membership() -> MagicMock:
            return SimpleNamespace(role="member", workspace_id=WS_ID)

        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_workspace] = override_get_workspace
        app.dependency_overrides[get_current_user] = override_get_current_user
        app.dependency_overrides[get_membership] = override_get_membership

    app.include_router(
        roleplay_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/roleplay",
    )
    return app


def _persona() -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=None,
        slug="skeptical-homeowner",
        name="Skeptical Homeowner",
        description="Guarded homeowner",
        difficulty="hard",
        channel="sms",
        persona_prompt="be skeptical",
        opening_message="Who is this?",
        objections=["distrust"],
        goal="book a visit",
        is_builtin=True,
        created_at=now,
        updated_at=now,
    )


def _run(status: str = "completed") -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=WS_ID,
        agent_id=uuid.uuid4(),
        persona_id=uuid.uuid4(),
        agent_name="Closer Bot",
        persona_name="Skeptical Homeowner",
        rehearsee="ai",
        channel="sms",
        status=status,
        max_turns=6,
        transcript=[{"role": "prospect", "content": "Who is this?"}],
        scores={"tone_label": "warm"},
        overall_score=82.0,
        objection_coverage=75.0,
        booking_attempted=True,
        tone_score=80.0,
        strengths=["clear"],
        gaps=["no urgency"],
        suggestions=["add pricing"],
        summary="Good rapport.",
        error=None,
        created_at=now,
        updated_at=now,
        completed_at=now,
    )


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


class TestRoleplayAuth:
    async def test_personas_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.get(f"/api/v1/workspaces/{WS_ID}/roleplay/personas")
        assert resp.status_code == 401

    async def test_create_run_requires_auth(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.post(
            f"/api/v1/workspaces/{WS_ID}/roleplay/runs",
            json={"agent_id": str(uuid.uuid4()), "persona_id": str(uuid.uuid4())},
        )
        assert resp.status_code == 401


class TestRoleplayHappyPath:
    async def test_list_personas(self, client: AsyncClient) -> None:
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                roleplay_module.RoleplayService,
                "list_personas",
                AsyncMock(return_value=[_persona()]),
            )
            resp = await client.get(f"/api/v1/workspaces/{WS_ID}/roleplay/personas")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["slug"] == "skeptical-homeowner"
        assert body[0]["is_builtin"] is True
        assert body[0]["objections"] == ["distrust"]

    async def test_create_run_returns_scored_report(self, client: AsyncClient) -> None:
        with pytest.MonkeyPatch().context() as mp:
            mp.setattr(
                roleplay_module.RoleplayService,
                "create_run",
                AsyncMock(return_value=_run("completed")),
            )
            resp = await client.post(
                f"/api/v1/workspaces/{WS_ID}/roleplay/runs",
                json={
                    "agent_id": str(uuid.uuid4()),
                    "persona_id": str(uuid.uuid4()),
                    "rehearsee": "ai",
                    "max_turns": 6,
                },
            )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "completed"
        assert body["overall_score"] == 82.0
        assert body["booking_attempted"] is True
        assert body["suggestions"] == ["add pricing"]
        assert body["transcript"][0]["role"] == "prospect"

    async def test_max_turns_validation(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/workspaces/{WS_ID}/roleplay/runs",
            json={
                "agent_id": str(uuid.uuid4()),
                "persona_id": str(uuid.uuid4()),
                "max_turns": 99,
            },
        )
        assert resp.status_code == 422
