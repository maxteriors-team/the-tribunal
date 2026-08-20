"""API adapter tests for prompt version endpoints."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import prompt_versions as prompt_versions_module
from app.schemas.prompt_version import PromptVersionResponse
from app.services.exceptions import NotFoundError, ValidationError


@asynccontextmanager
async def _test_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield


def _user() -> MagicMock:
    user = MagicMock()
    user.id = 7
    user.is_active = True
    return user


def _workspace(workspace_id: uuid.UUID) -> MagicMock:
    workspace = MagicMock()
    workspace.id = workspace_id
    workspace.is_active = True
    return workspace


def _prompt_version_response(
    *,
    agent_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> PromptVersionResponse:
    return PromptVersionResponse(
        id=version_id or uuid.uuid4(),
        agent_id=agent_id,
        system_prompt="You are helpful.",
        initial_greeting="Hello",
        temperature=0.7,
        version_number=1,
        change_summary="Initial test version",
        created_by_id=7,
        is_active=True,
        is_baseline=True,
        parent_version_id=None,
        total_calls=0,
        successful_calls=0,
        booked_appointments=0,
        traffic_percentage=None,
        experiment_id=None,
        arm_status="active",
        bandit_alpha=1.0,
        bandit_beta=1.0,
        total_reward=0.0,
        reward_count=0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        activated_at=None,
    )


def _make_app(
    *,
    workspace_id: uuid.UUID,
    db: MagicMock,
) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)

    async def override_get_db() -> AsyncIterator[MagicMock]:
        yield db

    async def override_get_current_user() -> MagicMock:
        return _user()

    async def override_get_workspace() -> MagicMock:
        return _workspace(workspace_id)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_membership] = lambda: MagicMock(
        role="owner", workspace_id=workspace_id
    )
    app.include_router(
        prompt_versions_module.router,
        prefix="/api/v1/workspaces/{workspace_id}/agents/{agent_id}/prompts",
    )
    return app


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
async def prompt_client(
    monkeypatch: pytest.MonkeyPatch,
    mock_db: MagicMock,
) -> AsyncIterator[tuple[AsyncClient, MagicMock, uuid.UUID, uuid.UUID]]:
    workspace_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    service = MagicMock()
    monkeypatch.setattr(
        prompt_versions_module,
        "_prompt_version_service",
        MagicMock(return_value=service),
    )
    app = _make_app(workspace_id=workspace_id, db=mock_db)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client, service, workspace_id, agent_id


async def test_create_prompt_version_delegates_to_lifecycle_service(
    prompt_client: tuple[AsyncClient, MagicMock, uuid.UUID, uuid.UUID],
    mock_db: MagicMock,
) -> None:
    client, service, workspace_id, agent_id = prompt_client
    response_model = _prompt_version_response(agent_id=agent_id)
    service.create_version_for_agent = AsyncMock(return_value=response_model)

    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/prompts",
        json={"system_prompt": "New prompt", "change_summary": "Test change", "is_baseline": True},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(response_model.id)
    assert body["system_prompt"] == "You are helpful."
    service.create_version_for_agent.assert_awaited_once()
    args = service.create_version_for_agent.await_args.args
    assert args[:3] == (mock_db, workspace_id, agent_id)
    assert args[3].system_prompt == "New prompt"
    assert service.create_version_for_agent.await_args.kwargs == {"created_by_id": 7}


async def test_compare_route_uses_static_path_not_version_id_path(
    prompt_client: tuple[AsyncClient, MagicMock, uuid.UUID, uuid.UUID],
    mock_db: MagicMock,
) -> None:
    client, service, workspace_id, agent_id = prompt_client
    winner_id = uuid.uuid4()
    service.compare_versions_in_workspace = AsyncMock(
        return_value={
            "versions": [
                {
                    "version_id": str(winner_id),
                    "version_number": 3,
                    "is_active": True,
                    "is_baseline": False,
                    "arm_status": "active",
                    "probability_best": 0.97,
                    "credible_interval_lower": 0.6,
                    "credible_interval_upper": 0.9,
                    "sample_size": 44,
                    "booking_rate": 0.5,
                    "mean_estimate": 0.75,
                }
            ],
            "winner_id": str(winner_id),
            "winner_probability": 0.97,
            "recommended_action": "declare_winner",
            "min_samples_needed": 0,
        }
    )
    service.get_version = AsyncMock(
        side_effect=AssertionError("compare must not hit version lookup")
    )

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/prompts/compare",
        params={"winner_threshold": "0.9"},
    )

    assert response.status_code == 200
    assert response.json()["winner_id"] == str(winner_id)
    service.compare_versions_in_workspace.assert_awaited_once_with(
        mock_db,
        workspace_id,
        agent_id,
        winner_threshold=0.9,
    )
    service.get_version.assert_not_called()


async def test_winner_route_translates_not_found_to_404(
    prompt_client: tuple[AsyncClient, MagicMock, uuid.UUID, uuid.UUID],
) -> None:
    client, service, workspace_id, agent_id = prompt_client
    service.detect_winner_in_workspace = AsyncMock(side_effect=NotFoundError("Agent not found"))

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/prompts/winner",
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "not_found",
        "message": "Agent not found",
    }


async def test_pause_route_translates_validation_error_to_400(
    prompt_client: tuple[AsyncClient, MagicMock, uuid.UUID, uuid.UUID],
) -> None:
    client, service, workspace_id, agent_id = prompt_client
    version_id = uuid.uuid4()
    service.pause_version_in_workspace = AsyncMock(
        side_effect=ValidationError("Cannot pause eliminated version")
    )

    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/prompts/{version_id}/pause",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "validation_error",
        "message": "Cannot pause eliminated version",
    }


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("compare", {"winner_threshold": "0.499"}),
        ("winner", {"threshold": "1.0"}),
    ],
)
async def test_static_statistical_routes_preserve_query_validation(
    prompt_client: tuple[AsyncClient, MagicMock, uuid.UUID, uuid.UUID],
    path: str,
    params: dict[str, str],
) -> None:
    client, _service, workspace_id, agent_id = prompt_client

    response = await client.get(
        f"/api/v1/workspaces/{workspace_id}/agents/{agent_id}/prompts/{path}",
        params=params,
    )

    assert response.status_code == 422
    errors: list[dict[str, Any]] = response.json()["detail"]
    assert errors[0]["loc"][0] == "query"
