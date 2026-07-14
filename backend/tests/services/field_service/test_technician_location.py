"""Integration tests for tagging technicians to a business location.

Hits the real database (marked ``integration``; deselected by default, run with
``-m integration``). Each test opens an ``AsyncSessionLocal`` and never commits,
so the transaction rolls back on close and the dev database stays clean.

Coverage: assigning a technician to a branch, clearing it, and that a branch id
from another workspace is rejected (tenant isolation).
"""

from __future__ import annotations

import uuid

import pytest

from app.db.session import AsyncSessionLocal, engine
from app.models.workspace import Workspace
from app.services.field_service import (
    BusinessLocationNotFoundError,
    BusinessLocationService,
    TechnicianService,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Biz", slug=f"biz-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def test_create_technician_with_business_location() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        branch = await BusinessLocationService(db).create(ws.id, {"name": "Austin"})
        tech = await TechnicianService(db).create(
            ws.id, {"name": "Sam", "business_location_id": branch.id}
        )
        assert tech.business_location_id == branch.id


async def test_update_technician_assigns_and_clears_location() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        branch = await BusinessLocationService(db).create(ws.id, {"name": "Austin"})
        service = TechnicianService(db)
        tech = await service.create(ws.id, {"name": "Sam"})
        assert tech.business_location_id is None

        assigned = await service.update(
            tech.id, ws.id, {"business_location_id": branch.id}
        )
        assert assigned.business_location_id == branch.id

        cleared = await service.update(tech.id, ws.id, {"business_location_id": None})
        assert cleared.business_location_id is None


async def test_cross_workspace_location_is_rejected() -> None:
    async with AsyncSessionLocal() as db:
        ws_a = await _workspace(db)
        ws_b = await _workspace(db)
        # A branch owned by workspace B…
        branch_b = await BusinessLocationService(db).create(ws_b.id, {"name": "Dallas"})
        # …cannot be assigned to a technician in workspace A.
        with pytest.raises(BusinessLocationNotFoundError):
            await TechnicianService(db).create(
                ws_a.id, {"name": "Sam", "business_location_id": branch_b.id}
            )
