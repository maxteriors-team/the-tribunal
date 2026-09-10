"""Tests for neutral default-agent provisioning.

Every new workspace receives a usable agent without requiring an operator-authored
prompt, and ``ensure_default_agent`` remains idempotent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.services.agents import ensure_default_agent
from app.services.agents.default_agent import DEFAULT_AGENT_PROMPT

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_ensure_default_agent_provisions_and_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Agt", slug=f"agt-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        # First call seeds a neutral, working agent.
        agent = await ensure_default_agent(db, ws.id)
        await db.flush()
        assert agent.workspace_id == ws.id
        assert agent.is_active is True
        assert agent.name == "Lead Response Assistant"
        assert agent.system_prompt == DEFAULT_AGENT_PROMPT
        assert len(agent.system_prompt) >= 100
        assert agent.noshow_reengagement_enabled is False

        # Second call is idempotent: returns the same agent, creates no duplicate.
        again = await ensure_default_agent(db, ws.id)
        await db.flush()
        assert again.id == agent.id
        all_agents = (
            (await db.execute(select(Agent).where(Agent.workspace_id == ws.id))).scalars().all()
        )
        assert len(all_agents) == 1
