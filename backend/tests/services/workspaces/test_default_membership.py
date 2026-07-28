"""A user must have at most one default workspace membership.

``POST /api/v1/workspaces`` used to flag its new membership ``is_default=True``
without clearing the caller's previous default, so anyone who created a second
workspace ended up with two default rows. The resolvers behind
``/api/v1/onboarding/*`` and ``/api/v1/billing/*`` asked for "the" default with
an unbounded ``scalar_one_or_none()`` and raised ``MultipleResultsFound`` —
a 500 on every one of those routes.

These tests pin all three halves of the fix: writers promote through
:func:`set_default_membership` (clear-then-set), the database enforces the
invariant with a partial unique index, and readers stay deterministic.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.api.v1.workspaces import create_workspace, set_default_workspace
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.workspace import WorkspaceCreate
from app.services.workspaces import (
    ensure_personal_workspace,
    resolve_active_membership,
    set_default_membership,
)

# Hits the real database (the invariant is enforced by a Postgres partial unique
# index), so it is an integration test: run with `-m integration`.
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_user(db) -> User:
    user = User(
        email=f"default-ws-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=get_password_hash("password123"),
        full_name="Default Probe",
    )
    db.add(user)
    await db.flush()
    return user


async def _default_count(db, user_id: int) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(WorkspaceMembership)
            .where(
                WorkspaceMembership.user_id == user_id,
                WorkspaceMembership.is_default.is_(True),
            )
        )
    ).scalar_one()


async def test_creating_a_second_workspace_moves_the_default_instead_of_adding_one() -> None:
    """The reported 500: register, then create a workspace via the API."""
    async with AsyncSessionLocal() as db:
        user = await _make_user(db)
        personal = await ensure_personal_workspace(db, user)
        await db.commit()

        created = await create_workspace(
            workspace_in=WorkspaceCreate(
                name="Second Workspace",
                slug=f"second-ws-{uuid.uuid4().hex[:8]}",
            ),
            current_user=user,
            db=db,
        )

        assert await _default_count(db, user.id) == 1
        # The endpoint's intent is preserved: the new workspace is the default.
        active = await resolve_active_membership(user.id, db)
        assert active is not None
        assert active.workspace_id == created.id
        assert active.workspace_id != personal.id


async def test_resolve_active_membership_no_longer_raises_for_this_user() -> None:
    """Onboarding/billing resolution must survive a user with several workspaces."""
    async with AsyncSessionLocal() as db:
        user = await _make_user(db)
        await ensure_personal_workspace(db, user)
        await db.commit()

        for index in range(2):
            await create_workspace(
                workspace_in=WorkspaceCreate(
                    name=f"Workspace {index}",
                    slug=f"ws-{index}-{uuid.uuid4().hex[:8]}",
                ),
                current_user=user,
                db=db,
            )

        # Previously raised MultipleResultsFound -> HTTP 500.
        membership = await resolve_active_membership(user.id, db)
        assert membership is not None
        assert await _default_count(db, user.id) == 1


async def test_set_default_flip_does_not_transiently_break_the_unique_index() -> None:
    """Moving a default must clear before promoting.

    The partial unique index is not deferrable, so a promote-then-clear (or an
    ORM flush ordering its UPDATEs arbitrarily) fails mid-transaction.
    """
    async with AsyncSessionLocal() as db:
        user = await _make_user(db)
        first = await ensure_personal_workspace(db, user)
        await db.commit()

        second = await create_workspace(
            workspace_in=WorkspaceCreate(
                name="Flip Target",
                slug=f"flip-{uuid.uuid4().hex[:8]}",
            ),
            current_user=user,
            db=db,
        )

        workspace = (
            await db.execute(select(Workspace).where(Workspace.id == first.id))
        ).scalar_one()
        membership = (
            await db.execute(
                select(WorkspaceMembership).where(
                    WorkspaceMembership.user_id == user.id,
                    WorkspaceMembership.workspace_id == first.id,
                )
            )
        ).scalar_one()

        result = await set_default_workspace(
            workspace=workspace,
            membership=membership,
            db=db,
        )

        assert result.is_default is True
        assert result.workspace.id == first.id
        assert await _default_count(db, user.id) == 1
        active = await resolve_active_membership(user.id, db)
        assert active is not None
        assert active.workspace_id == first.id
        assert active.workspace_id != second.id


async def test_set_default_membership_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        user = await _make_user(db)
        workspace = await ensure_personal_workspace(db, user)
        await db.commit()

        await set_default_membership(db, user.id, workspace.id)
        await set_default_membership(db, user.id, workspace.id)
        await db.commit()

        assert await _default_count(db, user.id) == 1
