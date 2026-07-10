"""Appointment management endpoints."""

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.workspace import Workspace
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentStatsResponse,
    AppointmentUpdate,
    PaginatedAppointments,
)
from app.services.appointments import AppointmentService

router = APIRouter()
logger = structlog.get_logger()


@router.get("", response_model=PaginatedAppointments)
async def list_appointments(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(
        None, description="Filter by status: scheduled/completed/no_show/cancelled"
    ),
    contact_id: int | None = Query(None),
    agent_id: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
) -> PaginatedAppointments:
    """List appointments in a workspace.

    Requires workspace membership. All appointments are filtered by workspace_id
    to ensure workspace isolation.

    Optional filters:
    - status_filter: filter by appointment status
    - contact_id: filter by contact (indexed)
    - agent_id: filter by agent UUID (indexed)
    - date_from: appointments scheduled on or after this datetime (indexed)
    - date_to: appointments scheduled on or before this datetime (indexed)
    """
    service = AppointmentService(db)
    return await service.list_appointments(
        workspace_id=workspace_id,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
        contact_id=contact_id,
        agent_id=agent_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    workspace_id: uuid.UUID,
    appointment_in: AppointmentCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Create a new appointment.

    Requires workspace membership. Validates contact and agent exist in workspace.
    The appointment is stored in the CRM, which is the single source of truth for
    scheduling (no external calendar sync).
    """
    service = AppointmentService(db)
    return await service.create_appointment(workspace_id, appointment_in)


@router.get("/stats", response_model=AppointmentStatsResponse)
async def get_appointment_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AppointmentStatsResponse:
    """Return show-up rate analytics for the workspace.

    Computes overall appointment counts by status and derived show-up rate,
    then breaks the same metrics down by agent and by campaign.

    show_up_rate = completed / (completed + no_show) * 100, else 0.
    """
    service = AppointmentService(db)
    return await service.get_stats(workspace_id)


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    workspace_id: uuid.UUID,
    appointment_id: int,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Get an appointment by ID."""
    service = AppointmentService(db)
    return await service.get_appointment(workspace_id, appointment_id)


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    workspace_id: uuid.UUID,
    appointment_id: int,
    appointment_in: AppointmentUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Update an appointment."""
    service = AppointmentService(db)
    return await service.update_appointment(workspace_id, appointment_id, appointment_in)


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    workspace_id: uuid.UUID,
    appointment_id: int,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete/cancel an appointment."""
    service = AppointmentService(db)
    await service.delete_appointment(workspace_id, appointment_id)


@router.post(
    "/{appointment_id}/send-reminder",
    response_model=dict,
    summary="Manually send an SMS reminder for a scheduled appointment",
)
async def send_appointment_reminder(
    workspace_id: uuid.UUID,
    appointment_id: int,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, Any]:
    """Send an immediate SMS reminder for a scheduled appointment.

    Only works for appointments with status='scheduled'.
    Updates reminder_sent_at on success.
    Returns success/failure info without raising on SMS-level errors (opted out,
    no phone, no from number).
    """
    log = logger.bind(
        workspace_id=str(workspace_id),
        appointment_id=appointment_id,
        user_id=current_user.id,
    )
    service = AppointmentService(db)
    try:
        result = await service.send_reminder(workspace_id, appointment_id, workspace)
        log.info("manual_reminder_result", success=result.get("success"))
        return result
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("manual_reminder_unexpected_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while sending the reminder",
        ) from exc
