"""Field-service job dispatch endpoints.

A *job* is a unit of field work for a customer. Dispatch tags one or more
technicians to it and gives it a time window; each assigned worker then sees the
job on their calendar (``GET /calendar/mine``).

Reads are available to any workspace member; writes are gated to dispatchers and
up (mirroring service-location writes in :mod:`app.api.v1.field_service`). Writes
run on the transactional session so a failed reference validation rolls back
cleanly.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.api.deps import (
    DB,
    CurrentUser,
    TransactionalDB,
    WorkspaceAccess,
    WorkspaceDispatcher,
)
from app.models.field_service import JobStatus
from app.schemas.job import (
    JobAssignRequest,
    JobCreate,
    JobListResponse,
    JobResponse,
    JobScheduleRequest,
    JobUpdate,
)
from app.services.jobs import JobService

router = APIRouter()


@router.get("", response_model=JobListResponse)
async def list_jobs(
    workspace: WorkspaceAccess,
    db: DB,
    status: JobStatus | None = None,
    crew_id: uuid.UUID | None = None,
    technician_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None, description="Jobs scheduled on or after this time"),
    date_to: datetime | None = Query(None, description="Jobs scheduled on or before this time"),
) -> JobListResponse:
    """List jobs for the dispatch board / calendar, with optional filters."""
    service = JobService(db)
    return JobListResponse(
        **await service.list(
            workspace.id,
            status=status,
            crew_id=crew_id,
            technician_id=technician_id,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    payload: JobCreate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobResponse:
    """Create a job, optionally pre-scheduled and/or pre-assigned to workers."""
    service = JobService(db)
    return await service.create(membership.workspace_id, payload.model_dump())


@router.get("/calendar/mine", response_model=JobListResponse)
async def list_my_calendar(
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    db: DB,
    date_from: datetime | None = Query(None, description="Jobs scheduled on or after this time"),
    date_to: datetime | None = Query(None, description="Jobs scheduled on or before this time"),
) -> JobListResponse:
    """Jobs assigned to the current user, shown on *their* calendar.

    Resolves the signed-in user to their technician record(s) in this workspace.
    Returns an empty list (not an error) when the user is not a field worker.
    """
    service = JobService(db)
    return JobListResponse(
        **await service.list_for_user(
            workspace.id,
            current_user.id,
            date_from=date_from,
            date_to=date_to,
        )
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> JobResponse:
    """Get a single job with its assigned technicians."""
    service = JobService(db)
    return await service.get(job_id, workspace.id)


@router.patch("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: uuid.UUID,
    payload: JobUpdate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobResponse:
    """Partially update a job. Status is recomputed when the window changes."""
    service = JobService(db)
    return await service.update(
        job_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/{job_id}", status_code=204)
async def delete_job(
    job_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> None:
    """Delete a job. Its technician assignments are removed (cascade)."""
    service = JobService(db)
    await service.delete(job_id, membership.workspace_id)


@router.post("/{job_id}/schedule", response_model=JobResponse)
async def schedule_job(
    job_id: uuid.UUID,
    payload: JobScheduleRequest,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobResponse:
    """Set a job's time window (flips unscheduled -> scheduled)."""
    service = JobService(db)
    return await service.schedule(
        job_id,
        membership.workspace_id,
        payload.scheduled_start,
        payload.scheduled_end,
    )


@router.post("/{job_id}/assignments", response_model=JobResponse)
async def assign_technicians(
    job_id: uuid.UUID,
    payload: JobAssignRequest,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobResponse:
    """Tag technicians onto a job (idempotent)."""
    service = JobService(db)
    return await service.assign_technicians(job_id, membership.workspace_id, payload.technician_ids)


@router.delete("/{job_id}/assignments/{technician_id}", response_model=JobResponse)
async def unassign_technician(
    job_id: uuid.UUID,
    technician_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobResponse:
    """Untag a technician from a job (no-op if not tagged)."""
    service = JobService(db)
    return await service.unassign_technician(job_id, membership.workspace_id, technician_id)
