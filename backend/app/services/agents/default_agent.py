"""Default agent provisioning for workspaces.

A new workspace receives a neutral lead-response agent without requiring the
operator to write a system prompt. The caller owns the transaction.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.schemas.agent import AgentCreate

logger = structlog.get_logger()

DEFAULT_AGENT_PROMPT = """
You are the lead-response assistant for the business using this CRM.

Respond to inbound SMS and chat leads, understand what they need, and help them take
the next appropriate step.

Core rules:
- Keep replies concise, natural, and focused on the lead's latest message.
- Use only business details, services, prices, and offers provided in this conversation
  or the configured knowledge base. Never invent missing facts.
- Ask one useful question at a time.
- Offer appointment booking only when the lead wants it or is clearly ready.
- Hand off to a human when the lead requests one or needs information you do not have.
- Respect opt-outs immediately. Do not continue selling after a stop request.
- Never claim to be human, promise outcomes, or pressure the lead.
"""


async def ensure_default_agent(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> Agent:
    """Return the workspace's first active agent, creating a neutral default if absent."""
    existing = await db.execute(
        select(Agent)
        .where(Agent.workspace_id == workspace_id, Agent.is_active.is_(True))
        .order_by(Agent.created_at.asc())
        .limit(1)
    )
    agent = existing.scalar_one_or_none()
    if agent is not None:
        return agent

    template = AgentCreate(
        name="Lead Response Assistant",
        description="General inbound lead qualification and appointment booking.",
        channel_mode="text",
        system_prompt=DEFAULT_AGENT_PROMPT,
        temperature=0.45,
        text_response_delay_ms=30_000,
        text_max_context_messages=24,
        enabled_tools=[
            "web_search",
            "book_appointment",
            "human_handoff",
            "crm_update",
        ],
        tool_settings={
            "calendar": ["check_availability", "book_appointment"],
            "crm": ["update_contact", "tag_contact", "create_opportunity"],
            "handoff": ["warm_lead", "high_intent", "human_review"],
            "messaging": ["sms", "chat"],
        },
        noshow_reengagement_enabled=False,
        never_booked_reengagement_enabled=False,
    )
    agent = Agent(workspace_id=workspace_id, **template.model_dump())
    db.add(agent)
    await db.flush()

    logger.info(
        "default_agent_provisioned",
        workspace_id=str(workspace_id),
        agent_id=str(agent.id),
    )
    return agent
