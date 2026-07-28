"""Both workspace-creation paths must agree on "needs onboarding" (finding RF-002).

Setup state used to be inferred from "does this workspace have zero AI agents?".
``POST /api/v1/workspaces`` seeds a template agent at creation time and
``ensure_personal_workspace`` (registration) does not, so a workspace's
onboarding state was decided by *which code path created it* rather than by
whether the operator configured anything: UI-created workspaces reported
"configured" seconds after birth and could never reach the wizard, while
registration-created ones were prompted until any agent existed.

These tests pin the explicit signal instead: ``Workspace.onboarding_completed_at``
is ``NULL`` out of both creation paths (seeded rows notwithstanding) and is set
only when the onboarding wizard completes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.api.v1.workspaces import create_workspace
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.user import User
from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate
from app.services.onboarding.workspace_setup import mark_onboarding_complete
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


async def _make_user(db) -> User:
    user = User(
        email=f"rf002-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=get_password_hash("password123"),
        full_name="Onboarding Probe",
    )
    db.add(user)
    await db.flush()
    return user


async def test_ui_created_workspace_is_seeded_an_agent_yet_still_needs_setup() -> None:
    """The reported repro: create via the API, then probe the workspace.

    The seeded agent is present (that behaviour is intentional so ``/agents``
    works on first run) but must not read as "the operator finished setup".
    """
    async with AsyncSessionLocal() as db:
        user = await _make_user(db)
        await db.commit()

        suffix = uuid.uuid4().hex[:8]
        response = await create_workspace(
            workspace_in=WorkspaceCreate(
                name="QA Fresh Workspace Probe",
                slug=f"qa-fresh-probe-{suffix}",
            ),
            current_user=user,
            db=db,
        )

        agents = (
            (await db.execute(select(Agent).where(Agent.workspace_id == response.id)))
            .scalars()
            .all()
        )
        assert len(agents) == 1, "creation still seeds a working default agent"
        assert response.onboarding_completed_at is None, (
            "a workspace seconds old and never configured must be offered onboarding"
        )


async def test_registration_created_workspace_also_needs_setup() -> None:
    """The other creation path must answer the same question the same way."""
    async with AsyncSessionLocal() as db:
        user = await _make_user(db)

        workspace = await ensure_personal_workspace(db, user)
        await db.flush()

        assert workspace.onboarding_completed_at is None


async def test_completing_onboarding_flips_the_signal_and_persists() -> None:
    async with AsyncSessionLocal() as db:
        workspace = Workspace(
            id=uuid.uuid4(),
            name="Onboarded",
            slug=f"onboarded-{uuid.uuid4().hex[:8]}",
        )
        db.add(workspace)
        await db.flush()
        assert workspace.onboarding_completed_at is None

        mark_onboarding_complete(workspace, now=lambda: datetime.now(UTC))
        await db.commit()

    async with AsyncSessionLocal() as db:
        reloaded = (
            await db.execute(select(Workspace).where(Workspace.id == workspace.id))
        ).scalar_one()
        assert reloaded.onboarding_completed_at is not None
