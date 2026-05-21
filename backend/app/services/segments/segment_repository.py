"""Segment repository - data access layer for segment operations."""

import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
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


def build_segment_contacts_query(
    workspace_id: uuid.UUID,
    definition: dict[str, Any],
) -> Any:
    """Build a contact query for a segment definition."""
    filter_rules = definition.get("rules", [])
    filter_logic = definition.get("logic", "and")

    query = select(Contact).where(Contact.workspace_id == workspace_id)
    if filter_rules:
        query = apply_contact_filters(
            query,
            workspace_id,
            filter_rules=filter_rules,
            filter_logic=filter_logic,
        )

    return query


async def preview_segment_contacts(
    workspace_id: uuid.UUID,
    definition: dict[str, Any],
    db: AsyncSession,
    *,
    limit: int = 10,
) -> tuple[list[Contact], int]:
    """Preview contacts that match a segment definition with total count."""
    base_query = build_segment_contacts_query(workspace_id, definition)
    count_query = select(func.count()).select_from(base_query.order_by(None).subquery())
    total = await db.scalar(count_query)

    result = await db.execute(
        base_query.order_by(Contact.created_at.desc(), Contact.id.desc()).limit(limit)
    )
    return list(result.scalars().all()), total or 0


async def resolve_segment_contacts(
    segment: Segment,
    db: AsyncSession,
) -> tuple[list[int], int]:
    """Resolve a segment's filter definition to contact IDs.

    Builds a query using apply_contact_filters and returns matching contact IDs.
    """
    query = build_segment_contacts_query(
        segment.workspace_id,
        segment.definition,
    ).with_only_columns(Contact.id)
    query = query.order_by(Contact.created_at.desc(), Contact.id.desc())

    result = await db.execute(query)
    ids = [row[0] for row in result.all()]

    return ids, len(ids)
