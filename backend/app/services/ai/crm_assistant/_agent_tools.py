"""AI agent CRM assistant tools."""

from __future__ import annotations

import uuid
from typing import Any

from app.db.scope import get_workspace_owned, select_workspace_owned
from app.models.agent import Agent
from app.schemas.agent import AgentCreate, AgentUpdate
from app.services.ai.crm_assistant._tool_context import (
    CRMToolContext,
    ToolArguments,
    ToolHandler,
    parse_uuid,
    without_confirmation,
)


class AgentAssistantTools:
    """Read and mutate AI responder agents."""

    def __init__(self, context: CRMToolContext) -> None:
        self.context = context

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_agents": self.list_agents,
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
        stmt = (
            select_workspace_owned(Agent, self.context.workspace_id)
            .order_by(Agent.created_at.desc())
            .limit(limit)
        )
        result = await self.context.db.execute(stmt)
        agents = result.scalars().all()

        return {
            "success": True,
            "data": [
                {
                    "id": str(agent.id),
                    "name": agent.name,
                    "channel_mode": agent.channel_mode,
                    "is_active": agent.is_active,
                }
                for agent in agents
            ],
            "count": len(agents),
        }

    async def create_agent(self, args: ToolArguments) -> dict[str, object]:
        try:
            agent_in = AgentCreate(**without_confirmation(args))
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        agent = Agent(workspace_id=self.context.workspace_id, **agent_in.model_dump())
        self.context.db.add(agent)
        await self.context.db.flush()
        return {"success": True, "data": self.serialize_agent(agent)}

    async def update_agent(self, args: ToolArguments) -> dict[str, object]:
        agent_id = parse_uuid(args.get("agent_id"))
        if agent_id is None:
            return {"success": False, "error": "Invalid agent_id"}

        agent = await self.get_agent_for_workspace(agent_id)
        if agent is None:
            return {"success": False, "error": "Agent not found"}

        update_args = {
            key: value for key, value in without_confirmation(args).items() if key != "agent_id"
        }
        try:
            agent_in = AgentUpdate(**update_args)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        update_data = agent_in.model_dump(exclude_unset=True)
        if not update_data:
            return {"success": False, "error": "No agent fields provided"}
        for field, value in update_data.items():
            setattr(agent, field, value)
        await self.context.db.flush()
        return {"success": True, "data": self.serialize_agent(agent)}
