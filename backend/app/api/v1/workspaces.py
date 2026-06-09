"""Workspace endpoints."""

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import (
    DB,
    CurrentMembership,
    CurrentUser,
    WorkspaceAccess,
    WorkspaceAdminAccess,
)
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.workspace import (
    MemberResponse,
    UpdateMemberRoleRequest,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
    WorkspaceWithMembership,
)
from app.services.opportunities import ensure_default_pipeline

router = APIRouter()


@router.get("", response_model=list[WorkspaceWithMembership])
async def list_workspaces(
    current_user: CurrentUser,
    db: DB,
) -> list[WorkspaceWithMembership]:
    """List all workspaces the user is a member of."""
    result = await db.execute(
        select(WorkspaceMembership, Workspace)
        .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == current_user.id)
        .where(Workspace.is_active.is_(True))
        .order_by(WorkspaceMembership.created_at)
    )
    rows = result.all()

    return [
        WorkspaceWithMembership(
            workspace=WorkspaceResponse.model_validate(workspace),
            role=membership.role,
            is_default=membership.is_default,
        )
        for membership, workspace in rows
    ]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    workspace_in: WorkspaceCreate,
    current_user: CurrentUser,
    db: DB,
) -> WorkspaceResponse:
    """Create a new workspace."""
    # Check if slug already exists
    result = await db.execute(select(Workspace).where(Workspace.slug == workspace_in.slug))
    if result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace slug already exists",
        )

    # Create workspace
    workspace = Workspace(
        name=workspace_in.name,
        slug=workspace_in.slug,
        description=workspace_in.description,
        settings=workspace_in.settings,
    )
    db.add(workspace)
    await db.flush()

    # Create membership (owner)
    membership = WorkspaceMembership(
        user_id=current_user.id,
        workspace_id=workspace.id,
        role="owner",
        is_default=True,
    )
    db.add(membership)

    # Provision a default pipeline so opportunities (e.g. ad-library promotions)
    # land in a real pipeline and the opportunities board has columns to render.
    await ensure_default_pipeline(db, workspace.id)

    await db.commit()
    await db.refresh(workspace)

    return WorkspaceResponse.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace: WorkspaceAccess,
) -> WorkspaceResponse:
    """Get a specific workspace."""
    return WorkspaceResponse.model_validate(workspace)


@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_in: WorkspaceUpdate,
    workspace: WorkspaceAdminAccess,
    db: DB,
) -> WorkspaceResponse:
    """Update a workspace (owner/admin only)."""
    update_data = workspace_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(workspace, field, value)

    await db.commit()
    await db.refresh(workspace)

    return WorkspaceResponse.model_validate(workspace)


@router.post("/{workspace_id}/set-default", response_model=WorkspaceWithMembership)
async def set_default_workspace(
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    db: DB,
) -> WorkspaceWithMembership:
    """Set a workspace as the user's default workspace."""
    # Clear is_default for all other memberships of this user
    all_memberships_result = await db.execute(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == membership.user_id)
    )
    for m in all_memberships_result.scalars().all():
        m.is_default = m.workspace_id == workspace.id

    await db.commit()
    await db.refresh(membership)

    return WorkspaceWithMembership(
        workspace=WorkspaceResponse.model_validate(workspace),
        role=membership.role,
        is_default=membership.is_default,
    )


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    db: DB,
) -> None:
    """Delete a workspace (owner only)."""
    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can delete a workspace",
        )

    workspace.is_active = False
    await db.commit()


@router.put("/{workspace_id}/members/{user_id}/role", response_model=MemberResponse)
async def update_member_role(
    workspace_id: uuid.UUID,
    user_id: int,
    role_update: UpdateMemberRoleRequest,
    membership: CurrentMembership,
    db: DB,
) -> MemberResponse:
    """Update a member's role (owner/admin only)."""
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage members",
        )

    # Get target membership
    target_result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    target_membership = target_result.scalar_one_or_none()
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this workspace",
        )

    # Cannot change owner's role
    if target_membership.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot change the owner's role",
        )

    # Admins cannot promote/demote other admins
    if membership.role == "admin" and target_membership.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot change other admins' roles",
        )

    # Update role
    target_membership.role = role_update.role
    await db.commit()

    return MemberResponse(
        user_id=user_id,
        role=role_update.role,
        message=f"Member role updated to {role_update.role}",
    )


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    workspace_id: uuid.UUID,
    user_id: int,
    membership: CurrentMembership,
    db: DB,
) -> None:
    """Remove a member from the workspace (owner/admin only)."""
    if membership.role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage members",
        )

    # Get target membership
    target_result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
    )
    target_membership = target_result.scalar_one_or_none()
    if target_membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in this workspace",
        )

    # Cannot remove the owner
    if target_membership.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot remove the workspace owner",
        )

    # Admins cannot remove other admins
    if membership.role == "admin" and target_membership.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot remove other admins",
        )

    # Remove membership
    await db.delete(target_membership)
    await db.commit()
