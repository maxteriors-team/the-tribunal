"""Default agent resolution for a workspace.

Inbound SMS/voice need to know which agent owns a conversation when the
receiving phone number has no explicit assignment. This module answers that and
nothing else: it *resolves* an existing agent, it never invents one.

An earlier implementation auto-seeded a canned sales agent into any workspace
that had no agent, including during live inbound traffic. That could put another
business's script in front of real customers and recreate the agent after an
operator deleted it. A CRM must never put words in an operator's mouth, so a
workspace with no agent now simply has no AI responder: the message still lands
in the inbox for a human to answer.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent

logger = structlog.get_logger()


async def get_default_agent(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> Agent | None:
    """Return the workspace's earliest active agent, or ``None`` if it has none.

    Read-only: never creates, never writes, so it is safe on any code path
    including live inbound webhooks.
    """
    result = await db.execute(
        select(Agent)
        .where(
            Agent.workspace_id == workspace_id,
            Agent.is_active.is_(True),
            Agent.deleted_at.is_(None),
        )
        .order_by(Agent.created_at.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()
