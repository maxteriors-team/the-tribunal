"""AI agent CRM assistant tools."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate
from app.services.ai.crm_assistant._pagination import count_matching, listing
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
    without_confirmation,
)
from app.services.ai.crm_assistant._tool_errors import (
    invalid_argument,
    invalid_id,
    not_found,
    validation_failed,
)


class AgentAssistantTools:
    """Read and mutate AI responder agents."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_agents": self.list_agents,
            "get_agent": self.get_agent,
            "create_agent": self.create_agent,
            "update_agent": self.update_agent,
        }

    @staticmethod
    def serialize_agent(agent: Agent) -> dict[str, Any]:
        return {
            "id": str(agent.id),
            "name": agent.name,
            "description": agent.description,
            "channel_mode": agent.channel_mode,
            "voice_provider": agent.voice_provider,
            "voice_id": agent.voice_id,
            "language": agent.language,
            "system_prompt": agent.system_prompt,
            "temperature": agent.temperature,
            "enabled_tools": agent.enabled_tools,
            "is_active": agent.is_active,
        }

    async def get_agent_for_workspace(self, agent_id: uuid.UUID) -> Agent | None:
        return await get_workspace_owned(
            self.context.db,
            Agent,
            agent_id,
            self.context.workspace_id,
        )

    async def list_agents(self, args: ToolArguments) -> dict[str, object]:
        limit = min(args.get("limit", 10), 50)
        stmt = select_workspace_owned(Agent, self.context.workspace_id)

        total = await count_matching(self.context.db, Agent, stmt)
        result = await self.context.db.execute(stmt.order_by(Agent.created_at.desc()).limit(limit))
        agents = result.scalars().all()

        return listing([self.serialize_agent(agent) for agent in agents], total=total)

    async def get_agent(self, args: ToolArguments) -> dict[str, object]:
        agent_id = parse_uuid(args.get("agent_id"))
        if agent_id is None:
            return invalid_id("agent_id", "Call list_agents to get a valid agent id.")

        agent = await self.get_agent_for_workspace(agent_id)
        if agent is None:
            return not_found("Agent", "Call list_agents to get a valid agent id.")

        return {"success": True, "data": self.serialize_agent(agent)}

    async def create_agent(self, args: ToolArguments) -> dict[str, object]:
        try:
            agent_in = AgentCreate(**without_confirmation(args))
        except ValueError as exc:
            return validation_failed("Agent", str(exc))

        agent = Agent(workspace_id=self.context.workspace_id, **agent_in.model_dump())
        self.context.db.add(agent)
        await self.context.db.flush()
        return {"success": True, "data": self.serialize_agent(agent)}

    async def update_agent(self, args: ToolArguments) -> dict[str, object]:
        agent_id = parse_uuid(args.get("agent_id"))
        if agent_id is None:
            return invalid_id("agent_id", "Call list_agents to get a valid agent id.")

        agent = await self.get_agent_for_workspace(agent_id)
        if agent is None:
            return not_found("Agent", "Call list_agents to get a valid agent id.")

        update_args = {
            key: value for key, value in without_confirmation(args).items() if key != "agent_id"
        }
        try:
            agent_in = AgentUpdate(**update_args)
        except ValueError as exc:
            return validation_failed("Agent", str(exc))

        update_data = agent_in.model_dump(exclude_unset=True)
        if not update_data:
            return invalid_argument(
                "No agent fields were provided to update.",
                "Include at least one field to change alongside agent_id.",
            )
        for field, value in update_data.items():
            setattr(agent, field, value)
        await self.context.db.flush()
        return {"success": True, "data": self.serialize_agent(agent)}
