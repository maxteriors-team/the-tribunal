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
from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import load_only

from app.api.deps import (
    DB,
    CanReadBilling,
    CanReadCRM,
    CanReadJobs,
    CanWriteBilling,
    CanWriteJobs,
    CanWriteOutreach,
    CurrentMembership,
    CurrentUser,
    TransactionalDB,
    WorkspaceAccess,
    WorkspaceDispatcher,
)
from app.api.handoff_images import (
    count_handoff_images,
    lock_handoff_image_collection,
    read_handoff_image_upload,
)
from app.api.service_errors import ServiceErrorRoute
from app.api.v1.contact_attachments import content_disposition
from app.core.permissions import (
    Capability,
    job_expense_owner_scope,
    role_can,
    time_entry_owner_scope,
)
from app.models.field_service import JobStatus
from app.models.job_handoff_image import JobHandoffImage
from app.models.quote_handoff_image import (
    MAX_HANDOFF_IMAGE_BYTES,
    MAX_HANDOFF_IMAGES_PER_QUOTE,
    QuoteHandoffImage,
)
from app.models.workspace import WorkspaceMembership
from app.schemas.handoff_image import HandoffImageListResponse, HandoffImageResponse
from app.schemas.inventory import (
    CompleteJobInventoryRequest,
    InventoryJobAllocationResponse,
    InventoryLedgerEntryResponse,
    JobInventoryPlanResponse,
    JobMaterialCreate,
    JobMaterialsResponse,
)
from app.schemas.job import (
    JobAssignRequest,
    JobCreate,
    JobInstallationPlanResponse,
    JobListResponse,
    JobPricingReplace,
    JobPricingResponse,
    JobResponse,
    JobScheduleRequest,
    JobUpdate,
    JobVisitCreate,
    JobVisitResponse,
    JobVisitUpdate,
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
from app.services.inventory import JobAllocationService
from app.services.jobs import JobCostingService, JobMaterialsService, JobService

logger = structlog.get_logger(__name__)
router = APIRouter(route_class=ServiceErrorRoute)

_QUOTE_HANDOFF_IMAGE_METADATA_COLUMNS = (
    QuoteHandoffImage.id,
    QuoteHandoffImage.filename,
    QuoteHandoffImage.content_type,
    QuoteHandoffImage.size_bytes,
    QuoteHandoffImage.created_at,
)
_JOB_HANDOFF_IMAGE_METADATA_COLUMNS = (
    JobHandoffImage.id,
    JobHandoffImage.filename,
    JobHandoffImage.content_type,
    JobHandoffImage.size_bytes,
    JobHandoffImage.created_at,
)


def _can_see_costs(membership: WorkspaceMembership) -> bool:
    """Whether this caller may see money on a job (rates, labour cost, expenses).

    ``billing:read`` is the same capability that guards ``/profitability``, so
    one tier boundary governs every monetary field on a job. The field tier
    (``jobs:read`` only) is below it.
    """
    return role_can(membership.role, Capability.BILLING_READ)


def _time_entry_payload_updates(membership: WorkspaceMembership, user_id: int) -> dict[str, object]:
    """Strip timer ownership and rate fields the caller cannot control."""
    updates: dict[str, object] = {}
    if time_entry_owner_scope(membership.role, user_id) is not None:
        updates["technician_id"] = None
    if not role_can(membership.role, Capability.BILLING_WRITE):
        updates["rate"] = Decimal("0")
    return updates


def _calendar_scope_user_id(
    membership: WorkspaceMembership, user_id: int, *, mine: bool = False
) -> int | None:
    """The user a caller's job reads are confined to, or ``None`` for the whole board.

    ``jobs:write`` is the dispatch line — owner, admin, manager, dispatcher.
    They run the board, so they read all of it. Everyone below (sales, tech,
    lead, field) sees only the jobs they are tagged on, which is the same
    predicate their own calendar already uses.

    Keying off the capability rather than naming roles keeps the read boundary
    on exactly the same line as the write boundary, and fails closed for
    unknown/legacy role strings (they resolve to the field tier).

    ``mine`` lets a dispatcher voluntarily narrow to their own work. It can only
    ever tighten the scope — there is no value of it that widens the field
    tier's view.
    """
    if mine or not role_can(membership.role, Capability.JOBS_WRITE):
        return user_id
    return None


@router.get("", response_model=JobListResponse)
async def list_jobs(
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
    status: JobStatus | None = None,
    crew_id: uuid.UUID | None = None,
    business_location_id: uuid.UUID | None = None,
    technician_id: uuid.UUID | None = None,
    date_from: datetime | None = Query(None, description="Jobs scheduled on or after this time"),
    date_to: datetime | None = Query(None, description="Jobs scheduled on or before this time"),
    mine: bool = Query(False, description="Only jobs the caller is assigned to"),
) -> JobListResponse:
    """List jobs for the dispatch board / calendar, with optional filters.

    Dispatchers and up see the whole board. Below that line the list is scoped
    server-side to the jobs the caller is assigned to — the requested filters
    narrow that set further, they never widen it.

    ``mine=true`` narrows the result to the caller's own work whatever their
    role; for the field tier it is already implied.
    """
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
            visible_to_user_id=_calendar_scope_user_id(membership, current_user.id, mine=mine),
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
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
) -> JobResponse:
    """Get a single job with its assigned technicians.

    Carries the same visibility scope as the list, so a deep link to somebody
    else's job 404s for the field tier instead of routing around the filter.
    """
    service = JobService(db)
    return await service.get(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post(
    "/{job_id}/handoff-images",
    response_model=HandoffImageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_job_handoff_image(
    job_id: uuid.UUID,
    file: UploadFile,
    membership: CanWriteJobs,
    current_user: CurrentUser,
    db: DB,
) -> HandoffImageResponse:
    """Store one office-authored image after locking the shared collection."""
    await JobService(db).get(job_id, membership.workspace_id)
    filename, content_type, data = await read_handoff_image_upload(file)
    source_quote_id, locked_job_id = await lock_handoff_image_collection(
        db, membership.workspace_id, job_id=job_id
    )
    image_count = await count_handoff_images(
        db,
        membership.workspace_id,
        quote_id=source_quote_id,
        job_id=locked_job_id,
    )
    if image_count >= MAX_HANDOFF_IMAGES_PER_QUOTE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A job can have at most {MAX_HANDOFF_IMAGES_PER_QUOTE} handoff images, "
                "including source quote images"
            ),
        )

    image = JobHandoffImage(
        workspace_id=membership.workspace_id,
        job_id=job_id,
        filename=filename,
        content_type=content_type,
        size_bytes=len(data),
        data=data,
        uploaded_by_user_id=current_user.id,
    )
    db.add(image)
    await db.commit()
    await db.refresh(image)
    logger.info(
        "job_handoff_image_uploaded",
        workspace_id=str(membership.workspace_id),
        job_id=str(job_id),
        image_id=str(image.id),
        size_bytes=image.size_bytes,
    )
    return HandoffImageResponse.model_validate(image)


