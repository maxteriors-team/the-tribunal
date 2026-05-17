"""Segment repository - data access layer for segment operations."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.segment import Segment
from app.services.contacts.contact_filters import apply_contact_filters

logger = structlog.get_logger()


async def list_segments(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> list[Segment]:
    """List all segments for a workspace."""
    result = await db.execute(
        select(Segment).where(Segment.workspace_id == workspace_id).order_by(Segment.name)
    )
    return list(result.scalars().all())


async def get_segment_by_id(
    segment_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> Segment | None:
    """Get a specific segment by ID."""
    result = await db.execute(
        select(Segment).where(
            Segment.id == segment_id,
            Segment.workspace_id == workspace_id,
        )
    )
    return result.scalar_one_or_none()


async def create_segment(
    workspace_id: uuid.UUID,
    name: str,
    definition: dict[str, Any],
    db: AsyncSession,
    description: str | None = None,
    is_dynamic: bool = True,
) -> Segment:
    """Create a new segment."""
    segment = Segment(
        workspace_id=workspace_id,
        name=name,
        description=description,
        definition=definition,
        is_dynamic=is_dynamic,
    )
    db.add(segment)
    await db.commit()
    await db.refresh(segment)
    return segment


async def update_segment(
    segment: Segment,
    db: AsyncSession,
    update_data: dict[str, Any],
) -> Segment:
    """Update a segment."""
    for field, value in update_data.items():
        setattr(segment, field, value)
    await db.commit()
    await db.refresh(segment)
    return segment


async def delete_segment(
    segment: Segment,
    db: AsyncSession,
) -> None:
    """Delete a segment."""
    await db.delete(segment)
    await db.commit()


async def resolve_segment_contacts(
    segment: Segment,
    db: AsyncSession,
) -> tuple[list[int], int]:
    """Resolve a segment's filter definition to contact IDs.

    Builds a query using apply_contact_filters and returns matching contact IDs.
    """
    definition = segment.definition
    filter_rules = definition.get("rules", [])
    filter_logic = definition.get("logic", "and")

    query = select(Contact.id).where(Contact.workspace_id == segment.workspace_id)

    # Apply the segment's filter rules
    if filter_rules:
        query = apply_contact_filters(
            query,
            segment.workspace_id,
            filter_rules=filter_rules,
            filter_logic=filter_logic,
        )

    query = query.order_by(Contact.created_at.desc(), Contact.id.desc())

    result = await db.execute(query)
    ids = [row[0] for row in result.all()]

    return ids, len(ids)
