"""Tag repository - data access layer for tag operations."""

import uuid

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.tag import ContactTag, Tag

logger = structlog.get_logger()


async def list_tags(
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> list[tuple[Tag, int]]:
    """List all tags for a workspace with contact counts.

    Returns:
        List of (Tag, contact_count) tuples
    """
    count_subquery = (
        select(
            ContactTag.tag_id,
            func.count(ContactTag.contact_id).label("contact_count"),
        )
        .group_by(ContactTag.tag_id)
        .subquery()
    )

    query = (
        select(
            Tag,
            func.coalesce(count_subquery.c.contact_count, 0).label("contact_count"),
        )
        .outerjoin(count_subquery, Tag.id == count_subquery.c.tag_id)
        .where(Tag.workspace_id == workspace_id)
        .order_by(Tag.name)
    )

    result = await db.execute(query)
    return [(row[0], row[1]) for row in result.all()]


async def get_tag_by_id(
    tag_id: uuid.UUID,
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> Tag | None:
    """Get a specific tag by ID."""
    result = await db.execute(select(Tag).where(Tag.id == tag_id, Tag.workspace_id == workspace_id))
    return result.scalar_one_or_none()


async def create_tag(
    workspace_id: uuid.UUID,
    name: str,
    color: str,
    db: AsyncSession,
) -> Tag:
    """Create a new tag."""
    tag = Tag(
        workspace_id=workspace_id,
        name=name,
        color=color,
    )
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return tag


async def update_tag(
    tag: Tag,
    db: AsyncSession,
    update_data: dict[str, str],
) -> Tag:
    """Update a tag."""
    for field, value in update_data.items():
        setattr(tag, field, value)
    await db.commit()
    await db.refresh(tag)
    return tag


async def delete_tag(
    tag: Tag,
    db: AsyncSession,
) -> None:
    """Delete a tag (cascades to contact_tags)."""
    await db.delete(tag)
    await db.commit()


async def bulk_add_tags(
    contact_ids: list[int],
    tag_ids: list[uuid.UUID],
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """Add tags to multiple contacts. Skips duplicates.

    Returns:
        Number of new contact_tag entries created
    """
    # Verify contacts belong to workspace
    contact_result = await db.execute(
        select(Contact.id).where(
            Contact.id.in_(contact_ids),
            Contact.workspace_id == workspace_id,
        )
    )
    valid_contact_ids = {row[0] for row in contact_result.all()}

    # Verify tags belong to workspace
    tag_result = await db.execute(
        select(Tag.id).where(
            Tag.id.in_(tag_ids),
            Tag.workspace_id == workspace_id,
        )
    )
    valid_tag_ids = {row[0] for row in tag_result.all()}

    # Get existing contact_tag pairs to avoid duplicates
    existing = await db.execute(
        select(ContactTag.contact_id, ContactTag.tag_id).where(
            ContactTag.contact_id.in_(valid_contact_ids),
            ContactTag.tag_id.in_(valid_tag_ids),
        )
    )
    existing_pairs = {(row[0], row[1]) for row in existing.all()}

    created = 0
    for contact_id in valid_contact_ids:
        for tag_id in valid_tag_ids:
            if (contact_id, tag_id) not in existing_pairs:
                db.add(ContactTag(contact_id=contact_id, tag_id=tag_id))
                created += 1

    if created > 0:
        await db.commit()

    return created


async def bulk_remove_tags(
    contact_ids: list[int],
    tag_ids: list[uuid.UUID],
    workspace_id: uuid.UUID,
    db: AsyncSession,
) -> int:
    """Remove tags from multiple contacts.

    Returns:
        Number of contact_tag entries removed
    """
    # Verify contacts belong to workspace
    contact_result = await db.execute(
        select(Contact.id).where(
            Contact.id.in_(contact_ids),
            Contact.workspace_id == workspace_id,
        )
    )
    valid_contact_ids = {row[0] for row in contact_result.all()}

    if not valid_contact_ids:
        return 0

    # Count existing entries first
    count_result = await db.execute(
        select(func.count()).select_from(
            select(ContactTag.id)
            .where(
                ContactTag.contact_id.in_(valid_contact_ids),
                ContactTag.tag_id.in_(tag_ids),
            )
            .subquery()
        )
    )
    count = count_result.scalar() or 0

    await db.execute(
        delete(ContactTag).where(
            ContactTag.contact_id.in_(valid_contact_ids),
            ContactTag.tag_id.in_(tag_ids),
        )
    )
    await db.commit()

    return count


async def get_tags_for_contact(
    contact_id: int,
    db: AsyncSession,
) -> list[Tag]:
    """Get all tags for a contact."""
    result = await db.execute(
        select(Tag)
        .join(ContactTag, ContactTag.tag_id == Tag.id)
        .where(ContactTag.contact_id == contact_id)
        .order_by(Tag.name)
    )
    return list(result.scalars().all())
