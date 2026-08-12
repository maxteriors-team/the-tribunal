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
    CanReadBilling,
    CanWriteJobs,
    CurrentMembership,
    CurrentUser,
    TransactionalDB,
    WorkspaceAccess,
    WorkspaceDispatcher,
)
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability, role_can
from app.models.field_service import JobStatus
from app.models.workspace import WorkspaceMembership
from app.schemas.inventory import (
    InventoryLedgerEntryResponse,
    JobMaterialCreate,
    JobMaterialsResponse,
)
from app.schemas.job import (
    JobAssignRequest,
    JobCreate,
    JobInstallationPlanResponse,
    JobListResponse,
    JobResponse,
    JobScheduleRequest,
    JobUpdate,
)
from app.schemas.job_costing import (
    ClockInRequest,
    JobExpenseCreate,
    JobExpenseResponse,
    JobProfitability,
    TimeEntryCreate,
    TimeEntryResponse,
)
from app.schemas.neighbor_outreach import (
    NeighborOutreachBatchResponse,
    NeighborOutreachCampaignRequest,
    NeighborOutreachCampaignResponse,
    NeighborOutreachEntryResponse,
    NeighborOutreachEntryUpdate,
    NeighborOutreachExportResponse,
    NeighborOutreachGenerateRequest,
)
from app.services.field_service.neighbor_outreach import NeighborOutreachService
from app.services.jobs import JobCostingService, JobMaterialsService, JobService

router = APIRouter(route_class=ServiceErrorRoute)


def _can_see_costs(membership: WorkspaceMembership) -> bool:
    """Whether this caller may see money on a job (rates, labour cost, expenses).

    ``billing:read`` is the same capability that guards ``/profitability``, so
    one tier boundary governs every monetary field on a job. The field tier
    (``jobs:read`` only) is below it.
    """
    return role_can(membership.role, Capability.BILLING_READ)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    workspace: WorkspaceAccess,
    db: DB,
    status: JobStatus | None = None,
    crew_id: uuid.UUID | None = None,
    business_location_id: uuid.UUID | None = None,
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
            business_location_id=business_location_id,
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


@router.get("/{job_id}/installation-plan", response_model=JobInstallationPlanResponse)
async def get_job_installation_plan(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
) -> JobInstallationPlanResponse:
    """Private selected sheet for authorized office staff or assigned installers."""
    return await JobService(db).get_installation_plan(
        job_id,
        workspace.id,
        membership=membership,
        user_id=current_user.id,
    )


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


# --------------------------------------------------------------------------- #
# Field execution: time tracking, expenses, profitability.
#
# Time entries stay open to any workspace member — a field technician must be
# able to clock in/out and see whether the timer is running — but the money on
# them (``rate``, ``labor_cost``) is redacted to 0 for callers without
# ``billing:read``, and a rate they submit is discarded. Expense *reads* are
# gated outright: an expense row is nothing but a cost, so there is no price-free
# projection worth serving. Profitability stays gated as before.
#
# This is the server-side half of the UI hiding done in edc79b5, which was a
# display filter only: the payloads still carried the amounts. Every call is
# workspace-scoped in the service.
# --------------------------------------------------------------------------- #
@router.get("/{job_id}/time-entries", response_model=list[TimeEntryResponse])
async def list_time_entries(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    db: DB,
) -> list[TimeEntryResponse]:
    """List a job's time entries, newest first (money redacted below billing:read)."""
    return await JobCostingService(db).list_time_entries(
        job_id, workspace.id, include_costs=_can_see_costs(membership)
    )


