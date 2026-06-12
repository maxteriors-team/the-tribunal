"""Tests for default-agent provisioning.

Covers the first-run promise: every new workspace must resolve to a working,
active AI agent seeded from the Prestyj template without the operator authoring
a prompt, and ``ensure_default_agent`` must be idempotent.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.workspace import Workspace
from app.services.agents import (
    PRESTYJ_COLD_LEAD_RESPONDER_PROMPT,
    ensure_default_agent,
)

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_ensure_default_agent_provisions_and_is_idempotent() -> None:
    async with AsyncSessionLocal() as db:
        ws = Workspace(id=uuid.uuid4(), name="Agt", slug=f"agt-{uuid.uuid4().hex[:8]}")
        db.add(ws)
        await db.flush()

        # First call seeds a working agent from the Prestyj template.
        agent = await ensure_default_agent(db, ws.id)
        await db.flush()
        assert agent.workspace_id == ws.id
        assert agent.is_active is True
        # The seeded agent "just works": it carries a non-empty, usable prompt
        # the operator never had to author.
        assert agent.system_prompt == PRESTYJ_COLD_LEAD_RESPONDER_PROMPT
        assert len(agent.system_prompt) >= 100

        # Second call is idempotent: returns the same agent, creates no duplicate.
        again = await ensure_default_agent(db, ws.id)
        await db.flush()
        assert again.id == agent.id
        all_agents = (
            (await db.execute(select(Agent).where(Agent.workspace_id == ws.id)))
            .scalars()
            .all()
        )
        assert len(all_agents) == 1
