"""Bookable staff pool endpoints (nested under an agent).

Manages the pool of bookable staff/resources used by round-robin and
skill-based appointment routing. Mounted at
``/workspaces/{workspace_id}/agents/{agent_id}/staff``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DB, CurrentUser, get_workspace
from app.api.service_errors import ServiceErrorRoute
from app.models.workspace import Workspace
from app.schemas.bookable_staff import (
    BookableStaffCreate,
    BookableStaffList,
    BookableStaffResponse,
    BookableStaffUpdate,
)
from app.services.calendar.bookable_staff_service import BookableStaffService

router = APIRouter(route_class=ServiceErrorRoute)


@router.get("", response_model=BookableStaffList)
async def list_bookable_staff(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> BookableStaffList:
    """List the bookable staff in an agent's assignment pool."""
    return await BookableStaffService(db).list_staff(workspace_id, agent_id)


@router.post("", response_model=BookableStaffResponse, status_code=status.HTTP_201_CREATED)
async def create_bookable_staff(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: BookableStaffCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> BookableStaffResponse:
    """Add a staff member to an agent's pool."""
    staff = await BookableStaffService(db).create_staff(workspace_id, agent_id, body)
    return BookableStaffResponse.model_validate(staff)


@router.put("/{staff_id}", response_model=BookableStaffResponse)
async def update_bookable_staff(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    staff_id: uuid.UUID,
    body: BookableStaffUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> BookableStaffResponse:
    """Update a staff member's configuration."""
    staff = await BookableStaffService(db).update_staff(workspace_id, agent_id, staff_id, body)
    return BookableStaffResponse.model_validate(staff)


@router.delete("/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookable_staff(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    staff_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Remove a staff member from the pool."""
    await BookableStaffService(db).delete_staff(workspace_id, agent_id, staff_id)
