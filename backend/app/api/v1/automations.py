"""Automation management endpoints."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, CanReadCRM, CanWriteCRM, CurrentUser
from app.db.pagination import paginate
from app.db.scope import apply_workspace_scope
from app.models.automation import Automation
from app.schemas.automation import (
    AutomationCreate,
    AutomationResponse,
    AutomationStatsResponse,
    AutomationUpdate,
    PaginatedAutomations,
)

router = APIRouter()


@router.get("/stats", response_model=AutomationStatsResponse)
async def get_automation_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
) -> AutomationStatsResponse:
    """Get automation statistics for a workspace."""
    # Total automations
    total_result = await db.execute(
        apply_workspace_scope(
            select(func.count()).select_from(Automation),
            Automation,
            workspace_id,
        )
    )
    total = total_result.scalar_one()

    # Active automations
    active_result = await db.execute(
        apply_workspace_scope(
            select(func.count()).select_from(Automation),
            Automation,
            workspace_id,
        ).where(Automation.is_active.is_(True))
    )
    active = active_result.scalar_one()

    # Triggered today
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    triggered_today_result = await db.execute(
        apply_workspace_scope(
            select(func.count()).select_from(Automation),
            Automation,
            workspace_id,
        ).where(Automation.last_triggered_at >= today_start)
    )
    triggered_today = triggered_today_result.scalar_one()

    return AutomationStatsResponse(
        total=total,
        active=active,
        triggered_today=triggered_today,
    )


@router.get("", response_model=PaginatedAutomations)
async def list_automations(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    active_only: bool = False,
) -> PaginatedAutomations:
    """List automations in a workspace."""
    query = apply_workspace_scope(select(Automation), Automation, workspace_id)

    if active_only:
        query = query.where(Automation.is_active.is_(True))

    query = query.order_by(Automation.created_at.desc())
    result = await paginate(db, query, page=page, page_size=page_size)

    return PaginatedAutomations(**result.to_response(AutomationResponse))


@router.post("", response_model=AutomationResponse, status_code=status.HTTP_201_CREATED)
async def create_automation(
    workspace_id: uuid.UUID,
    automation_in: AutomationCreate,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteCRM,
) -> Automation:
    """Create a new automation."""
    automation = Automation(
        workspace_id=workspace_id,
        **automation_in.model_dump(),
    )
    db.add(automation)
    await db.commit()
    await db.refresh(automation)

    return automation


@router.get("/{automation_id}", response_model=AutomationResponse)
async def get_automation(
    workspace_id: uuid.UUID,
    automation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanReadCRM,
) -> Automation:
    """Get an automation by ID."""
    result = await db.execute(
        apply_workspace_scope(select(Automation), Automation, workspace_id).where(
            Automation.id == automation_id
        )
    )
    automation = result.scalar_one_or_none()

    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )

    return automation


@router.put("/{automation_id}", response_model=AutomationResponse)
async def update_automation(
    workspace_id: uuid.UUID,
    automation_id: uuid.UUID,
    automation_in: AutomationUpdate,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteCRM,
) -> Automation:
    """Update an automation."""
    result = await db.execute(
        apply_workspace_scope(select(Automation), Automation, workspace_id).where(
            Automation.id == automation_id
        )
    )
    automation = result.scalar_one_or_none()

    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )

    # Update fields
    update_data = automation_in.model_dump(exclude_unset=True)

    # Handle actions specially to convert pydantic models to dicts
    if "actions" in update_data and update_data["actions"] is not None:
        update_data["actions"] = [
            action.model_dump() if hasattr(action, "model_dump") else action
            for action in update_data["actions"]
        ]

    for field, value in update_data.items():
        setattr(automation, field, value)

    await db.commit()
    await db.refresh(automation)

    return automation


@router.delete("/{automation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_automation(
    workspace_id: uuid.UUID,
    automation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteCRM,
) -> None:
    """Delete an automation."""
    result = await db.execute(
        apply_workspace_scope(select(Automation), Automation, workspace_id).where(
            Automation.id == automation_id
        )
    )
    automation = result.scalar_one_or_none()

    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )

    await db.delete(automation)
    await db.commit()


@router.post("/{automation_id}/toggle", response_model=AutomationResponse)
async def toggle_automation(
    workspace_id: uuid.UUID,
    automation_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    _gate: CanWriteCRM,
) -> Automation:
    """Toggle automation active status."""
    result = await db.execute(
        apply_workspace_scope(select(Automation), Automation, workspace_id).where(
            Automation.id == automation_id
        )
    )
    automation = result.scalar_one_or_none()

    if not automation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Automation not found",
        )

    automation.is_active = not automation.is_active
    await db.commit()
    await db.refresh(automation)

    return automation
