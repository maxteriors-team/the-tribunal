"""Contact timeline service."""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.contacts.contact_repository import get_contact_by_id
from app.services.contacts.contact_repository import (
    get_contact_timeline as repo_get_contact_timeline,
)
from app.services.contacts.exceptions import ContactNotFoundError

logger = structlog.get_logger()


class ContactTimelineService:
    """Unified timeline operations for a contact."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.log = logger.bind(service="contact_timeline")

    async def get_contact_timeline(
        self,
        *,
        contact_id: int,
        workspace_id: uuid.UUID,
        limit: int = 100,
        conversation_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent timeline items for a contact."""
        contact = await get_contact_by_id(contact_id, workspace_id, self.db)
        if contact is None:
            raise ContactNotFoundError()

        return await repo_get_contact_timeline(
            contact_id=contact_id,
            workspace_id=workspace_id,
            db=self.db,
            limit=limit,
            conversation_id=conversation_id,
        )
