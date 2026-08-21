"""Internal workspace time and attendance endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.api.deps import DB, CanManageAttendance, CanUseAttendance, TransactionalDB
from app.api.service_errors import ServiceErrorRoute
from app.schemas.attendance import (
    AttendanceAdminListQuery,
    AttendanceAdminReportResponse,
    AttendanceClockInRequest,
    AttendanceClockOutRequest,
    AttendanceDateRange,
    AttendanceEntryResponse,
    AttendanceEntryUpdateRequest,
    AttendanceExportRequest,
    AttendanceManualEntryRequest,
    AttendancePauseRequest,
    AttendanceReportResponse,
    AttendanceVoidRequest,
)
from app.services.attendance import AttendanceService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("/me", response_model=AttendanceReportResponse)
async def get_my_attendance(
    workspace_id: uuid.UUID,
    date_range: Annotated[AttendanceDateRange, Query()],
    db: DB,
    membership: CanUseAttendance,
) -> AttendanceReportResponse:
    """Return the caller's entries and current clock state for a local date range."""
    return await AttendanceService(db).get_my_report(workspace_id, membership, date_range)


@router.post(
    "/clock-in",
    response_model=AttendanceEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def clock_in(
    workspace_id: uuid.UUID,
    payload: AttendanceClockInRequest,
    db: TransactionalDB,
    membership: CanUseAttendance,
) -> AttendanceEntryResponse:
    """Start the caller's UTC server clock; request_id retries return the same entry."""
    return await AttendanceService(db).clock_in(workspace_id, membership, payload)


@router.post("/clock-out", response_model=AttendanceEntryResponse)
async def clock_out(
    workspace_id: uuid.UUID,
    payload: AttendanceClockOutRequest,
    db: TransactionalDB,
    membership: CanUseAttendance,
) -> AttendanceEntryResponse:
    """Stop the caller's UTC server clock; request_id retries return the same entry."""
    return await AttendanceService(db).clock_out(workspace_id, membership, payload)


@router.post("/pause", response_model=AttendanceEntryResponse)
async def pause_shift(
    workspace_id: uuid.UUID,
    payload: AttendancePauseRequest,
    db: TransactionalDB,
    membership: CanUseAttendance,
) -> AttendanceEntryResponse:
    """Pause the caller's active shift without ending it."""
    return await AttendanceService(db).pause_shift(workspace_id, membership, payload)


@router.post("/resume", response_model=AttendanceEntryResponse)
async def resume_shift(
    workspace_id: uuid.UUID,
    payload: AttendancePauseRequest,
    db: TransactionalDB,
    membership: CanUseAttendance,
) -> AttendanceEntryResponse:
    """Resume the caller's paused active shift."""
    return await AttendanceService(db).resume_shift(workspace_id, membership, payload)


@router.get("/entries", response_model=AttendanceAdminReportResponse)
async def list_entries(
    workspace_id: uuid.UUID,
    query: Annotated[AttendanceAdminListQuery, Query()],
    db: DB,
    membership: CanManageAttendance,
) -> AttendanceAdminReportResponse:
    """List all workspace entries, optionally restricted to one active member."""
    return await AttendanceService(db).list_entries(
        workspace_id,
        membership,
        query,
        user_id=query.user_id,
    )


@router.post(
    "/entries",
    response_model=AttendanceEntryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_manual_entry(
    workspace_id: uuid.UUID,
    payload: AttendanceManualEntryRequest,
    db: TransactionalDB,
    membership: CanManageAttendance,
) -> AttendanceEntryResponse:
    """Create a completed manual interval for an active workspace member."""
    return await AttendanceService(db).create_manual_entry(workspace_id, membership, payload)


@router.patch("/entries/{entry_id}", response_model=AttendanceEntryResponse)
async def update_entry(
    workspace_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: AttendanceEntryUpdateRequest,
    db: TransactionalDB,
    membership: CanManageAttendance,
) -> AttendanceEntryResponse:
    """Correct timestamps or an encrypted note, recording the mandatory reason."""
    return await AttendanceService(db).update_entry(workspace_id, membership, entry_id, payload)


@router.post("/entries/{entry_id}/void", response_model=AttendanceEntryResponse)
async def void_entry(
    workspace_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: AttendanceVoidRequest,
    db: TransactionalDB,
    membership: CanManageAttendance,
) -> AttendanceEntryResponse:
    """Void an interval without deleting it, recording the mandatory reason."""
    return await AttendanceService(db).void_entry(workspace_id, membership, entry_id, payload)


@router.post(
    "/exports",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "description": (
                "Generic UTF-8 CSV containing raw completed hours. Payroll software must "
                "classify regular and overtime hours; no vendor compatibility is implied."
            ),
            "content": {"text/csv": {}},
        }
    },
)
async def export_attendance(
    workspace_id: uuid.UUID,
    payload: AttendanceExportRequest,
    db: TransactionalDB,
    membership: CanManageAttendance,
) -> Response:
    """Export completed raw hours and persist only audit metadata, never CSV content."""
    result = await AttendanceService(db).export_csv(workspace_id, membership, payload)
    return Response(
        content=result.content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{result.filename}"',
            "X-Attendance-Export-SHA256": result.sha256,
            "X-Payroll-Classification-Required": "regular-and-overtime",
        },
    )
