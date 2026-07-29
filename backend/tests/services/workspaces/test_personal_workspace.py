"""Tests for personal-workspace provisioning (finding RF-001).

Every new/first-login user must resolve to a usable default workspace with an
owner membership and a default pipeline, otherwise the dashboard freezes on its
loading skeleton. ``ensure_personal_workspace`` must be idempotent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.pipeline import Pipeline
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.workspaces import ensure_personal_workspace

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_user(db, full_name: str | None) -> User:
    user = User(
        email=f"rf001-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=get_password_hash("password123"),
        full_name=full_name,
    )
    db.add(user)
    await db.flush()
    return user


async def test_ensure_personal_workspace_provisions_owner_membership_and_pipeline() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, "Jane Doe")

        workspace = await ensure_personal_workspace(db, user)
        await db.flush()

        assert workspace.name == "Jane's Workspace"
        assert workspace.is_active is True

        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.workspace_id == workspace.id,
                )
            )
        ).scalar_one()
        assert membership.role == "owner"
        assert membership.is_default is True

        pipelines = (
            (await db.execute(select(Pipeline).where(Pipeline.workspace_id == workspace.id)))
            .scalars()
            .all()
        )
        assert len(pipelines) == 1


async def test_ensure_personal_workspace_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, None)

        first = await ensure_personal_workspace(db, user)
        await db.flush()
        # No full_name falls back to the generic personal-workspace name.
        assert first.name == "My Workspace"

        again = await ensure_personal_workspace(db, user)
        await db.flush()
        assert again.id == first.id

        memberships = (
            (
                await db.execute(
                    select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(memberships) == 1


async def test_ensure_personal_workspace_returns_existing_default() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, "Existing Owner")
        ws = Workspace(id=uuid.uuid4(), name="Existing", slug=f"existing-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()
        db.add(
            WorkspaceMembership(user_id=user.id, workspace_id=ws.id, role="owner", is_default=True)
        )
        await db.flush()

        resolved = await ensure_personal_workspace(db, user)
        assert resolved.id == ws.id
