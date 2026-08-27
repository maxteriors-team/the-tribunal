"""Workspace-scoped lighting project API."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CanReadBilling, CanWriteBilling, CurrentUser
from app.api.service_errors import ServiceErrorRoute
from app.schemas.lighting_project import (
    LightingProjectCreate,
    LightingProjectDetail,
    LightingProjectRevision,
    LightingProjectStatus,
    LightingProjectType,
    LightingProjectUpdate,
    PaginatedLightingProjects,
)
from app.services.lighting_projects import LightingProjectService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=PaginatedLightingProjects)
async def list_lighting_projects(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
    search: Annotated[str | None, Query(max_length=200)] = None,
    project_status: Annotated[LightingProjectStatus | None, Query(alias="status")] = None,
    project_type: Annotated[LightingProjectType | None, Query()] = None,
    contact_id: Annotated[int | None, Query(gt=0)] = None,
    opportunity_id: Annotated[uuid.UUID | None, Query()] = None,
    assigned_user_id: Annotated[int | None, Query(gt=0)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> PaginatedLightingProjects:
    """List projects with CRM and archive filters."""

    return await LightingProjectService(db).list_projects(
        workspace_id,
        search=search,
        status=project_status,
        project_type=project_type,
        contact_id=contact_id,
        opportunity_id=opportunity_id,
        assigned_user_id=assigned_user_id,
        page=page,
        page_size=page_size,
    )


@router.post(
    "",
    response_model=LightingProjectDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_lighting_project(
    workspace_id: uuid.UUID,
    payload: LightingProjectCreate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> LightingProjectDetail:
    """Create a contact-linked lighting project."""

    return await LightingProjectService(db).create_project(
        workspace_id, payload, user_id=current_user.id
    )


@router.get("/{project_id}", response_model=LightingProjectDetail)
async def get_lighting_project(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
) -> LightingProjectDetail:
    """Get one project and its complete current drawing."""

    return await LightingProjectService(db).get_project(workspace_id, project_id)


@router.get("/{project_id}/revision", response_model=LightingProjectRevision)
async def get_lighting_project_revision(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    membership: CanReadBilling,
) -> LightingProjectRevision:
    """Get the lightweight version stamp used for live refresh."""

    return await LightingProjectService(db).get_project_revision(workspace_id, project_id)


@router.patch("/{project_id}", response_model=LightingProjectDetail)
async def update_lighting_project(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: LightingProjectUpdate,
    current_user: CurrentUser,
    db: DB,
    membership: CanWriteBilling,
) -> LightingProjectDetail:
    """Version-check and update one project without force-overwriting."""

    return await LightingProjectService(db).update_project(
        workspace_id,
        project_id,
        payload,
        user_id=current_user.id,
    )
