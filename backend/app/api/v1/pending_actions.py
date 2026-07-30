"""Pending action management endpoints for HITL approval gate."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, get_workspace
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.pending_action import PendingAction
from app.models.workspace import Workspace
from app.schemas.pending_action import (
    ApproveActionRequest,
    PendingActionListResponse,
    PendingActionResponse,
    RejectActionRequest,
    pending_action_response,
)
from app.services.approval.approval_gate_service import approval_gate_service

router = APIRouter()


@router.get("/stats")
async def get_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Get pending action counts grouped by status."""
    result = await db.execute(
        apply_workspace_scope(
            select(PendingAction.status, func.count(PendingAction.id)),
            PendingAction,
            workspace_id,
        ).group_by(PendingAction.status)
    )
    counts: dict[str, int] = {row[0]: row[1] for row in result.all()}

    return {
        "pending": counts.get("pending", 0),
        "approved": counts.get("approved", 0),
        "rejected": counts.get("rejected", 0),
        "expired": counts.get("expired", 0),
        "executed": counts.get("executed", 0),
    }


@router.get("", response_model=PendingActionListResponse)
async def list_actions(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    status_filter: str | None = Query(None, alias="status"),
    agent_id: uuid.UUID | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PendingActionListResponse:
    """List pending actions for a workspace with optional filters."""
    query = apply_workspace_scope(select(PendingAction), PendingAction, workspace_id).order_by(
        PendingAction.created_at.desc()
    )

    if status_filter:
        query = query.where(PendingAction.status == status_filter)

    if agent_id:
        query = query.where(PendingAction.agent_id == agent_id)

    result = await paginate(db, query, page=page, page_size=page_size)

    return PendingActionListResponse(
        items=[pending_action_response(a) for a in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        pages=result.pages,
    )


@router.get("/{action_id}", response_model=PendingActionResponse)
async def get_action(
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> PendingActionResponse:
    """Get a specific pending action."""
    result = await db.execute(
        apply_workspace_scope(select(PendingAction), PendingAction, workspace_id).where(
            PendingAction.id == action_id
        )
    )
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending action not found",
        )

    return pending_action_response(action)


@router.post("/{action_id}/approve", response_model=PendingActionResponse)
async def approve_action(
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    body: ApproveActionRequest | None = None,
) -> PendingActionResponse:
    """Approve a pending action for execution."""
    # Verify action belongs to workspace
    result = await db.execute(
        apply_workspace_scope(select(PendingAction), PendingAction, workspace_id).where(
            PendingAction.id == action_id
        )
    )
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending action not found",
        )

    if action.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action is already {action.status}",
        )

    updated = await approval_gate_service.approve_action(
        db=db,
        action_id=action_id,
        user_id=current_user.id,
    )

    return pending_action_response(updated)


@router.post("/{action_id}/reject", response_model=PendingActionResponse)
async def reject_action(
    workspace_id: uuid.UUID,
    action_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    body: RejectActionRequest | None = None,
) -> PendingActionResponse:
    """Reject a pending action."""
    # Verify action belongs to workspace
    result = await db.execute(
        apply_workspace_scope(select(PendingAction), PendingAction, workspace_id).where(
            PendingAction.id == action_id
        )
    )
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending action not found",
        )

    if action.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action is already {action.status}",
        )

    updated = await approval_gate_service.reject_action(
        db=db,
        action_id=action_id,
        user_id=current_user.id,
        reason=body.reason if body else None,
    )

    return pending_action_response(updated)
