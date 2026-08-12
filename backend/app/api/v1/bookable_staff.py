"""Bookable staff pool endpoints (nested under an agent).

Manages the pool of bookable staff/resources used by round-robin and
skill-based appointment routing. Mounted at
``/workspaces/{workspace_id}/agents/{agent_id}/staff``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import DB, CurrentMembership, CurrentUser, get_workspace
from app.api.service_errors import ServiceErrorRoute
from app.core.permissions import Capability, role_can
from app.models.workspace import Workspace, WorkspaceMembership
from app.schemas.bookable_staff import (
    BookableStaffCreate,
    BookableStaffList,
    BookableStaffResponse,
    BookableStaffUpdate,
)
from app.services.calendar.bookable_staff_service import BookableStaffService

router = APIRouter(route_class=ServiceErrorRoute)


def _assert_may_link_login(membership: WorkspaceMembership, sets_user_id: bool) -> None:
    """Guard the ``user_id`` link behind ``members:manage``.

    The rest of this pool is ordinary agent configuration, but ``user_id``
    decides *whose* calendar a booking lands on — relinking a staff row would
    otherwise let any member read another person's appointments. Linking a login
    is therefore the same privilege as managing the team, wherever it is done.
    """
    if sets_user_id and not role_can(membership.role, Capability.MEMBERS_MANAGE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to link a bookable staff member to a login",
        )


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
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> BookableStaffResponse:
    """Add a staff member to an agent's pool."""
    _assert_may_link_login(membership, body.user_id is not None)
    staff = await BookableStaffService(db).create_staff(workspace_id, agent_id, body)
    return BookableStaffResponse.model_validate(staff)


@router.put("/{staff_id}", response_model=BookableStaffResponse)
async def update_bookable_staff(
    workspace_id: uuid.UUID,
    agent_id: uuid.UUID,
    staff_id: uuid.UUID,
    body: BookableStaffUpdate,
    membership: CurrentMembership,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> BookableStaffResponse:
    """Update a staff member's configuration."""
    _assert_may_link_login(membership, "user_id" in body.model_fields_set)
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
