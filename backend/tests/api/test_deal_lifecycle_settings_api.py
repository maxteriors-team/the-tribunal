"""Contract tests for workspace-scoped deal lifecycle configuration."""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1 import settings as settings_module

WS_ID = uuid.uuid4()
PIPELINE_ID = uuid.uuid4()
STAGE_IDS = [uuid.uuid4() for _ in range(8)]
ASSIGNEE_ID = 42


@asynccontextmanager
async def _test_lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


class _Result:
    def __init__(self, values: set[Any]) -> None:
        self.values = values

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return list(self.values)

    def scalar_one_or_none(self) -> Any | None:
        if not self.values:
            return None
        if len(self.values) != 1:
            raise AssertionError("Expected at most one scalar result")
        return next(iter(self.values))


def _workspace(settings: dict[str, Any] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=WS_ID,
        name="Maxteriors",
        is_active=True,
        settings=settings or {},
    )


def _payload() -> dict[str, Any]:
    keys = (
        "new_lead_stage_id",
        "contacted_no_answer_stage_id",
        "visit_demo_scheduled_stage_id",
        "qualified_stage_id",
        "quote_follow_up_stage_id",
        "won_stage_id",
        "job_completed_stage_id",
        "unqualified_stage_id",
    )
    return {
        "pipeline_id": str(PIPELINE_ID),
        **{key: str(stage_id) for key, stage_id in zip(keys, STAGE_IDS, strict=True)},
        "follow_up_assignee_user_id": ASSIGNEE_ID,
        "end_of_day_cutoff": "16:30",
    }


def _app(
    workspace: SimpleNamespace,
    *,
    owned_stage_ids: set[uuid.UUID] | None = None,
    active_member_ids: set[int] | None = None,
    role: str = "owner",
) -> tuple[FastAPI, AsyncMock]:
    app = FastAPI(lifespan=_test_lifespan)
    db = AsyncMock()
    results = [
        _Result(owned_stage_ids or set()),
        _Result(active_member_ids or set()),
    ]

    async def execute(_statement: object) -> _Result:
        if not results:
            raise AssertionError("Unexpected database query")
        return results.pop(0)

    db.execute = AsyncMock(side_effect=execute)

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
        role=role,
        workspace_id=WS_ID,
    )
    app.include_router(settings_module.router, prefix="/api/v1")
    return app, db


def _url() -> str:
    return f"/api/v1/workspaces/{WS_ID}/deal-lifecycle"


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    )


async def test_get_returns_unconfigured_fail_closed_default() -> None:
    app, _db = _app(_workspace())
    async with _client(app) as client:
        response = await client.get(_url())

    assert response.status_code == 200
    assert response.json()["pipeline_id"] is None
    assert response.json()["follow_up_assignee_user_id"] is None
    assert response.json()["end_of_day_cutoff"] == "17:00:00"


async def test_put_validates_and_round_trips_owned_resources() -> None:
    workspace = _workspace({"neighbor_setting": {"enabled": True}})
    app, db = _app(
        workspace,
        owned_stage_ids=set(STAGE_IDS),
        active_member_ids={ASSIGNEE_ID},
    )
    async with _client(app) as client:
        response = await client.put(_url(), json=_payload())
        fetched = await client.get(_url())

    assert response.status_code == 200
    assert response.json()["pipeline_id"] == str(PIPELINE_ID)
    assert response.json()["end_of_day_cutoff"] == "16:30:00"
    assert fetched.json() == response.json()
    assert workspace.settings["neighbor_setting"] == {"enabled": True}
    assert workspace.settings["deal_lifecycle"]["pipeline_id"] == str(PIPELINE_ID)
    assert db.execute.await_count == 2
    db.commit.assert_awaited_once()


async def test_pipeline_or_stage_outside_workspace_is_rejected_without_writing() -> None:
    workspace = _workspace()
    app, db = _app(
        workspace,
        owned_stage_ids=set(STAGE_IDS[:-1]),
        active_member_ids={ASSIGNEE_ID},
    )
    async with _client(app) as client:
        response = await client.put(_url(), json=_payload())

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Lifecycle pipeline and stages must belong to this workspace"
    )
    assert "deal_lifecycle" not in workspace.settings
    db.commit.assert_not_awaited()
    assert db.execute.await_count == 1


async def test_assignee_outside_workspace_or_inactive_is_rejected_without_writing() -> None:
    workspace = _workspace()
    app, db = _app(workspace, owned_stage_ids=set(STAGE_IDS))
    async with _client(app) as client:
        response = await client.put(_url(), json=_payload())

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Follow-up assignee must be an active member of this workspace"
    )
    assert "deal_lifecycle" not in workspace.settings
    db.commit.assert_not_awaited()


async def test_malformed_mapping_is_rejected_before_database_access() -> None:
    workspace = _workspace()
    app, db = _app(workspace)
    duplicate_payload = _payload()
    duplicate_payload["won_stage_id"] = duplicate_payload["qualified_stage_id"]

    async with _client(app) as client:
        duplicate = await client.put(_url(), json=duplicate_payload)
        partial = await client.put(
            _url(),
            json={"pipeline_id": str(PIPELINE_ID), "end_of_day_cutoff": "17:00"},
        )
        zoned_cutoff_payload = _payload()
        zoned_cutoff_payload["end_of_day_cutoff"] = "16:30Z"
        zoned_cutoff = await client.put(_url(), json=zoned_cutoff_payload)

    assert duplicate.status_code == 422
    assert partial.status_code == 422
    assert zoned_cutoff.status_code == 422
    db.execute.assert_not_awaited()


async def test_sales_rep_can_read_but_cannot_change_shared_lifecycle() -> None:
    app, db = _app(_workspace(), role="sales_rep")
    async with _client(app) as client:
        fetched = await client.get(_url())
        updated = await client.put(_url(), json=_payload())

    assert fetched.status_code == 200
    assert updated.status_code == 403
    db.execute.assert_not_awaited()


async def test_corrupt_stored_blob_fails_closed() -> None:
    app, _db = _app(_workspace({"deal_lifecycle": {"pipeline_id": "not-a-uuid"}}))
    async with _client(app) as client:
        response = await client.get(_url())

    assert response.status_code == 200
    assert response.json()["pipeline_id"] is None
    assert response.json()["follow_up_assignee_user_id"] is None
