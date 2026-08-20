"""Agent management endpoints."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability
from app.models.workspace import Workspace
from app.schemas.agent import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    EmbedSettingsResponse,
    EmbedSettingsUpdate,
    PaginatedAgents,
)
from app.services.agents import AgentService

router = APIRouter(
    route_class=ServiceErrorRoute,
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.WORKSPACE_MANAGE))
    ],
)


@router.get("", response_model=PaginatedAgents)
async def list_agents(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    active_only: bool = True,
) -> PaginatedAgents:
    """List agents in a workspace."""
    service = AgentService(db)
    return await service.list_agents(
        workspace_id, page=page, page_size=page_size, active_only=active_only
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    workspace_id: uuid.UUID,
    agent_in: AgentCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Create a new agent."""
    service = AgentService(db)
    return await service.create_agent(workspace_id, agent_in)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Get an agent by ID."""
    service = AgentService(db)
    return await service.get_agent(workspace_id, agent_id)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    agent_in: AgentUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Update an agent."""
    service = AgentService(db)
    return await service.update_agent(workspace_id, agent_id, agent_in)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete an agent (soft delete by deactivating)."""
    service = AgentService(db)
    await service.delete_agent(workspace_id, agent_id)


@router.get("/{agent_id}/embed", response_model=EmbedSettingsResponse)
async def get_embed_settings(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> EmbedSettingsResponse:
    """Get embed settings for an agent."""
    service = AgentService(db)
    return await service.get_embed_settings(workspace_id, agent_id)


@router.put("/{agent_id}/embed", response_model=EmbedSettingsResponse)
async def update_embed_settings(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: EmbedSettingsUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> EmbedSettingsResponse:
    """Update embed settings for an agent."""
    service = AgentService(db)
    return await service.update_embed_settings(workspace_id, agent_id, body)
