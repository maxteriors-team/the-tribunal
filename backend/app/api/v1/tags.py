"""Tag endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import (
    DB,
    CurrentUser,
    TransactionalDB,
    get_workspace,
    require_route_capabilities,
)
from app.core.permissions import Capability
from app.models.workspace import Workspace
from app.schemas.tag import (
    BulkTagRequest,
    BulkTagResponse,
    TagCreate,
    TagListResponse,
    TagResponse,
    TagUpdate,
)
from app.services.tags import TagService

router = APIRouter(
    dependencies=[Depends(require_route_capabilities(Capability.CRM_READ, Capability.CRM_WRITE))]
)


async def _transactional_workspace(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: TransactionalDB,
) -> Workspace:
    """Resolve workspace access inside the same transaction as tag writes."""
    return await get_workspace(request, workspace_id, current_user, db)


TagWriteWorkspace = Annotated[Workspace, Depends(_transactional_workspace)]


@router.get("", response_model=TagListResponse)
async def list_tags(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> TagListResponse:
    """List all tags for a workspace."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = TagService(db)
    result = await service.list_tags(workspace.id)
    return TagListResponse(**result)


@router.post("", response_model=TagResponse, status_code=201)
async def create_tag(
    workspace_id: uuid.UUID,
    tag_in: TagCreate,
    current_user: CurrentUser,
    db: TransactionalDB,
    workspace: TagWriteWorkspace,
) -> TagResponse:
    """Create a new tag."""
    service = TagService(db)
    return await service.create_tag(
        workspace_id=workspace.id,
        name=tag_in.name,
        color=tag_in.color,
    )


@router.get("/{tag_id}", response_model=TagResponse)
async def get_tag(
    request: Request,
    workspace_id: uuid.UUID,
    tag_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> TagResponse:
    """Get a specific tag."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = TagService(db)
    return await service.get_tag(tag_id, workspace.id)


@router.put("/{tag_id}", response_model=TagResponse)
async def update_tag(
    workspace_id: uuid.UUID,
    tag_id: uuid.UUID,
    tag_in: TagUpdate,
    current_user: CurrentUser,
    db: TransactionalDB,
    workspace: TagWriteWorkspace,
) -> TagResponse:
    """Update a tag."""
    service = TagService(db)
    return await service.update_tag(
        tag_id=tag_id,
        workspace_id=workspace.id,
        update_data=tag_in.model_dump(exclude_unset=True),
    )


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(
    workspace_id: uuid.UUID,
    tag_id: uuid.UUID,
    current_user: CurrentUser,
    db: TransactionalDB,
    workspace: TagWriteWorkspace,
) -> None:
    """Delete a tag."""
    service = TagService(db)
    await service.delete_tag(tag_id, workspace.id)


@router.post("/bulk-tag", response_model=BulkTagResponse)
async def bulk_tag_contacts(
    workspace_id: uuid.UUID,
    request: BulkTagRequest,
    current_user: CurrentUser,
    db: TransactionalDB,
    workspace: TagWriteWorkspace,
) -> BulkTagResponse:
    """Bulk add/remove tags on contacts."""
    service = TagService(db)
    result = await service.bulk_tag_contacts(
        workspace_id=workspace.id,
        contact_ids=request.contact_ids,
        add_tag_ids=request.add_tag_ids,
        remove_tag_ids=request.remove_tag_ids,
    )
    return BulkTagResponse(**result)