@router.get("/{job_id}/handoff-images", response_model=HandoffImageListResponse)
async def list_job_handoff_images(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: DB,
) -> HandoffImageListResponse:
    """List job and source-quote images after applying job visibility rules."""
    job = await JobService(db).get(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )
    quote_rows: list[QuoteHandoffImage] = []
    if job.source_quote_id is not None:
        quote_rows = list(
            (
                await db.execute(
                    select(QuoteHandoffImage)
                    .options(load_only(*_QUOTE_HANDOFF_IMAGE_METADATA_COLUMNS))
                    .where(
                        QuoteHandoffImage.workspace_id == workspace.id,
                        QuoteHandoffImage.quote_id == job.source_quote_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    job_rows = list(
        (
            await db.execute(
                select(JobHandoffImage)
                .options(load_only(*_JOB_HANDOFF_IMAGE_METADATA_COLUMNS))
                .where(
                    JobHandoffImage.workspace_id == workspace.id,
                    JobHandoffImage.job_id == job_id,
                )
            )
        )
        .scalars()
        .all()
    )
    images = sorted(
        [HandoffImageResponse.model_validate(row) for row in [*quote_rows, *job_rows]],
        key=lambda image: image.created_at,
        reverse=True,
    )
    return HandoffImageListResponse(
        images=images,
        max_images=MAX_HANDOFF_IMAGES_PER_QUOTE,
        max_image_bytes=MAX_HANDOFF_IMAGE_BYTES,
    )


@router.get("/{job_id}/handoff-images/{image_id}/download")
async def download_job_handoff_image(
    job_id: uuid.UUID,
    image_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: DB,
) -> Response:
    """Serve one job-visible image from either private storage owner."""
    job = await JobService(db).get(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )
    image: JobHandoffImage | QuoteHandoffImage | None = (
        await db.execute(
            select(JobHandoffImage).where(
                JobHandoffImage.id == image_id,
                JobHandoffImage.workspace_id == workspace.id,
                JobHandoffImage.job_id == job_id,
            )
        )
    ).scalar_one_or_none()
    if image is None and job.source_quote_id is not None:
        image = (
            await db.execute(
                select(QuoteHandoffImage).where(
                    QuoteHandoffImage.id == image_id,
                    QuoteHandoffImage.workspace_id == workspace.id,
                    QuoteHandoffImage.quote_id == job.source_quote_id,
                )
            )
        ).scalar_one_or_none()
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handoff image not found",
        )
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            "Content-Disposition": content_disposition(image.filename, image.content_type),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.delete(
    "/{job_id}/handoff-images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_job_handoff_image(
    job_id: uuid.UUID,
    image_id: uuid.UUID,
    membership: CanWriteJobs,
    db: DB,
) -> None:
    """Delete only a job-owned image from an office-visible job."""
    await JobService(db).get(job_id, membership.workspace_id)
    image = (
        await db.execute(
            select(JobHandoffImage)
            .options(load_only(JobHandoffImage.id, JobHandoffImage.size_bytes))
            .where(
                JobHandoffImage.id == image_id,
                JobHandoffImage.workspace_id == membership.workspace_id,
                JobHandoffImage.job_id == job_id,
            )
        )
    ).scalar_one_or_none()
    if image is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Handoff image not found",
        )
    size_bytes = image.size_bytes
    await db.delete(image)
    await db.commit()
    logger.info(
        "job_handoff_image_deleted",
        workspace_id=str(membership.workspace_id),
        job_id=str(job_id),
        image_id=str(image_id),
        size_bytes=size_bytes,
    )


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


@router.get("/{job_id}/inventory-plan", response_model=JobInventoryPlanResponse)
async def get_job_inventory_plan(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
) -> JobInventoryPlanResponse:
    """Return inventory allocations after applying normal job visibility rules."""
    await JobService(db).get(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )
    return await JobAllocationService(db).get_plan(workspace.id, job_id)


@router.post("/{job_id}/complete-with-inventory", response_model=JobInventoryPlanResponse)
async def complete_job_with_inventory(
    job_id: uuid.UUID,
    payload: CompleteJobInventoryRequest,
    membership: CanWriteJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> JobInventoryPlanResponse:
    """Post actual Bistro inventory and complete the job in one transaction."""
    return await JobAllocationService(db).complete(
        membership.workspace_id,
        job_id,
        payload,
        created_by_id=current_user.id,
    )


@router.post(
    "/{job_id}/inventory-allocations/{allocation_id}/return",
    response_model=InventoryJobAllocationResponse,
)
async def return_job_inventory_allocation(
    job_id: uuid.UUID,
    allocation_id: uuid.UUID,
    membership: CanWriteJobs,
    db: TransactionalDB,
) -> InventoryJobAllocationResponse:
    """Return one deployed reusable allocation without changing owned stock."""
    return await JobAllocationService(db).return_reusable(
        membership.workspace_id, job_id, allocation_id
    )


@router.get("/{job_id}/visits", response_model=list[JobVisitResponse])
async def list_job_visits(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
) -> list[JobVisitResponse]:
    """List visits after applying the same job visibility boundary as job detail."""
    service = JobService(db)
    await service.get(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )
    return await service.list_visits(job_id, workspace.id)


@router.post("/{job_id}/visits", response_model=JobVisitResponse, status_code=201)
async def create_job_visit(
    job_id: uuid.UUID,
    payload: JobVisitCreate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobVisitResponse:
    return await JobService(db).create_visit(job_id, membership.workspace_id, payload.model_dump())


@router.patch("/{job_id}/visits/{visit_id}", response_model=JobVisitResponse)
async def update_job_visit(
    job_id: uuid.UUID,
    visit_id: uuid.UUID,
    payload: JobVisitUpdate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> JobVisitResponse:
    return await JobService(db).update_visit(
        job_id,
        visit_id,
        membership.workspace_id,
        payload.model_dump(exclude_unset=True),
    )


@router.delete("/{job_id}/visits/{visit_id}", status_code=204)
async def delete_job_visit(
    job_id: uuid.UUID,
    visit_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> None:
    await JobService(db).delete_visit(job_id, visit_id, membership.workspace_id)


@router.get("/{job_id}/pricing", response_model=JobPricingResponse)
async def get_job_pricing(
    job_id: uuid.UUID,
    membership: CanReadBilling,
    current_user: CurrentUser,
    db: DB,
) -> JobPricingResponse:
    """Return priced scope only when both job visibility and billing access allow it."""
    service = JobService(db)
    await service.get(
        job_id,
        membership.workspace_id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )
    return await service.get_pricing(job_id, membership.workspace_id)


@router.put("/{job_id}/pricing", response_model=JobPricingResponse)
async def replace_job_pricing(
    job_id: uuid.UUID,
    payload: JobPricingReplace,
    membership: CanWriteBilling,
    db: TransactionalDB,
) -> JobPricingResponse:
    """Atomically replace job pricing for billing-authorized operators."""
    return await JobService(db).replace_pricing(
        job_id,
        membership.workspace_id,
        payload.tax_rate,
        [item.model_dump() for item in payload.items],
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
# Field users can operate only jobs assigned to them or their crew. Timer
# payloads remain price-free below billing:read, and each user controls only
# their own running timer. Expense reads and profitability stay billing-gated.
# --------------------------------------------------------------------------- #
@router.get("/{job_id}/time-entries", response_model=list[TimeEntryResponse])
async def list_time_entries(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: DB,
) -> list[TimeEntryResponse]:
    """List saved job time after applying assignment and pricing boundaries."""
    return await JobCostingService(db).list_time_entries(
        job_id,
        workspace.id,
        include_costs=_can_see_costs(membership),
        viewer_user_id=current_user.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post(
    "/{job_id}/time-entries/clock-in",
    response_model=TimeEntryResponse,
    status_code=201,
)
async def clock_in(
    job_id: uuid.UUID,
    payload: ClockInRequest,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Start or resume the signed-in user's timer on an assigned job."""
    payload = payload.model_copy(update=_time_entry_payload_updates(membership, current_user.id))
    return await JobCostingService(db).clock_in(
        job_id,
        workspace.id,
        payload,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post("/{job_id}/time-entries/pause", response_model=TimeEntryResponse)
async def pause_timer(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Pause the signed-in user's running timer."""
    return await JobCostingService(db).pause_timer(
        job_id,
        workspace.id,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post("/{job_id}/time-entries/end", response_model=TimeEntryResponse)
async def end_timer(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """End the signed-in user's running or paused timer."""
    return await JobCostingService(db).end_timer(
        job_id,
        workspace.id,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post("/{job_id}/time-entries/clock-out", response_model=TimeEntryResponse)
async def clock_out(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Backward-compatible clock-out action; equivalent to pausing."""
    return await JobCostingService(db).clock_out(
        job_id,
        workspace.id,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post("/{job_id}/time-entries", response_model=TimeEntryResponse, status_code=201)
async def add_time_entry(
    job_id: uuid.UUID,
    payload: TimeEntryCreate,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> TimeEntryResponse:
    """Log a completed manual time entry on an assigned job."""
    payload = payload.model_copy(update=_time_entry_payload_updates(membership, current_user.id))
    return await JobCostingService(db).add_time_entry(
        job_id,
        workspace.id,
        payload,
        created_by_id=current_user.id,
        include_costs=_can_see_costs(membership),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.delete("/{job_id}/time-entries/{entry_id}", status_code=204)
async def delete_time_entry(
    job_id: uuid.UUID,
    entry_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadJobs,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> None:
    """Delete an owned entry, or any entry with attendance management."""
    await JobCostingService(db).delete_time_entry(
        job_id,
        workspace.id,
        entry_id,
        restrict_to_user_id=time_entry_owner_scope(membership.role, current_user.id),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.get("/{job_id}/expenses", response_model=list[JobExpenseResponse])
async def list_expenses(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadBilling,
    current_user: CurrentUser,
    db: DB,
) -> list[JobExpenseResponse]:
    """List costs only when billing and job visibility both allow it."""
    return await JobCostingService(db).list_expenses(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.post("/{job_id}/expenses", response_model=JobExpenseResponse, status_code=201)
async def add_expense(
    job_id: uuid.UUID,
    payload: JobExpenseCreate,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> JobExpenseResponse:
    """Record a known cost on an assigned job without revealing other costs."""
    return await JobCostingService(db).add_expense(
        job_id,
        workspace.id,
        payload,
        created_by_id=current_user.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.delete("/{job_id}/expenses/{expense_id}", status_code=204)
async def delete_expense(
    job_id: uuid.UUID,
    expense_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> None:
    """Delete an owned cost, or any cost with billing write access."""
    await JobCostingService(db).delete_expense(
        job_id,
        workspace.id,
        expense_id,
        restrict_to_user_id=job_expense_owner_scope(membership.role, current_user.id),
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


@router.get("/{job_id}/profitability", response_model=JobProfitability)
async def job_profitability(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    membership: CanReadBilling,
    current_user: CurrentUser,
    db: DB,
) -> JobProfitability:
    """Compute P&L only when billing and job visibility both allow it."""
    return await JobCostingService(db).get_profitability(
        job_id,
        workspace.id,
        visible_to_user_id=_calendar_scope_user_id(membership, current_user.id),
    )


# --------------------------------------------------------------------------- #
# Neighbor outreach: turning a finished job into leads from the same street.
#
# Reads need ``crm:read``; everything that creates a list, changes an entry,
# exports addresses, or touches the messaging path is dispatcher-gated — the
# export payload is customer PII and enrollment spends the workspace's sending
# reputation.
#
# The read was previously open to any member, on the reasoning that a technician
# could see who else on the street to leave a door hanger with, and that an
# entry's ``label`` is "the site's own name, never the address". That second half
# does not hold: ``app/services/jobber/mapping.py`` names an imported site after
# its ``address_line1``, so for any workspace migrated from Jobber the label *is*
# the street address. Together with ``customer_name`` the read returned
# neighbours' names and addresses — the same data the field tier is 403 on at
# ``/contacts`` and ``/service-locations``, reached through a different door.
# --------------------------------------------------------------------------- #
@router.get("/{job_id}/neighbors", response_model=NeighborOutreachBatchResponse)
async def get_job_neighbors(
    job_id: uuid.UUID,
    workspace: WorkspaceAccess,
    _gate: CanReadCRM,
    db: DB,
) -> NeighborOutreachBatchResponse:
    """The generated neighbour list for a job, nearest first (404 until generated).

    Carries neighbours' names and, for Jobber-imported sites, their addresses, so
    this is customer data rather than an operational surface. Finding 4 of
    docs/technician-role-audit.md.
    """
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
    _gate: CanWriteOutreach,
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
