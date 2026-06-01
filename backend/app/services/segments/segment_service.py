"""Segment service - business logic orchestration layer."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.pagination import list_response
from app.schemas.segment import SegmentResponse
from app.services.segments.segment_repository import (
    create_segment,
    delete_segment,
    get_segment_by_id,
    list_segments,
    resolve_segment_contacts,
    update_segment,
)

logger = structlog.get_logger()


class SegmentService:
    """High-level segment service for orchestrating business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="segment")

    async def list_segments(
        self,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        """List all segments for a workspace."""
        segments = await list_segments(workspace_id, self.db)
        items = [SegmentResponse.model_validate(s) for s in segments]
        return list_response(items)

    async def get_segment(
        self,
        segment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> SegmentResponse:
        """Get a specific segment."""
        segment = await get_segment_by_id(segment_id, workspace_id, self.db)
        if segment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )
        return SegmentResponse.model_validate(segment)

    async def create_segment(
        self,
        workspace_id: uuid.UUID,
        name: str,
        definition: dict[str, Any],
        description: str | None = None,
        is_dynamic: bool = True,
    ) -> SegmentResponse:
        """Create a new segment."""
        segment = await create_segment(
            workspace_id=workspace_id,
            name=name,
            definition=definition,
            db=self.db,
            description=description,
            is_dynamic=is_dynamic,
        )
        return SegmentResponse.model_validate(segment)

    async def update_segment(
        self,
        segment_id: uuid.UUID,
        workspace_id: uuid.UUID,
        update_data: dict[str, Any],
    ) -> SegmentResponse:
        """Update a segment."""
        segment = await get_segment_by_id(segment_id, workspace_id, self.db)
        if segment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )
        updated = await update_segment(segment, self.db, update_data)
        return SegmentResponse.model_validate(updated)

    async def delete_segment(
        self,
        segment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        """Delete a segment."""
        segment = await get_segment_by_id(segment_id, workspace_id, self.db)
        if segment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )
        await delete_segment(segment, self.db)

    async def get_segment_contacts(
        self,
        segment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Resolve a segment to contact IDs."""
        segment = await get_segment_by_id(segment_id, workspace_id, self.db)
        if segment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )
        ids, total = await resolve_segment_contacts(segment, self.db)
        return {"ids": ids, "total": total}

    async def refresh_segment(
        self,
        segment_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> SegmentResponse:
        """Refresh a segment's cached contact count."""
        segment = await get_segment_by_id(segment_id, workspace_id, self.db)
        if segment is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Segment not found",
            )
        _ids, total = await resolve_segment_contacts(segment, self.db)
        updated = await update_segment(
            segment,
            self.db,
            {
                "contact_count": total,
                "last_computed_at": datetime.now(UTC),
            },
        )
        return SegmentResponse.model_validate(updated)
