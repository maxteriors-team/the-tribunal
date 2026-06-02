"""Tag service - business logic orchestration layer."""

import uuid
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tag import ContactTag, Tag
from app.schemas.tag import TagResponse
from app.services.tags.tag_repository import (
    bulk_add_tags,
    bulk_remove_tags,
    create_tag,
    delete_tag,
    get_tag_by_id,
    list_tags,
    update_tag,
)

logger = structlog.get_logger()


class TagService:
    """High-level tag service for orchestrating business logic."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.log = logger.bind(service="tag")

    async def get_or_create_tag(
        self,
        workspace_id: uuid.UUID,
        name: str,
        color: str = "#6366f1",
    ) -> Tag:
        """Return the workspace tag named ``name``, creating it when missing."""
        tag_name = name.strip()
        if not tag_name:
            raise ValueError("Tag name cannot be blank")

        stmt = (
            pg_insert(Tag)
            .values(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                name=tag_name,
                color=color,
            )
            .on_conflict_do_nothing(constraint="uq_tags_workspace_name")
        )
        await self.db.execute(stmt)

        result = await self.db.execute(
            select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == tag_name)
        )
        return result.scalar_one()

    async def add_tag_to_contact(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
        name: str,
        color: str = "#6366f1",
    ) -> Tag:
        """Idempotently apply the named workspace tag to one contact."""
        tag = await self.get_or_create_tag(workspace_id=workspace_id, name=name, color=color)
        stmt = (
            pg_insert(ContactTag)
            .values(id=uuid.uuid4(), contact_id=contact_id, tag_id=tag.id)
            .on_conflict_do_nothing(constraint="uq_contact_tags_contact_tag")
        )
        await self.db.execute(stmt)
        return tag

    async def add_tags_to_contact(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
        names: list[str] | None,
        color: str = "#6366f1",
    ) -> list[Tag]:
        """Idempotently apply multiple named tags to one contact."""
        tags: list[Tag] = []
        for name in self._normalize_names(names):
            tags.append(
                await self.add_tag_to_contact(
                    workspace_id=workspace_id,
                    contact_id=contact_id,
                    name=name,
                    color=color,
                )
            )
        return tags

    async def replace_contact_tags_by_name(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
        names: list[str] | None,
        color: str = "#6366f1",
    ) -> list[Tag]:
        """Replace one contact's normalized tags with exactly the provided names."""
        normalized_names = self._normalize_names(names)
        if normalized_names:
            tags = [
                await self.get_or_create_tag(workspace_id=workspace_id, name=name, color=color)
                for name in normalized_names
            ]
            tag_ids = [tag.id for tag in tags]
            await self.db.execute(
                delete(ContactTag).where(
                    ContactTag.contact_id == contact_id,
                    ContactTag.tag_id.not_in(tag_ids),
                )
            )
            for tag_id in tag_ids:
                await self.db.execute(
                    pg_insert(ContactTag)
                    .values(id=uuid.uuid4(), contact_id=contact_id, tag_id=tag_id)
                    .on_conflict_do_nothing(constraint="uq_contact_tags_contact_tag")
                )
            return tags

        await self.db.execute(delete(ContactTag).where(ContactTag.contact_id == contact_id))
        return []

    @staticmethod
    def _normalize_names(names: list[str] | None) -> list[str]:
        """Return trimmed, deduplicated tag names preserving first-seen order."""
        if not names:
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_name in names:
            name = raw_name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(name)
        return normalized

    async def contact_has_tag(
        self,
        *,
        workspace_id: uuid.UUID,
        contact_id: int,
        name: str,
    ) -> bool:
        """Return whether a contact has a named workspace tag."""
        tag_name = name.strip()
        if not tag_name:
            return False
        result = await self.db.execute(
            select(ContactTag.id)
            .join(Tag, Tag.id == ContactTag.tag_id)
            .where(
                ContactTag.contact_id == contact_id,
                Tag.workspace_id == workspace_id,
                Tag.name == tag_name,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def list_tag_names_for_contact(
        self,
        *,
        contact_id: int,
    ) -> list[str]:
        """Return normalized tag names for a contact in stable order."""
        result = await self.db.execute(
            select(Tag.name)
            .join(ContactTag, ContactTag.tag_id == Tag.id)
            .where(ContactTag.contact_id == contact_id)
            .order_by(func.lower(Tag.name), Tag.name)
        )
        return list(result.scalars().all())

    async def list_tags(
        self,
        workspace_id: uuid.UUID,
    ) -> dict[str, Any]:
        """List all tags for a workspace with contact counts."""
        rows = await list_tags(workspace_id, self.db)

        items = []
        for tag, contact_count in rows:
            tag_response = TagResponse.model_validate(tag)
            tag_response.contact_count = contact_count
            items.append(tag_response)

        return {
            "items": items,
            "total": len(items),
        }

    async def get_tag(
        self,
        tag_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> TagResponse:
        """Get a specific tag."""
        tag = await get_tag_by_id(tag_id, workspace_id, self.db)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        return TagResponse.model_validate(tag)

    async def create_tag(
        self,
        workspace_id: uuid.UUID,
        name: str,
        color: str = "#6366f1",
    ) -> TagResponse:
        """Create a new tag."""
        tag = await create_tag(
            workspace_id=workspace_id,
            name=name,
            color=color,
            db=self.db,
        )
        return TagResponse.model_validate(tag)

    async def update_tag(
        self,
        tag_id: uuid.UUID,
        workspace_id: uuid.UUID,
        update_data: dict[str, str],
    ) -> TagResponse:
        """Update a tag."""
        tag = await get_tag_by_id(tag_id, workspace_id, self.db)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        updated = await update_tag(tag, self.db, update_data)
        return TagResponse.model_validate(updated)

    async def delete_tag(
        self,
        tag_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        """Delete a tag."""
        tag = await get_tag_by_id(tag_id, workspace_id, self.db)
        if tag is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tag not found",
            )
        await delete_tag(tag, self.db)

    async def bulk_tag_contacts(
        self,
        workspace_id: uuid.UUID,
        contact_ids: list[int],
        add_tag_ids: list[uuid.UUID] | None = None,
        remove_tag_ids: list[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """Bulk add/remove tags on contacts."""
        updated = 0
        errors: list[str] = []

        if add_tag_ids:
            try:
                added = await bulk_add_tags(
                    contact_ids=contact_ids,
                    tag_ids=add_tag_ids,
                    workspace_id=workspace_id,
                    db=self.db,
                )
                updated += added
            except Exception as e:
                errors.append(f"Failed to add tags: {e!s}")

        if remove_tag_ids:
            try:
                removed = await bulk_remove_tags(
                    contact_ids=contact_ids,
                    tag_ids=remove_tag_ids,
                    workspace_id=workspace_id,
                    db=self.db,
                )
                updated += removed
            except Exception as e:
                errors.append(f"Failed to remove tags: {e!s}")

        return {
            "updated": updated,
            "errors": errors,
        }
