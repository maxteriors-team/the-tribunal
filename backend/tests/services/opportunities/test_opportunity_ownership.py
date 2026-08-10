"""Tenant and role ownership behavior for opportunities."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.db.session import AsyncSessionLocal, engine
from app.models.pipeline import Pipeline, PipelineStage
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
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
    workspace = Workspace(id=uuid.uuid4(), name=name, slug=f"own-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    await db.flush()
    return workspace


async def _member(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    name: str,
    *,
    role: str = "sales_rep",
    is_active: bool = True,
) -> User:
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password="x",
        full_name=name,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role=role))
    await db.flush()
    return user


async def _pipeline(db: AsyncSession, workspace_id: uuid.UUID) -> tuple[Pipeline, PipelineStage]:
    pipeline = Pipeline(workspace_id=workspace_id, name="Sales")
    db.add(pipeline)
    await db.flush()
    stage = PipelineStage(pipeline_id=pipeline.id, name="Qualified", probability=40)
    db.add(stage)
    await db.flush()
    return pipeline, stage


async def test_manager_can_select_update_and_clear_active_owner() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Main")
        other_workspace = await _workspace(db, "Other")
        owner = await _member(db, workspace.id, "First owner")
        next_owner = await _member(db, workspace.id, "Next owner")
        foreign_owner = await _member(db, other_workspace.id, "Foreign owner")
        inactive_owner = await _member(db, workspace.id, "Inactive owner", is_active=False)
        pipeline, stage = await _pipeline(db, workspace.id)
        service = OpportunityService(db)

        created = await service.create_opportunity(
            workspace.id,
            OpportunityCreate(
                name="Window cleaning",
                pipeline_id=pipeline.id,
                stage_id=stage.id,
                assigned_user_id=owner.id,
            ),
        )
        assert created.assigned_user_id == owner.id
        assert created.assignee is not None
        assert created.assignee.full_name == "First owner"

        updated = await service.update_opportunity(
            workspace.id,
            created.id,
            OpportunityUpdate(assigned_user_id=next_owner.id),
            user_id=owner.id,
        )
        assert updated.assigned_user_id == next_owner.id

        cleared = await service.update_opportunity(
            workspace.id,
            created.id,
            OpportunityUpdate(assigned_user_id=None),
            user_id=owner.id,
        )
        assert cleared.assigned_user_id is None
        assert cleared.assignee is None

        for invalid_owner_id in (foreign_owner.id, inactive_owner.id):
            with pytest.raises(NotFoundError):
                await service.update_opportunity(
                    workspace.id,
                    created.id,
                    OpportunityUpdate(assigned_user_id=invalid_owner_id),
                    user_id=owner.id,
                )


async def test_sales_scope_forces_self_over_client_selected_owner() -> None:
    async with AsyncSessionLocal() as db:
        workspace = await _workspace(db, "Main")
        sales_rep = await _member(db, workspace.id, "Sales rep")
        manager = await _member(db, workspace.id, "Manager", role="admin")
        pipeline, stage = await _pipeline(db, workspace.id)

        created = await OpportunityService(db).create_opportunity(
            workspace.id,
            OpportunityCreate(
                name="Gutter guards",
                pipeline_id=pipeline.id,
                stage_id=stage.id,
                assigned_user_id=manager.id,
            ),
            assigned_user_id=sales_rep.id,
        )

        assert created.assigned_user_id == sales_rep.id
        assert created.assignee is not None
        assert created.assignee.full_name == "Sales rep"
