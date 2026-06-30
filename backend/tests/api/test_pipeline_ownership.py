"""Integration tests for sales-tier pipeline ownership.

Drives :class:`app.services.opportunities.OpportunityService` against a real DB
(marked ``integration``; run with ``-m integration``). Each test opens an
``AsyncSessionLocal`` and rolls back on close, so the dev database stays clean.

The ``restrict_to_user_id`` argument is what the router derives from
:func:`app.core.permissions.pipeline_owner_scope` — ``None`` for managers/admins
(manage every deal), the caller's own user id for the sales tier (own deals only).
"""

from __future__ import annotations

import uuid

import pytest

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.opportunity import Opportunity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.services.exceptions import NotFoundError
from app.services.opportunities import OpportunityService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Pipeline RBAC", slug=f"pl-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def _user(db) -> User:
    email = f"rep-{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
    )
    db.add(user)
    await db.flush()
    return user


async def _pipeline(db, workspace_id: uuid.UUID) -> tuple[Pipeline, PipelineStage]:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    await db.flush()
    stage = PipelineStage(pipeline_id=pipeline.id, name="New", order=0, probability=10)
    db.add(stage)
    await db.flush()
    return pipeline, stage


async def _opportunity(db, workspace_id, pipeline_id, *, owner_id: int | None) -> Opportunity:
    opp = Opportunity(
        workspace_id=workspace_id,
        pipeline_id=pipeline_id,
        name="Deal",
        assigned_user_id=owner_id,
    )
    db.add(opp)
    await db.flush()
    return opp


# --------------------------------------------------------------------------- #
# Sales tier: own-only
# --------------------------------------------------------------------------- #
async def test_sales_can_act_on_own_but_not_others() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        rep = await _user(db)
        other = await _user(db)
        pipeline, _ = await _pipeline(db, ws.id)
        mine = await _opportunity(db, ws.id, pipeline.id, owner_id=rep.id)
        theirs = await _opportunity(db, ws.id, pipeline.id, owner_id=other.id)
        svc = OpportunityService(db)

        # Read: own ok, other's is 404 (existence not leaked).
        assert (await svc.get_opportunity(ws.id, mine.id, restrict_to_user_id=rep.id)).id == mine.id
        with pytest.raises(NotFoundError):
            await svc.get_opportunity(ws.id, theirs.id, restrict_to_user_id=rep.id)

        # Update: own ok, other's 404.
        updated = await svc.update_opportunity(
            ws.id, mine.id, OpportunityUpdate(name="Renamed"), rep.id, restrict_to_user_id=rep.id
        )
        assert updated.name == "Renamed"
        with pytest.raises(NotFoundError):
            await svc.update_opportunity(
                ws.id, theirs.id, OpportunityUpdate(name="Hijack"), rep.id,
                restrict_to_user_id=rep.id,
            )

        # Delete: other's 404.
        with pytest.raises(NotFoundError):
            await svc.delete_opportunity(ws.id, theirs.id, restrict_to_user_id=rep.id)


async def test_sales_list_is_scoped_to_own_deals() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        rep = await _user(db)
        other = await _user(db)
        pipeline, _ = await _pipeline(db, ws.id)
        await _opportunity(db, ws.id, pipeline.id, owner_id=rep.id)
        await _opportunity(db, ws.id, pipeline.id, owner_id=rep.id)
        await _opportunity(db, ws.id, pipeline.id, owner_id=other.id)
        await db.flush()
        svc = OpportunityService(db)

        scoped = await svc.list_opportunities(ws.id, restrict_to_user_id=rep.id)
        assert scoped.total == 2
        assert all(item.assigned_user_id == rep.id for item in scoped.items)

        # Manager view (no restriction) sees all three.
        unscoped = await svc.list_opportunities(ws.id)
        assert unscoped.total == 3


async def test_sales_create_self_assigns() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        rep = await _user(db)
        pipeline, stage = await _pipeline(db, ws.id)
        svc = OpportunityService(db)

        created = await svc.create_opportunity(
            ws.id,
            OpportunityCreate(name="Self", pipeline_id=pipeline.id, stage_id=stage.id),
            assigned_user_id=rep.id,
        )
        assert created.assigned_user_id == rep.id


async def test_sales_update_cannot_reassign_away() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        rep = await _user(db)
        other = await _user(db)
        pipeline, _ = await _pipeline(db, ws.id)
        mine = await _opportunity(db, ws.id, pipeline.id, owner_id=rep.id)
        svc = OpportunityService(db)

        # A sales rep tries to hand their deal to someone else — ignored; stays theirs.
        result = await svc.update_opportunity(
            ws.id,
            mine.id,
            OpportunityUpdate(assigned_user_id=other.id),
            rep.id,
            restrict_to_user_id=rep.id,
        )
        assert result.assigned_user_id == rep.id


# --------------------------------------------------------------------------- #
# Manager tier: any deal
# --------------------------------------------------------------------------- #
async def test_manager_can_update_any_opportunity() -> None:
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)
        rep = await _user(db)
        pipeline, _ = await _pipeline(db, ws.id)
        theirs = await _opportunity(db, ws.id, pipeline.id, owner_id=rep.id)
        svc = OpportunityService(db)

        # Manager passes restrict_to_user_id=None → no ownership restriction.
        updated = await svc.update_opportunity(
            ws.id, theirs.id, OpportunityUpdate(name="Manager edit"), 999,
            restrict_to_user_id=None,
        )
        assert updated.name == "Manager edit"
