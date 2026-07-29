"""Service plan endpoints (recurring job templates).

A plan repeats a job on a schedule; a background worker materializes the next
concrete job as its due date approaches (see
:mod:`app.workers.recurring_job_worker`). Operators can also force-generate the
next job on demand via ``POST /{id}/run``.

The path stays ``recurring-jobs`` while the product surface is called Service
Plans: renaming it would 404 the live frontend during the window where the new
backend is deployed but the old frontend is still being served.

Reads are available to any workspace member; writes are gated to dispatchers and
up, mirroring :mod:`app.api.v1.jobs`. Writes run on the transactional session so
a failed reference validation rolls back cleanly.
"""

import uuid

from fastapi import APIRouter

from app.api.deps import (
    DB,
    CurrentUser,
    TransactionalDB,
    WorkspaceAccess,
    WorkspaceDispatcher,
)
from app.models.recurring_job import ServicePlanType
from app.schemas.recurring_job import (
    RecurringJobRunResponse,
    RecurringJobTemplateCreate,
    RecurringJobTemplateListResponse,
    RecurringJobTemplateResponse,
    RecurringJobTemplateUpdate,
)
from app.services.recurring_jobs import RecurringJobService

router = APIRouter()


@router.get("", response_model=RecurringJobTemplateListResponse)
async def list_templates(
    workspace: WorkspaceAccess,
    db: DB,
    is_active: bool | None = None,
    plan_type: ServicePlanType | None = None,
) -> RecurringJobTemplateListResponse:
    """List service plans, soonest next-occurrence first."""
    service = RecurringJobService(db)
    return RecurringJobTemplateListResponse(
        **await service.list(workspace.id, is_active=is_active, plan_type=plan_type)
    )


@router.post("", response_model=RecurringJobTemplateResponse, status_code=201)
async def create_template(
    payload: RecurringJobTemplateCreate,
    membership: WorkspaceDispatcher,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> RecurringJobTemplateResponse:
    """Create a recurring job template."""
    service = RecurringJobService(db)
    return await service.create(
        membership.workspace_id, payload.model_dump(), created_by_id=current_user.id
    )


@router.get("/{template_id}", response_model=RecurringJobTemplateResponse)
async def get_template(
    template_id: uuid.UUID,
    workspace: WorkspaceAccess,
    db: DB,
) -> RecurringJobTemplateResponse:
    """Get a single recurring job template."""
    service = RecurringJobService(db)
    return await service.get(template_id, workspace.id)


@router.patch("/{template_id}", response_model=RecurringJobTemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: RecurringJobTemplateUpdate,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> RecurringJobTemplateResponse:
    """Partially update a recurring job template."""
    service = RecurringJobService(db)
    return await service.update(
        template_id, membership.workspace_id, payload.model_dump(exclude_unset=True)
    )


@router.delete("/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> None:
    """Delete a recurring job template. Generated jobs are kept (link cleared)."""
    service = RecurringJobService(db)
    await service.delete(template_id, membership.workspace_id)


@router.post("/{template_id}/run", response_model=RecurringJobRunResponse)
async def run_template(
    template_id: uuid.UUID,
    membership: WorkspaceDispatcher,
    db: TransactionalDB,
) -> RecurringJobRunResponse:
    """Force-generate the next occurrence(s) for this template now."""
    service = RecurringJobService(db)
    result = await service.run_template(template_id, membership.workspace_id)
    return RecurringJobRunResponse(**result)
