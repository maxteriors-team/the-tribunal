"""Contract tests for unsold-quote revival workspace settings."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


class _TemplateResult:
    def __init__(self, template_ids: set[uuid.UUID]) -> None:
        self.template_ids = template_ids

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: list(self.template_ids))


def _auth_app(
    workspace: SimpleNamespace,
    *,
    available_template_ids: set[uuid.UUID] | None = None,
) -> FastAPI:
    app = FastAPI(lifespan=_test_lifespan)
    template_ids = available_template_ids or set()
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_TemplateResult(template_ids))

    async def override_get_db() -> AsyncIterator[AsyncMock]:
        yield db

    async def override_get_workspace() -> SimpleNamespace:
        return workspace

    async def override_get_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=1, is_active=True, email="operator@example.com")

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_workspace] = override_get_workspace
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_membership] = lambda: SimpleNamespace(
        role="owner", workspace_id=WS_ID
    )
    app.include_router(settings_module.router, prefix="/api/v1")
    return app


@pytest.fixture
async def auth_client() -> AsyncIterator[AsyncClient]:
    workspace = SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings={})
    async with AsyncClient(
        transport=ASGITransport(app=_auth_app(workspace)),
        base_url="http://testserver",
    ) as client:
        yield client


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/unsold-quote-revival"


async def test_get_returns_disabled_30_60_90_default(auth_client: AsyncClient) -> None:
    response = await auth_client.get(_url())
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["max_touches"] == 3
    assert body["high_value_threshold"] == 5_000
    assert [touch["offset_days"] for touch in body["touches"]] == [30, 60, 90]
    assert [touch["channel"] for touch in body["touches"]] == ["sms", "email", "call"]


async def test_partial_update_round_trips_without_enabling(auth_client: AsyncClient) -> None:
    response = await auth_client.put(_url(), json={"high_value_threshold": 15_000})
    assert response.status_code == 200
    assert response.json()["high_value_threshold"] == 15_000
    assert (await auth_client.get(_url())).json()["high_value_threshold"] == 15_000


async def test_enabling_requires_saved_templates(auth_client: AsyncClient) -> None:
    response = await auth_client.put(_url(), json={"enabled": True})
    assert response.status_code == 422
    assert "need saved message templates" in response.json()["detail"]


async def test_touches_beyond_max_touches_need_no_template(auth_client: AsyncClient) -> None:
    """Capping the ladder must not force copy for steps that can never run."""
    template_id = uuid.uuid4()
    workspace = SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings={})
    app = _auth_app(workspace, available_template_ids={template_id})
    payload = {
        "enabled": True,
        "max_touches": 1,
        "touches": [
            {"offset_days": 30, "channel": "sms", "template_id": str(template_id)},
            {"offset_days": 60, "channel": "email"},
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.put(_url(), json=payload)

    assert response.status_code == 200
    assert response.json()["max_touches"] == 1


async def test_high_value_template_from_another_workspace_is_rejected() -> None:
    routine = uuid.uuid4()
    foreign = uuid.uuid4()
    workspace = SimpleNamespace(id=WS_ID, name="Maxteriors", is_active=True, settings={})
    app = _auth_app(workspace, available_template_ids={routine})
    payload = {
        "touches": [
            {
                "offset_days": 30,
                "channel": "sms",
                "template_id": str(routine),
                "high_value_template_id": str(foreign),
            },
        ],
    }

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.put(_url(), json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "Every message template must belong to this workspace"


async def test_offsets_cannot_overlap_the_first_14_days_cadence(auth_client: AsyncClient) -> None:
    response = await auth_client.put(
        _url(),
        json={"touches": [{"offset_days": 14, "channel": "sms"}]},
    )
    assert response.status_code == 422


async def test_all_call_ladder_is_a_422_not_a_500(auth_client: AsyncClient) -> None:
    response = await auth_client.put(
        _url(),
        json={
            "touches": [
                {"offset_days": 30, "channel": "call"},
                {"offset_days": 60, "channel": "call"},
            ]
        },
    )
    assert response.status_code == 422
    assert "automated touch" in response.json()["detail"]


async def test_descending_offsets_are_a_422_not_a_500(auth_client: AsyncClient) -> None:
    response = await auth_client.put(
        _url(),
        json={
            "touches": [
                {"offset_days": 90, "channel": "sms"},
                {"offset_days": 30, "channel": "email"},
            ]
        },
    )
    assert response.status_code == 422
    assert "ascending order" in response.json()["detail"]


async def test_revival_settings_do_not_disturb_the_post_estimate_block() -> None:
    """The two cadences are separate blobs; saving one must not clear the other."""
    workspace = SimpleNamespace(
        id=WS_ID,
        name="Maxteriors",
        is_active=True,
        settings={"post_estimate_followup": {"enabled": True, "high_value_threshold": 9_000}},
    )
    app = _auth_app(workspace)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.put(_url(), json={"high_value_threshold": 4_000})

    assert response.status_code == 200
    assert workspace.settings["post_estimate_followup"]["enabled"] is True
    assert workspace.settings["unsold_quote_revival"]["high_value_threshold"] == 4_000
