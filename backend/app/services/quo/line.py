"""Workspace-owned active Quo line resolution."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.encryption import hash_phone
from app.models.conversation import Conversation
from app.models.workspace import WorkspaceIntegration
from app.utils.phone import normalize_phone_safe


@dataclass(frozen=True, slots=True)
class ActiveQuoLine:
    phone_number_id: str
    phone_number: str


async def get_active_quo_line(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> ActiveQuoLine | None:
    """Return the validated non-secret selected line for one workspace."""
    result = await db.execute(
        select(WorkspaceIntegration).where(
            WorkspaceIntegration.workspace_id == workspace_id,
            WorkspaceIntegration.integration_type == "quo",
            WorkspaceIntegration.is_active.is_(True),
        )
    )
    integration = result.scalar_one_or_none()
    credentials = integration.safe_credentials() if integration is not None else None
    if credentials is None:
        return None
    phone_number_id = credentials.get("phone_number_id")
    raw_phone_number = credentials.get("phone_number")
    normalized_phone = (
        normalize_phone_safe(raw_phone_number) if isinstance(raw_phone_number, str) else None
    )
    if (
        not isinstance(phone_number_id, str)
        or not phone_number_id.strip()
        or len(phone_number_id) > 255
        or normalized_phone is None
        or normalized_phone != raw_phone_number
    ):
        return None
    return ActiveQuoLine(
        phone_number_id=phone_number_id.strip(),
        phone_number=normalized_phone,
    )


async def visible_conversation_provider_clause(
    db: AsyncSession,
    workspace_id: uuid.UUID,
) -> ColumnElement[bool]:
    """Hide Quo conversations outside the workspace's selected line."""
    visible_provider = or_(
        Conversation.source_provider.is_(None),
        Conversation.source_provider != "quo",
    )
    active_line = await get_active_quo_line(db, workspace_id)
    if active_line is None:
        return visible_provider
    return or_(
        visible_provider,
        Conversation.workspace_phone_hash == hash_phone(active_line.phone_number),
    )
