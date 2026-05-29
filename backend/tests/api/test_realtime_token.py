"""Tests for authenticated Realtime token endpoint."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_workspace
from app.api.v1.router import api_router
from app.models.user import User
from app.models.workspace import Workspace


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def _make_agent(workspace_id: uuid.UUID, agent_id: uuid.UUID) -> MagicMock:
    agent = MagicMock()
    agent.id = agent_id
    agent.workspace_id = workspace_id
    agent.name = "Voice Test Agent"
    agent.system_prompt = "Be helpful"
    agent.voice_id = "marin"
    agent.language = "en"
    agent.initial_greeting = "Hello"
    agent.turn_detection_mode = "server_vad"
    agent.turn_detection_threshold = 0.45
    agent.silence_duration_ms = 650
    agent.calcom_event_type_id = None
    agent.enabled_tools = []
    agent.tool_settings = {}
    return agent


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    user = MagicMock(spec=User)
    user.id = 1

    async def override_user() -> User:
        return user

    async def override_db() -> MagicMock:
        db = MagicMock()
        db.execute = AsyncMock()
        return db

    async def override_workspace(workspace_id: uuid.UUID) -> Workspace:
        workspace = MagicMock(spec=Workspace)
        workspace.id = workspace_id
        return workspace

    app = FastAPI(lifespan=_test_lifespan)
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_workspace] = override_workspace
    app.include_router(api_router, prefix="/api/v1")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac


async def test_realtime_token_posts_ga_client_secret_body(client: AsyncClient) -> None:
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    agent = _make_agent(workspace_id, agent_id)

    fake_openai_response = MagicMock()
    fake_openai_response.status_code = 200
    fake_openai_response.json.return_value = {"value": "secret-value"}

    fake_http_client = AsyncMock()
    fake_http_client.post = AsyncMock(return_value=fake_openai_response)
    fake_http_client.__aenter__.return_value = fake_http_client
    fake_http_client.__aexit__.return_value = None

    credential_context = MagicMock()
    credential_context.source = "workspace_api_key"
    credential_context.openai_headers.return_value = {"Authorization": "Bearer sk-test"}

    with (
        patch("app.api.v1.realtime.AgentService") as agent_service_cls,
        patch(
            "app.api.v1.realtime.resolve_openai_credentials",
            new=AsyncMock(return_value=credential_context),
        ),
        patch("app.api.v1.realtime.httpx.AsyncClient", return_value=fake_http_client),
    ):
        agent_service_cls.return_value.get_agent = AsyncMock(return_value=agent)
        response = await client.post(
            f"/api/v1/realtime/token/{agent_id}?workspace_id={workspace_id}",
            json={
                "voice": "cedar",
                "instructions": "Test instructions",
                "turn_detection_threshold": 0.55,
                "silence_duration_ms": 800,
                "initial_greeting": "Hi there",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["client_secret"] == {"value": "secret-value"}
    assert data["model"] == "gpt-realtime-2"
    assert data["agent"]["initial_greeting"] == "Hi there"

    posted = fake_http_client.post.await_args.kwargs
    assert posted["headers"]["Authorization"] == "Bearer sk-test"
    body = posted["json"]
    assert body["expires_after"]["seconds"] == 600
    session = body["session"]
    assert session["type"] == "realtime"
    assert session["model"] == "gpt-realtime-2"
    assert session["instructions"] == "Test instructions"
    assert session["output_modalities"] == ["audio"]
    assert session["audio"]["output"]["voice"] == "cedar"
    assert session["audio"]["input"]["format"] == {"type": "audio/pcmu"}
    assert session["audio"]["input"]["turn_detection"]["threshold"] == 0.55
