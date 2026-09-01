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
from app.core.permissions import Capability, role_can
from app.core.roles import can_assign_workspace_role
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.bulk_members import (
    BulkMemberCreateRequest,
    BulkMemberCreateResponse,
)
from app.schemas.workspace import (
    MemberResponse,
    UpdateMemberRoleRequest,
    WorkspaceCreate,
    WorkspaceResponse,
    WorkspaceUpdate,
    WorkspaceWithMembership,
)
from app.services.field_service import ensure_member_on_roster, retire_member_from_roster
from app.services.opportunities import ensure_default_pipeline
from app.services.workspaces import bulk_create_members, set_default_membership
from app.services.workspaces.default_sales_setup import ensure_default_sales_setup

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

    # Create membership (owner). The new workspace becomes the caller's default,
    # which means demoting whatever was default before: flagging this row without
    # clearing the old one left the user with two defaults, and the resolvers
    # behind /onboarding and /billing then raised MultipleResultsFound — a 500 on
    # every one of those routes for anyone who ever created a second workspace.
    membership = WorkspaceMembership(
        user_id=current_user.id,
        workspace_id=workspace.id,
        role="owner",
        is_default=False,
    )
    db.add(membership)
    await db.flush()
    await set_default_membership(db, current_user.id, workspace.id)

    # Provision a default pipeline so opportunities (e.g. ad-library promotions)
    # land in a real pipeline and the opportunities board has columns to render.
    await ensure_default_pipeline(db, workspace.id)
    await ensure_default_sales_setup(db, workspace, created_by_id=current_user.id)

    # Deliberately no default agent. A seeded agent speaks to real customers in
    # the operator's name, so the operator authors it in the /agents wizard --
    # we do not guess a script for their business. (This used to seed another
    # company's cold-lead template into every new workspace.)

    await db.commit()
    await db.refresh(workspace)

    return WorkspaceResponse.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
) -> WorkspaceResponse:
    """Get a specific workspace, including the caller's role."""
    response = WorkspaceResponse.model_validate(workspace)
    response.role = membership.role
    return response


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
    # Ordered clear-then-promote in one place. The previous per-object loop let
    # the ORM flush the demotions and the promotion in an arbitrary order, which
    # transiently holds two default rows and now trips the partial unique index.
    await set_default_membership(db, membership.user_id, workspace.id)

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
    if not role_can(membership.role, Capability.MEMBERS_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage members",
        )
    if not can_assign_workspace_role(membership.role, role_update.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workspace owner can grant the admin role",
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

    # Promoting someone into a field role puts them on the dispatch board so
    # jobs can be tagged to them. Demoting never removes a roster row: field
    # work and CRM permissions are separate axes (see
    # app.services.field_service.roster).
    target_user = await db.get(User, user_id)
    if target_user is not None:
        await ensure_member_on_roster(
            db,
            workspace_id=workspace_id,
            user=target_user,
            role=role_update.role,
        )

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
    if not role_can(membership.role, Capability.MEMBERS_MANAGE):
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

    # Someone who lost workspace access must stop showing up as assignable.
    # Retiring (unlink + deactivate) rather than deleting keeps the assignment
    # history on jobs they already worked.
    await retire_member_from_roster(db, workspace_id=workspace_id, user_id=user_id)

    # Remove membership
    await db.delete(target_membership)
    await db.commit()


@router.post(
    "/{workspace_id}/members/bulk",
    response_model=BulkMemberCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def bulk_create_workspace_members(
    workspace_id: uuid.UUID,
    payload: BulkMemberCreateRequest,
    membership: CurrentMembership,
    db: DB,
) -> BulkMemberCreateResponse:
    """Provision many members at once (owner/admin only).

    Creates a login + workspace membership for each new email and attaches any
    existing accounts as members. Returns a per-row outcome; rows that conflict
    are skipped without failing the batch. Only the owner may grant the admin
    role. Generated temporary passwords are returned once and never stored in
    plaintext.
    """
    if not role_can(membership.role, Capability.MEMBERS_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to manage members",
        )

    response = await bulk_create_members(
        db,
        workspace_id=workspace_id,
        caller_role=membership.role,
        items=payload.members,
    )
    await db.commit()
    return response
