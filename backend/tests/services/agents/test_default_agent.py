"""Tests for default-agent resolution.

The contract changed deliberately. This used to seed a canned "Prestyj
Cold-Lead Responder" (a different company's script, pitching a $497 video-ad
package) into any workspace that had no agent -- including from live inbound
webhooks, which meant deleting it just made it come back on the next text.

The rule now: resolve an agent the operator actually created, or none at all.
Never fabricate one, because a fabricated agent speaks to real customers in the
operator's name.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.services.agents import get_default_agent

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _workspace(db) -> Workspace:
    ws = Workspace(id=uuid.uuid4(), name="Agt", slug=f"agt-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    return ws


async def test_workspace_with_no_agent_resolves_to_none_and_creates_nothing() -> None:
    # Pooled connections belong to the previous test's event loop; drop them
    # first (same pattern as tests/integration/test_attendance.py).
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        assert await get_default_agent(db, ws.id) is None

        # The critical regression guard: resolving must never invent an agent.
        # Previously this call seeded one, so an operator could never get rid
        # of it -- deleting it simply re-created it on the next inbound message.
        await db.flush()
        agents = (
            (await db.execute(select(Agent).where(Agent.workspace_id == ws.id))).scalars().all()
        )
        assert agents == []


async def test_resolves_earliest_active_agent_and_skips_deleted_or_paused() -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        ws = await _workspace(db)

        deleted = Agent(
            workspace_id=ws.id,
            name="Deleted",
            system_prompt="x",
            is_active=False,
            deleted_at=datetime.now(UTC),
        )
        paused = Agent(workspace_id=ws.id, name="Paused", system_prompt="x", is_active=False)
        live = Agent(workspace_id=ws.id, name="Live", system_prompt="x", is_active=True)
        db.add_all([deleted, paused, live])
        await db.flush()

        assert (await get_default_agent(db, ws.id)) is not None
        assert (await get_default_agent(db, ws.id)).id == live.id


async def test_does_not_leak_an_agent_across_workspaces() -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        owner = await _workspace(db)
        stranger = await _workspace(db)
        db.add(Agent(workspace_id=owner.id, name="Owned", system_prompt="x", is_active=True))
        await db.flush()

        assert await get_default_agent(db, stranger.id) is None
