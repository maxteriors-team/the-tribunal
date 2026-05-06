"""Segment endpoints."""

import uuid

from fastapi import APIRouter, Request

from app.api.deps import DB, CurrentUser, get_workspace
from app.schemas.segment import (
    SegmentContactsResponse,
    SegmentCreate,
    SegmentListResponse,
    SegmentResponse,
    SegmentUpdate,
)
from app.services.segments import SegmentService

router = APIRouter()


@router.get("", response_model=SegmentListResponse)
async def list_segments(
    request: Request,
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> SegmentListResponse:
    """List all segments for a workspace."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    result = await service.list_segments(workspace.id)
    return SegmentListResponse(**result)


@router.post("", response_model=SegmentResponse, status_code=201)
async def create_segment(
    request: Request,
    workspace_id: uuid.UUID,
    segment_in: SegmentCreate,
    current_user: CurrentUser,
    db: DB,
) -> SegmentResponse:
    """Create a new segment."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    return await service.create_segment(
        workspace_id=workspace.id,
        name=segment_in.name,
        definition=segment_in.definition.model_dump(),
        description=segment_in.description,
        is_dynamic=segment_in.is_dynamic,
    )


@router.get("/{segment_id}", response_model=SegmentResponse)
async def get_segment(
    request: Request,
    workspace_id: uuid.UUID,
    segment_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> SegmentResponse:
    """Get a specific segment."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    return await service.get_segment(segment_id, workspace.id)


@router.put("/{segment_id}", response_model=SegmentResponse)
async def update_segment(
    request: Request,
    workspace_id: uuid.UUID,
    segment_id: uuid.UUID,
    segment_in: SegmentUpdate,
    current_user: CurrentUser,
    db: DB,
) -> SegmentResponse:
    """Update a segment."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    update_data = segment_in.model_dump(exclude_unset=True)
    # Convert FilterDefinition to dict if present
    if "definition" in update_data and update_data["definition"] is not None:
        defn = update_data["definition"]
        if hasattr(defn, "model_dump"):
            update_data["definition"] = defn.model_dump()
    return await service.update_segment(segment_id, workspace.id, update_data)


@router.delete("/{segment_id}", status_code=204)
async def delete_segment(
    request: Request,
    workspace_id: uuid.UUID,
    segment_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> None:
    """Delete a segment."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    await service.delete_segment(segment_id, workspace.id)


@router.get("/{segment_id}/contacts", response_model=SegmentContactsResponse)
async def get_segment_contacts(
    request: Request,
    workspace_id: uuid.UUID,
    segment_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> SegmentContactsResponse:
    """Resolve a segment to contact IDs."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    result = await service.get_segment_contacts(segment_id, workspace.id)
    return SegmentContactsResponse(**result)


@router.post("/{segment_id}/refresh", response_model=SegmentResponse)
async def refresh_segment(
    request: Request,
    workspace_id: uuid.UUID,
    segment_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
) -> SegmentResponse:
    """Refresh a segment's cached contact count."""
    workspace = await get_workspace(request, workspace_id, current_user, db)
    service = SegmentService(db)
    return await service.refresh_segment(segment_id, workspace.id)
