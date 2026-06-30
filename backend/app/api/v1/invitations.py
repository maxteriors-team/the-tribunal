"""Workspace invitation endpoints."""

import uuid
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.crud import get_nested_or_404
from app.api.deps import DB, CurrentUser, OptionalCurrentUser
from app.core.config import settings
from app.core.permissions import Capability, role_can
from app.db.scope import apply_workspace_scope
from app.models.invitation import WorkspaceInvitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.invitation import (
    InvitationAcceptResponse,
    InvitationCreate,
    InvitationPublicResponse,
    InvitationResponse,
)
from app.services.email import send_invitation_email
from app.services.idempotency import derive_outbound_key

router = APIRouter()
logger = structlog.get_logger()


async def verify_workspace_admin(
    db: DB,
    current_user: CurrentUser,
    workspace_id: uuid.UUID,
) -> WorkspaceMembership:
    """Verify user has admin access to workspace."""
    result = await db.execute(
        apply_workspace_scope(select(WorkspaceMembership), WorkspaceMembership, workspace_id).where(
            WorkspaceMembership.user_id == current_user.id
        )
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found or access denied",
        )

    if not role_can(membership.role, Capability.MEMBERS_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to manage invitations",
        )

    return membership


@router.get("", response_model=list[InvitationResponse])
async def list_invitations(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> list[InvitationResponse]:
    """List all pending invitations for a workspace."""
    await verify_workspace_admin(db, current_user, workspace_id)

    result = await db.execute(
        apply_workspace_scope(
            select(WorkspaceInvitation).options(selectinload(WorkspaceInvitation.invited_by)),
            WorkspaceInvitation,
            workspace_id,
        )
        .where(WorkspaceInvitation.status == "pending")
        .order_by(WorkspaceInvitation.created_at.desc())
    )
    invitations = result.scalars().all()

    return [
        InvitationResponse(
            id=inv.id,
            workspace_id=inv.workspace_id,
            email=inv.email,
            role=inv.role,
            status=inv.status,
            message=inv.message,
            invited_by_email=inv.invited_by.email if inv.invited_by else None,
            invited_by_name=inv.invited_by.full_name if inv.invited_by else None,
            expires_at=inv.expires_at,
            created_at=inv.created_at,
            accepted_at=inv.accepted_at,
        )
        for inv in invitations
    ]


@router.post("", response_model=InvitationResponse, status_code=status.HTTP_201_CREATED)
async def create_invitation(
    workspace_id: uuid.UUID,
    invitation_data: InvitationCreate,
    current_user: CurrentUser,
    db: DB,
) -> InvitationResponse:
    """Create and send an invitation to join the workspace."""
    await verify_workspace_admin(db, current_user, workspace_id)

    # Get workspace details
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Check if user is already a member
    result = await db.execute(select(User).where(User.email == invitation_data.email))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        result = await db.execute(
            apply_workspace_scope(
                select(WorkspaceMembership), WorkspaceMembership, workspace_id
            ).where(WorkspaceMembership.user_id == existing_user.id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User is already a member of this workspace",
            )

    # Check for existing pending invitation
    result = await db.execute(
        apply_workspace_scope(select(WorkspaceInvitation), WorkspaceInvitation, workspace_id).where(
            WorkspaceInvitation.email == invitation_data.email,
            WorkspaceInvitation.status == "pending",
        )
    )
    existing_invitation = result.scalar_one_or_none()

    if existing_invitation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invitation has already been sent to this email",
        )

    # Create invitation
    invitation = WorkspaceInvitation(
        workspace_id=workspace_id,
        email=invitation_data.email,
        role=invitation_data.role,
        message=invitation_data.message,
        invited_by_id=current_user.id,
    )
    db.add(invitation)
    await db.commit()
    await db.refresh(invitation)

    # Send invitation email
    invitation_url = f"{settings.frontend_url}/invite/{invitation.token}"
    try:
        await send_invitation_email(
            to_email=invitation_data.email,
            workspace_name=workspace.name,
            inviter_name=current_user.full_name or current_user.email,
            invitation_url=invitation_url,
            role=invitation_data.role,
            message=invitation_data.message,
            idempotency_key=derive_outbound_key("workspace_invitation_email", invitation.id),
        )
    except Exception as e:
        logger.error(
            "failed_to_send_invitation_email",
            email=invitation_data.email,
            error=str(e),
        )
        # Don't fail the request if email fails - invitation is still created

    logger.info(
        "invitation_created",
        workspace_id=str(workspace_id),
        email=invitation_data.email,
        invited_by=current_user.id,
    )

    return InvitationResponse(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        message=invitation.message,
        invited_by_email=current_user.email,
        invited_by_name=current_user.full_name,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
        accepted_at=invitation.accepted_at,
    )


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_invitation(
    workspace_id: uuid.UUID,
    invitation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> None:
    """Cancel a pending invitation."""
    await verify_workspace_admin(db, current_user, workspace_id)

    invitation = await get_nested_or_404(
        db,
        WorkspaceInvitation,
        invitation_id,
        parent_field="workspace_id",
        parent_id=workspace_id,
        detail="Invitation not found",
    )

    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only cancel pending invitations",
        )

    invitation.status = "cancelled"
    await db.commit()

    logger.info(
        "invitation_cancelled",
        invitation_id=str(invitation_id),
        cancelled_by=current_user.id,
    )


# Public endpoints for invitation acceptance (outside workspace scope)
public_router = APIRouter()


@public_router.get("/{token}", response_model=InvitationPublicResponse)
async def get_invitation_by_token(
    token: str,
    db: DB,
) -> InvitationPublicResponse:
    """Get invitation details by token (public endpoint)."""
    result = await db.execute(
        select(WorkspaceInvitation)
        .options(
            selectinload(WorkspaceInvitation.workspace),
            selectinload(WorkspaceInvitation.invited_by),
        )
        .where(WorkspaceInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()

    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )

    return InvitationPublicResponse(
        workspace_name=invitation.workspace.name,
        workspace_slug=invitation.workspace.slug,
        email=invitation.email,
        role=invitation.role,
        invited_by_name=invitation.invited_by.full_name if invitation.invited_by else None,
        expires_at=invitation.expires_at,
        is_expired=invitation.is_expired,
        is_valid=invitation.is_valid,
    )


@public_router.post("/{token}/accept", response_model=InvitationAcceptResponse)
async def accept_invitation(
    token: str,
    current_user: OptionalCurrentUser,
    db: DB,
) -> InvitationAcceptResponse:
    """Accept an invitation to join a workspace."""
    result = await db.execute(
        select(WorkspaceInvitation)
        .options(selectinload(WorkspaceInvitation.workspace))
        .where(WorkspaceInvitation.token == token)
    )
    invitation = result.scalar_one_or_none()

    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invitation not found",
        )

    if not invitation.is_valid:
        if invitation.is_expired:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This invitation has expired",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This invitation is no longer valid",
        )

    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Please log in to accept this invitation",
        )

    # Verify email matches (case insensitive)
    if current_user.email.lower() != invitation.email.lower():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This invitation was sent to a different email address",
        )

    # Check if already a member
    result = await db.execute(
        apply_workspace_scope(
            select(WorkspaceMembership),
            WorkspaceMembership,
            invitation.workspace_id,
        ).where(WorkspaceMembership.user_id == current_user.id)
    )
    if result.scalar_one_or_none():
        # Already a member, just mark invitation as accepted
        invitation.status = "accepted"
        invitation.accepted_at = datetime.now(UTC)
        await db.commit()

        return InvitationAcceptResponse(
            success=True,
            message="You are already a member of this workspace",
            workspace_id=invitation.workspace_id,
            workspace_slug=invitation.workspace.slug,
        )

    # Create membership
    membership = WorkspaceMembership(
        user_id=current_user.id,
        workspace_id=invitation.workspace_id,
        role=invitation.role,
        is_default=False,
    )
    db.add(membership)

    # Update invitation status
    invitation.status = "accepted"
    invitation.accepted_at = datetime.now(UTC)

    await db.commit()

    logger.info(
        "invitation_accepted",
        invitation_id=str(invitation.id),
        user_id=current_user.id,
        workspace_id=str(invitation.workspace_id),
    )

    return InvitationAcceptResponse(
        success=True,
        message=f"You have joined {invitation.workspace.name}",
        workspace_id=invitation.workspace_id,
        workspace_slug=invitation.workspace.slug,
    )