@router.post("/{job_id}/time-entries/clock-in", response_model=TimeEntryResponse, status_code=201)
async def clock_in(
    job_id: uuid.UUID,
    payload: ClockInRequest,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Start the clock on a job (rejected if a timer is already running)."""
    return await JobCostingService(db).clock_in(
        job_id,
        workspace.id,
        payload,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
    )


@router.post("/{job_id}/time-entries/clock-out", response_model=TimeEntryResponse)
async def clock_out(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Stop the job's running timer."""
    return await JobCostingService(db).clock_out(
        job_id, workspace.id, include_costs=_can_see_costs(membership)
    )


@router.post("/{job_id}/time-entries", response_model=TimeEntryResponse, status_code=201)
async def add_time_entry(
    job_id: uuid.UUID,
    payload: TimeEntryCreate,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Log a completed time entry with an explicit start and end."""
    return await JobCostingService(db).add_time_entry(
        job_id,
        workspace.id,
        payload,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
    )


@router.delete("/{job_id}/time-entries/{entry_id}", status_code=204)
async def delete_time_entry(
    job_id: uuid.UUID,
    entry_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: TransactionalDB,
) -> None:
    """Delete a time entry."""
    await JobCostingService(db).delete_time_entry(job_id, workspace.id, entry_id)


@router.get("/{job_id}/expenses", response_model=list[JobExpenseResponse])
async def list_expenses(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadBilling,
    db: DB,
) -> list[JobExpenseResponse]:
    """List a job's expenses, newest first.

    Gated on ``billing:read``: every field on an expense is a cost the customer
    never sees and a technician has no operational use for. A field technician
    may still *record* one (POST below) — that only echoes back the amount they
    submitted — but cannot read the job's costs back out.
    """
    return await JobCostingService(db).list_expenses(job_id, workspace.id)


@router.post("/{job_id}/expenses", response_model=JobExpenseResponse, status_code=201)
async def add_expense(
    job_id: uuid.UUID,
    payload: JobExpenseCreate,
    workspace: WorkspaceAccess,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> JobExpenseResponse:
    """Record a cost incurred on a job.

    Open to any workspace member so a technician can still log that a cost
    happened; the response only reflects the amount the caller just supplied, so
    it discloses nothing they did not already know.
    """
    return await JobCostingService(db).add_expense(
        job_id, workspace.id, payload, created_by_id=current_user.id
    )


@router.delete("/{job_id}/expenses/{expense_id}", status_code=204)
async def delete_expense(
    job_id: uuid.UUID,
    expense_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: TransactionalDB,
) -> None:
    """Delete an expense."""
    await JobCostingService(db).delete_expense(job_id, workspace.id, expense_id)


@router.get("/{job_id}/profitability", response_model=JobProfitability)
async def job_profitability(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadBilling,
    db: DB,
) -> JobProfitability:
    """Compute the job's P&L (revenue from the linked invoice minus costs).

    Gated on ``billing:read``: the P&L exposes customer revenue, profit, and
    margin, so a field technician (``jobs:read`` only, no billing) must not see
    it — even though they can still log their own time and expenses on the job.
    """
    return await JobCostingService(db).get_profitability(job_id, workspace.id)


# --------------------------------------------------------------------------- #
# Neighbor outreach: turning a finished job into leads from the same street.
#
# Reads are open to any workspace member (a technician can see who else on the
# street to leave a hanger with); everything that creates a list, changes an
# entry, exports addresses, or touches the messaging path is dispatcher-gated —
# the export payload is customer PII and enrollment spends the workspace's
# sending reputation.
# --------------------------------------------------------------------------- #
@router.get("/{job_id}/neighbors", response_model=NeighborOutreachBatchResponse)
async def get_job_neighbors(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> NeighborOutreachBatchResponse:
    """The generated neighbour list for a job, nearest first (404 until generated)."""
    return await NeighborOutreachService(db).get_for_job(job_id, workspace.id)


@router.post(
    "/{job_id}/neighbors",
    response_model=NeighborOutreachBatchResponse,
    status_code=201,
)
async def generate_job_neighbors(
    job_id: uuid.UUID,
    payload: NeighborOutreachGenerateRequest,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> NeighborOutreachBatchResponse:
    """Generate (or top up) the job's neighbour list.

    Idempotent: re-running reuses the job's existing batch and appends only newly
    in-radius sites, so statuses an operator already set are never reset and no
    house is worked twice for the same job.
    """
    return await NeighborOutreachService(db).generate_for_job(
        job_id,
        membership.workspace_id,
        radius_meters=payload.radius_meters,
        max_neighbors=payload.max_neighbors,
    )


@router.get("/{job_id}/neighbors/export", response_model=NeighborOutreachExportResponse)
async def export_job_neighbors(
    job_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: DB,
) -> NeighborOutreachExportResponse:
    """Door-hanger / direct-mail list for the job's neighbours.

    Dispatcher-gated because the rows carry neighbours' postal addresses decrypted
    out of ``service_locations`` — the default, always-legal output channel, but
    customer PII all the same.
    """
    return await NeighborOutreachService(db).export(job_id, membership.workspace_id)


@router.patch(
    "/{job_id}/neighbors/entries/{entry_id}",
    response_model=NeighborOutreachEntryResponse,
)
async def update_job_neighbor_entry(
    job_id: uuid.UUID,
    entry_id: uuid.UUID,
    payload: NeighborOutreachEntryUpdate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> NeighborOutreachEntryResponse:
    """Mark a neighbour contacted/skipped/converted, or add a note."""
    return await NeighborOutreachService(db).update_entry(
        entry_id, membership.workspace_id, payload
    )


@router.post(
    "/{job_id}/neighbors/campaign",
    response_model=NeighborOutreachCampaignResponse,
)
async def enroll_job_neighbors_in_campaign(
    job_id: uuid.UUID,
    payload: NeighborOutreachCampaignRequest,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> NeighborOutreachCampaignResponse:
    """Enroll the *consented* subset of the batch into an existing campaign.

    Neighbours with no contact record, no recorded consent, or a global opt-out are
    left on the print channel and reported in ``blocked_by_reason``. Zero
    enrollments on a street of strangers is the correct result.
    """
    return await NeighborOutreachService(db).enroll_in_campaign(
        job_id, membership.workspace_id, payload
    )


# --------------------------------------------------------------------------- #
# Job materials: stock consumed delivering the job.
#
# Posting a material writes an inventory ledger row (``reason='job_usage'``,
# ``reference_type='job'``) — it does **not** create a ``JobExpense``. That is
# the one rule that keeps materials from being counted twice, since job expenses
# already have a free-form "materials" category. The cost is the server-side
# weighted average at posting time; the request has no cost field at all.
#
# Deleting a material posts a compensating ``return_to_stock`` row at the cost
# it left with. The ledger is an audit trail: an undo is a new entry, never a
# deletion.
# --------------------------------------------------------------------------- #
@router.get("/{job_id}/materials", response_model=JobMaterialsResponse)
async def list_job_materials(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    db: DB,
) -> JobMaterialsResponse:
    """Materials consumed on a job (costs redacted below billing:read)."""
    return await JobMaterialsService(db).list_for_job(
        job_id, workspace.id, include_costs=_can_see_costs(membership)
    )


@router.post(
    "/{job_id}/materials",
    response_model=InventoryLedgerEntryResponse,
    status_code=201,
)
async def add_job_material(
    job_id: uuid.UUID,
    payload: JobMaterialCreate,
    membership: CanWriteJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> InventoryLedgerEntryResponse:
    """Consume stock on a job, valued at the item's current average cost."""
    return await JobMaterialsService(db).consume_for_job(
        job_id,
        membership.workspace_id,
        payload,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
    )


@router.delete(
    "/{job_id}/materials/{entry_id}",
    response_model=InventoryLedgerEntryResponse,
)
async def remove_job_material(
    job_id: uuid.UUID,
    entry_id: uuid.UUID,
    membership: CanWriteJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> InventoryLedgerEntryResponse:
    """Undo a material line by returning it to stock (never deletes history)."""
    return await JobMaterialsService(db).return_for_job(
        job_id,
        membership.workspace_id,
        entry_id,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
    )
