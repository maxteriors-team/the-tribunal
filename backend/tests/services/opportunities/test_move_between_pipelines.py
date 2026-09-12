"""Moving a deal to a stage in another pipeline, and refusing another tenant's.

Context: the board had no move control, only "add". Operators moved a contact by
adding a second card, and on 2026-09-10 that duplicate fired a "New Lead —
Welcome Text" at an already-quoted customer. The trigger was fixed separately;
this covers the move that should have existed instead.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.opportunity import Opportunity, OpportunityActivity
from app.models.pipeline import Pipeline, PipelineStage
from app.models.workspace import Workspace
from app.schemas.opportunity import OpportunityCreate, OpportunityUpdate
from app.services.exceptions import NotFoundError
from app.services.opportunities.opportunity_service import OpportunityService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool() -> AsyncIterator[None]:
    await engine.dispose()
    yield
    await engine.dispose()


async def _workspace(db: AsyncSession, name: str) -> Workspace:
    workspace = Workspace(id=uuid.uuid4(), name=name, slug=f"mv-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    await db.flush()
    return workspace


async def _pipeline(
    db: AsyncSession, workspace_id: uuid.UUID, name: str
) -> tuple[Pipeline, PipelineStage, PipelineStage]:
    pipeline = Pipeline(workspace_id=workspace_id, name=name)
    db.add(pipeline)
    await db.flush()
    entry = PipelineStage(pipeline_id=pipeline.id, name=f"{name} entry", order=0, probability=10)
    later = PipelineStage(pipeline_id=pipeline.id, name=f"{name} later", order=1, probability=60)
    db.add_all([entry, later])
    await db.flush()
    return pipeline, entry, later


async def _activity_types(db: AsyncSession, opportunity_id: uuid.UUID) -> list[str]:
    rows = await db.execute(
        select(OpportunityActivity.activity_type).where(
            OpportunityActivity.opportunity_id == opportunity_id
        )
    )
    return list(rows.scalars())


async def test_moving_to_another_pipelines_stage_moves_the_deal_with_it() -> None:
    """The card must not keep a pipeline that does not contain its stage."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Main")
        sales, sales_entry, _ = await _pipeline(db, workspace.id, "Sales")
        service_pipeline, service_entry, _ = await _pipeline(db, workspace.id, "Service")
        service_api = OpportunityService(db)

        created = await service_api.create_opportunity(
            workspace.id,
            OpportunityCreate(name="Gutter job", pipeline_id=sales.id, stage_id=sales_entry.id),
        )

        moved = await service_api.update_opportunity(
            workspace.id,
            created.id,
            OpportunityUpdate(stage_id=service_entry.id),
            user_id=1,
        )

        assert moved.stage_id == service_entry.id
        assert moved.pipeline_id == service_pipeline.id

        row = await db.get(Opportunity, created.id)
        assert row is not None
        assert row.pipeline_id == service_pipeline.id
        assert row.probability == service_entry.probability

        types = await _activity_types(db, created.id)
        assert "pipeline_changed" in types
        assert "stage_changed" in types


async def test_moving_within_one_pipeline_logs_no_pipeline_change() -> None:
    """Board drag-and-drop must not start writing pipeline_changed noise."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Main")
        sales, entry, later = await _pipeline(db, workspace.id, "Sales")
        service_api = OpportunityService(db)

        created = await service_api.create_opportunity(
            workspace.id,
            OpportunityCreate(name="Roof wash", pipeline_id=sales.id, stage_id=entry.id),
        )

        moved = await service_api.update_opportunity(
            workspace.id,
            created.id,
            OpportunityUpdate(stage_id=later.id),
            user_id=1,
        )

        assert moved.pipeline_id == sales.id
        assert "pipeline_changed" not in await _activity_types(db, created.id)


async def test_a_stage_from_another_workspace_is_refused() -> None:
    """Cross-tenant write: the stage must belong to the caller's workspace."""
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Main")
        other = await _workspace(db, "Other tenant")
        sales, entry, _ = await _pipeline(db, workspace.id, "Sales")
        _, foreign_stage, _ = await _pipeline(db, other.id, "Their pipeline")
        service_api = OpportunityService(db)

        created = await service_api.create_opportunity(
            workspace.id,
            OpportunityCreate(name="Lighting", pipeline_id=sales.id, stage_id=entry.id),
        )

        with pytest.raises(NotFoundError):
            await service_api.update_opportunity(
                workspace.id,
                created.id,
                OpportunityUpdate(stage_id=foreign_stage.id),
                user_id=1,
            )

        row = await db.get(Opportunity, created.id)
        assert row is not None
        assert row.stage_id == entry.id
        assert row.pipeline_id == sales.id


async def test_creating_with_a_stage_outside_the_chosen_pipeline_is_refused() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Main")
        sales, _, _ = await _pipeline(db, workspace.id, "Sales")
        _, service_entry, _ = await _pipeline(db, workspace.id, "Service")

        with pytest.raises(NotFoundError):
            await OpportunityService(db).create_opportunity(
                workspace.id,
                OpportunityCreate(
                    name="Mismatched", pipeline_id=sales.id, stage_id=service_entry.id
                ),
            )
