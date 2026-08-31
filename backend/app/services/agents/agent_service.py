"""Agent business logic service."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.crud import get_or_404
from app.db.pagination import paginate
from app.models.agent import Agent, generate_public_id
from app.schemas.agent import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    EmbedSettings,
    EmbedSettingsResponse,
    EmbedSettingsUpdate,
    PaginatedAgents,
)

logger = structlog.get_logger()


def _build_embed_response(agent: Agent) -> EmbedSettingsResponse:
    """Construct an EmbedSettingsResponse from an agent model."""
    embed_settings = agent.embed_settings or {}
    mode = embed_settings.get("mode", "voice")
    embed_code = None

    if agent.embed_enabled and agent.public_id:
        embed_code = (
            f'<script src="/widget/v1/widget.js" defer></script>\n'
            f'<ai-agent agent-id="{agent.public_id}" mode="{mode}"></ai-agent>'
        )

    return EmbedSettingsResponse(
        public_id=agent.public_id,
        embed_enabled=agent.embed_enabled,
        allowed_domains=agent.allowed_domains or [],
        embed_settings=EmbedSettings(
            button_text=embed_settings.get("button_text", "Talk to AI"),
            theme=embed_settings.get("theme", "auto"),
            position=embed_settings.get("position", "bottom-right"),
            primary_color=embed_settings.get("primary_color", "#6366f1"),
            mode=mode,
            display=embed_settings.get("display", "floating"),
        ),
        embed_code=embed_code,
    )


class AgentService:
    """Service for agent CRUD and embed settings management."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(component="agent_service")

    async def list_agents(
        self,
        workspace_id: uuid.UUID,
        page: int = 1,
        page_size: int = 50,
        active_only: bool = True,
    ) -> PaginatedAgents:
        """List agents in a workspace."""
        query = select(Agent).where(
            Agent.workspace_id == workspace_id,
            Agent.deleted_at.is_(None),
        )
        if active_only:
            query = query.where(Agent.is_active.is_(True))
        query = query.order_by(Agent.created_at.desc())

        result = await paginate(self.db, query, page=page, page_size=page_size)
        return PaginatedAgents(**result.to_response(AgentResponse))

    async def create_agent(
        self,
        workspace_id: uuid.UUID,
        agent_in: AgentCreate,
    ) -> Agent:
        """Create a new agent."""
        agent = Agent(workspace_id=workspace_id, **agent_in.model_dump())
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        self.log.info("agent_created", agent_id=agent.id, workspace_id=str(workspace_id))
        return agent

    async def get_agent(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> Agent:
        """Get an agent by ID, raising 404 if not found or deleted."""
        agent = await get_or_404(self.db, Agent, agent_id, workspace_id=workspace_id)
        if agent.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found",
            )
        return agent

    async def update_agent(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        agent_in: AgentUpdate,
    ) -> Agent:
        """Update an agent's fields."""
        agent = await self.get_agent(workspace_id, agent_id)

        update_data = agent_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(agent, field, value)

        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def delete_agent(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> None:
        """Soft-delete an agent: hide it everywhere, keep the row for history.

        is_active is cleared too so every existing `is_active` runtime guard
        (inbound routing, text replies, workers) stops using it immediately.
        """
        agent = await self.get_agent(workspace_id, agent_id)
        agent.deleted_at = datetime.now(UTC)
        agent.is_active = False
        await self.db.commit()
        self.log.info("agent_deleted", agent_id=agent_id, workspace_id=str(workspace_id))

    async def get_embed_settings(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> EmbedSettingsResponse:
        """Get embed settings, generating a public_id if one doesn't exist yet."""
        agent = await self.get_agent(workspace_id, agent_id)

        if not agent.public_id:
            agent.public_id = generate_public_id()
            await self.db.commit()
            await self.db.refresh(agent)

        return _build_embed_response(agent)

    async def update_embed_settings(
        self,
        workspace_id: uuid.UUID,
        agent_id: uuid.UUID,
        body: EmbedSettingsUpdate,
    ) -> EmbedSettingsResponse:
        """Update embed settings, generating a public_id if enabling embed."""
        agent = await self.get_agent(workspace_id, agent_id)

        if body.embed_enabled and not agent.public_id:
            agent.public_id = generate_public_id()

        if body.embed_enabled is not None:
            agent.embed_enabled = body.embed_enabled

        if body.allowed_domains is not None:
            agent.allowed_domains = body.allowed_domains

        if body.embed_settings is not None:
            current_settings = agent.embed_settings or {}
            current_settings.update(body.embed_settings)
            agent.embed_settings = current_settings

        await self.db.commit()
        await self.db.refresh(agent)

        return _build_embed_response(agent)
