"""Appointment management endpoints."""

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CurrentMembership, CurrentUser, get_workspace
from app.core.permissions import appointment_owner_scope
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.appointment import (
    AppointmentCreate,
    AppointmentResponse,
    AppointmentStatsResponse,
    AppointmentUpdate,
    PaginatedAppointments,
)
from app.services.appointments import AppointmentService
from app.services.rate_limiting.appointment_reminder_limiter import (
    enforce_appointment_reminder_rate_limit,
)

router = APIRouter()
logger = structlog.get_logger()


def _calendar_scope_user_id(
    membership: WorkspaceMembership, user_id: int, *, mine: bool = False
) -> int | None:
    """The user a caller's appointment reads are confined to, or ``None`` for everything.

    Owners, admins, managers, and dispatchers see the whole team. Sales and lower
    tiers see only appointments assigned to their login-backed staff row. ``mine``
    can narrow a higher role but can never widen a lower role's scope.
    """
    if mine:
        return user_id
    return appointment_owner_scope(membership.role, user_id)


@router.get("", response_model=PaginatedAppointments)
async def list_appointments(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(
        None, description="Filter by status: scheduled/completed/no_show/cancelled"
    ),
    contact_id: int | None = Query(None),
    agent_id: str | None = Query(None),
    business_location_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    mine: bool = Query(False, description="Only appointments the caller is booked on"),
) -> PaginatedAppointments:
    """List appointments in a workspace.

    Requires workspace membership. All appointments are filtered by workspace_id
    to ensure workspace isolation.

    Dispatchers and up see every appointment. Below that line the list is scoped
    server-side to the appointments the caller is booked on (their linked
    bookable-staff row); an unlinked caller gets an empty page, not an error.

    ``mine=true`` narrows the result to the caller's own bookings whatever their
    role; for the field tier it is already implied.

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
        business_location_id=business_location_id,
        date_from=date_from,
        date_to=date_to,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id, mine=mine),
    )


@router.post("", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    workspace_id: uuid.UUID,
    appointment_in: AppointmentCreate,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Create a new appointment.

    Dispatch-tier callers may leave it unassigned or tag a booking-enabled user.
    Restricted callers are assigned to their active linked booking resource so
    the row remains visible on their scoped calendar; an admin must enable that
    resource in Settings → Team first.
    """
    service = AppointmentService(db)
    visible_to_user_id = _calendar_scope_user_id(membership, current_user.id)
    if visible_to_user_id is not None and appointment_in.bookable_staff_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only dispatchers can tag another user on an appointment",
        )
    return await service.create_appointment(
        workspace_id,
        appointment_in,
        booked_for_user_id=visible_to_user_id,
    )


@router.get("/stats", response_model=AppointmentStatsResponse)
async def get_appointment_stats(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> AppointmentStatsResponse:
    """Return show-up rate analytics for the workspace.

    Computes overall appointment counts by status and derived show-up rate,
    then breaks the same metrics down by agent and by campaign.

    show_up_rate = completed / (completed + no_show) * 100, else 0.
    """
    service = AppointmentService(db)
    return await service.get_stats(
        workspace_id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment(
    workspace_id: uuid.UUID,
    appointment_id: int,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Get an appointment by ID.

    Carries the same scope as the list, so a deep link to an appointment the
    caller is not booked on 404s rather than bypassing the filter.
    """
    service = AppointmentService(db)
    return await service.get_appointment(
        workspace_id,
        appointment_id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.put("/{appointment_id}", response_model=AppointmentResponse)
async def update_appointment(
    workspace_id: uuid.UUID,
    appointment_id: int,
    appointment_in: AppointmentUpdate,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> Any:
    """Update an appointment within the caller's calendar scope."""
    service = AppointmentService(db)
    visible_to_user_id = _calendar_scope_user_id(membership, current_user.id)
    if visible_to_user_id is not None and "bookable_staff_id" in appointment_in.model_fields_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only dispatchers can change an appointment's tagged user",
        )
    return await service.update_appointment(
        workspace_id,
        appointment_id,
        appointment_in,
        visible_to_user_id=visible_to_user_id,
    )


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(
    workspace_id: uuid.UUID,
    appointment_id: int,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete/cancel an appointment within the caller's calendar scope."""
    service = AppointmentService(db)
    await service.delete_appointment(
        workspace_id,
        appointment_id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post(
    "/{appointment_id}/send-reminder",
    response_model=dict,
    summary="Manually send an SMS reminder for a scheduled appointment",
)
async def send_appointment_reminder(
    workspace_id: uuid.UUID,
    appointment_id: int,
    current_user: CurrentUser,
    membership: CurrentMembership,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, Any]:
    """Send an immediate SMS reminder for an appointment visible to the caller.

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
    await enforce_appointment_reminder_rate_limit(workspace_id, current_user.id)
    service = AppointmentService(db)
    try:
        result = await service.send_reminder(
            workspace_id,
            appointment_id,
            workspace,
            visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
        )
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
