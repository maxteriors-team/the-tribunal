"""Integration tests for :class:`app.services.field_service.BusinessLocationService`.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: CRUD, the active-state list filter, the ``(workspace_id, name)`` unique
conflict, cross-workspace 404s, and that the same branch name is reusable across
different workspaces.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.services.field_service import (
    BusinessLocationNameConflictError,
    BusinessLocationNotFoundError,
    BusinessLocationService,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the asyncpg pool around each test to avoid closed-loop reuse."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Biz", slug=f"biz-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def test_create_defaults_and_fields() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        loc = await BusinessLocationService(db).create(
            ws.id, {"name": "Austin", "city": "Austin", "state": "TX"}
        )
        assert loc.name == "Austin"
        assert loc.workspace_id == ws.id
        assert loc.is_active is True
        assert loc.timezone == "UTC"
        assert loc.business_hours == {}
        assert loc.country == "US"
        assert loc.city == "Austin"


async def test_list_and_active_filter() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = BusinessLocationService(db)
        await service.create(ws.id, {"name": "Austin"})
        await service.create(ws.id, {"name": "Dallas", "is_active": False})

        every = await service.list(ws.id)
        assert every["total"] == 2
        assert [item.name for item in every["items"]] == ["Austin", "Dallas"]

        active = await service.list(ws.id, is_active=True)
        assert [item.name for item in active["items"]] == ["Austin"]

        inactive = await service.list(ws.id, is_active=False)
        assert [item.name for item in inactive["items"]] == ["Dallas"]


async def test_get_update_delete_roundtrip() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = BusinessLocationService(db)
        created = await service.create(ws.id, {"name": "Austin"})

        fetched = await service.get(created.id, ws.id)
        assert fetched.id == created.id

        updated = await service.update(
            created.id, ws.id, {"name": "Austin HQ", "timezone": "America/Chicago"}
        )
        assert updated.name == "Austin HQ"
        assert updated.timezone == "America/Chicago"

        await service.delete(created.id, ws.id)
        # ``AsyncSessionLocal`` has autoflush off (the API's transaction boundary
        # flushes/commits); flush here so the pending DELETE hits the DB before
        # we assert the row is gone.
        await db.flush()
        with pytest.raises(BusinessLocationNotFoundError):
            await service.get(created.id, ws.id)


async def test_duplicate_name_in_workspace_conflicts() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        service = BusinessLocationService(db)
        await service.create(ws.id, {"name": "Austin"})
        with pytest.raises(BusinessLocationNameConflictError):
            await service.create(ws.id, {"name": "Austin"})


async def test_same_name_across_workspaces_is_allowed() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        service = BusinessLocationService(db)
        a = await service.create(ws_a.id, {"name": "Austin"})
        b = await service.create(ws_b.id, {"name": "Austin"})
        assert a.id != b.id


async def test_cross_workspace_access_is_404() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        service = BusinessLocationService(db)
        loc = await service.create(ws_a.id, {"name": "Austin"})
        # Another workspace cannot see or mutate this branch.
        with pytest.raises(BusinessLocationNotFoundError):
            await service.get(loc.id, ws_b.id)
        with pytest.raises(BusinessLocationNotFoundError):
            await service.update(loc.id, ws_b.id, {"name": "Nope"})
        with pytest.raises(BusinessLocationNotFoundError):
            await service.delete(loc.id, ws_b.id)
