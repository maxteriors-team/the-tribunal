"""Tests for agent deletion.

Covers the operator promise: a deleted agent disappears from the AI Agents page
for good. Before ``deleted_at`` existed, delete only cleared ``is_active``, so
the card came straight back as "Inactive" because the page lists inactive agents
too -- indistinguishable from an agent the operator had merely paused.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal, engine
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.schemas.agent import AgentUpdate
from app.services.agents import AgentService

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _seed(db: AsyncSession, name: str) -> tuple[Workspace, Agent]:
    ws = Workspace(id=uuid.uuid4(), name="Del", slug=f"del-{uuid.uuid4().hex[:8]}")
    db.add(ws)
    await db.flush()
    agent = Agent(workspace_id=ws.id, name=name, system_prompt="x")
    db.add(agent)
    await db.flush()
    return ws, agent


async def test_deleted_agent_is_hidden_even_when_listing_inactive() -> None:
    # Pooled connections belong to the previous test's event loop; drop them
    # first (same pattern as tests/integration/test_attendance.py).
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        ws, deleted = await _seed(db, "Prestyj Cold-Lead Responder")
        paused = Agent(workspace_id=ws.id, name="Paused", system_prompt="x", is_active=False)
        db.add(paused)
        await db.flush()

        service = AgentService(db)
        await service.delete_agent(ws.id, deleted.id)

        # active_only=False is what the AI Agents page sends: it must still show
        # the paused agent, and must not show the deleted one.
        listed = await service.list_agents(ws.id, active_only=False)
        names = {a.id for a in listed.items}
        assert deleted.id not in names
        assert paused.id in names

        # The row survives so historical calls/conversations still resolve it.
        assert await db.get(Agent, deleted.id) is not None


async def test_deleted_agent_is_not_readable_or_editable() -> None:
    await engine.dispose()
    async with AsyncSessionLocal() as db:
        ws, agent = await _seed(db, "Gone")
        service = AgentService(db)
        await service.delete_agent(ws.id, agent.id)

        with pytest.raises(HTTPException) as read_exc:
            await service.get_agent(ws.id, agent.id)
        assert read_exc.value.status_code == 404

        # No resurrection by flipping is_active back on.
        with pytest.raises(HTTPException) as write_exc:
            await service.update_agent(ws.id, agent.id, AgentUpdate(is_active=True))
        assert write_exc.value.status_code == 404
