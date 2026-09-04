"""Authorize recipients for internal workspace notification emails."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import WorkspaceRole
from app.models.user import User
from app.models.workspace import WorkspaceMembership

_ADMIN_EMAIL_ROLES = (
    WorkspaceRole.OWNER.value,
    WorkspaceRole.ADMIN.value,
)


async def workspace_notification_email_users(
    db: AsyncSession,
    workspace_id: uuid.UUID | str,
    *,
    recipient_user_ids: Sequence[int] | None = None,
) -> list[User]:
    """Return active admins, or active members explicitly targeted for operational work."""
    workspace_uuid = uuid.UUID(str(workspace_id))
    query = (
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_uuid,
            User.is_active.is_(True),
        )
    )
    if recipient_user_ids is None:
        query = query.where(WorkspaceMembership.role.in_(_ADMIN_EMAIL_ROLES))
    else:
        query = query.where(User.id.in_(recipient_user_ids))

    result = await db.execute(query)
    return list(result.scalars().all())
