"""Default agent provisioning for workspaces.

A brand-new workspace should have a working AI follow-up agent without the
operator having to author a 100+ character system prompt from scratch in the
agents wizard. This module seeds a sensible default agent from the existing
production-grade Prestyj cold-lead responder template so the self-serve
``/agents`` experience "just works" on first run.

Mirrors :mod:`app.services.opportunities.default_pipeline`: idempotent, flushes
but does not commit (the caller owns the transaction), and is safe to call
repeatedly (e.g. from workspace creation or a future backfill).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.services.agents.templates import build_prestyj_cold_lead_responder_template

logger = structlog.get_logger()


async def ensure_default_agent(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> Agent:
    """Return the workspace's first active agent, creating a default if absent.

    Idempotent: if any active agent already exists, the earliest (by
    ``created_at``) is returned unchanged. Otherwise a default agent is created
    from the Prestyj cold-lead responder template. Flushes but does not commit —
    the caller owns the transaction.
    """
    existing = await db.execute(
        select(Agent)
        .where(Agent.workspace_id == workspace_id, Agent.is_active.is_(True))
        .order_by(Agent.created_at.asc())
        .limit(1)
    )
    agent = existing.scalar_one_or_none()
    if agent is not None:
        return agent

    template = build_prestyj_cold_lead_responder_template()
    agent = Agent(workspace_id=workspace_id, **template.model_dump())
    db.add(agent)
    await db.flush()

    logger.info(
        "default_agent_provisioned",
        workspace_id=str(workspace_id),
        agent_id=str(agent.id),
    )
    return agent
