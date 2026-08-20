"""Human profile management endpoints for HITL system."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DB, CurrentUser, get_workspace, require_route_capabilities
from app.core.permissions import Capability
from app.models.agent import Agent
from app.models.human_profile import HumanProfile
from app.models.workspace import Workspace
from app.schemas.human_profile import (
    HumanProfileCreate,
    HumanProfileResponse,
    HumanProfileUpdate,
)

router = APIRouter(
    dependencies=[
        Depends(require_route_capabilities(Capability.CRM_READ, Capability.WORKSPACE_MANAGE))
    ]
)


def _profile_to_response(profile: HumanProfile) -> HumanProfileResponse:
    """Convert a HumanProfile model to a HumanProfileResponse."""
    return HumanProfileResponse(
        id=profile.id,
        workspace_id=profile.workspace_id,
        agent_id=profile.agent_id,
        display_name=profile.display_name,
        role_title=profile.role_title,
        phone_number=profile.phone_number,
        email=profile.email,
        timezone=profile.timezone,
        bio=profile.bio,
        communication_preferences=profile.communication_preferences,
        action_policies=profile.action_policies,
        default_policy=profile.default_policy,
        auto_approve_timeout_minutes=profile.auto_approve_timeout_minutes,
        auto_reject_timeout_minutes=profile.auto_reject_timeout_minutes,
        is_active=profile.is_active,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


async def _get_agent_or_404(
    db: AsyncSession,
    agent_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> Agent:
    """Verify agent exists and belongs to workspace."""
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.workspace_id == workspace_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


@router.get("", response_model=HumanProfileResponse)
async def get_agent_profile(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> HumanProfileResponse:
    """Get the human profile for an agent."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(HumanProfile).where(
            HumanProfile.agent_id == agent_id,
            HumanProfile.workspace_id == workspace_id,
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Human profile not found",
        )

    return _profile_to_response(profile)


@router.put("", response_model=HumanProfileResponse)
async def upsert_profile(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: HumanProfileCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> HumanProfileResponse:
    """Create or update the human profile for an agent (idempotent)."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(HumanProfile).where(
            HumanProfile.agent_id == agent_id,
            HumanProfile.workspace_id == workspace_id,
        )
    )
    profile = result.scalar_one_or_none()

    if profile:
        # Update existing
        for field, value in body.model_dump().items():
            setattr(profile, field, value)
    else:
        # Create new
        profile = HumanProfile(
            workspace_id=workspace_id,
            agent_id=agent_id,
            **body.model_dump(),
        )
        db.add(profile)

    await db.commit()
    await db.refresh(profile)

    return _profile_to_response(profile)


@router.patch("", response_model=HumanProfileResponse)
async def update_profile(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: HumanProfileUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> HumanProfileResponse:
    """Partial update of the human profile for an agent."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(HumanProfile).where(
            HumanProfile.agent_id == agent_id,
            HumanProfile.workspace_id == workspace_id,
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Human profile not found",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(profile, field, value)

    await db.commit()
    await db.refresh(profile)

    return _profile_to_response(profile)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete the human profile for an agent."""
    await _get_agent_or_404(db, agent_id, workspace_id)

    result = await db.execute(
        select(HumanProfile).where(
            HumanProfile.agent_id == agent_id,
            HumanProfile.workspace_id == workspace_id,
        )
    )
    profile = result.scalar_one_or_none()

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Human profile not found",
        )

    await db.delete(profile)
    await db.commit()
