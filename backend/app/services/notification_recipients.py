"""Role-scoped recipients for operator notification emails."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import WorkspaceRole
from app.models.user import User
from app.models.workspace import WorkspaceMembership

_WORKSPACE_WIDE_EMAIL_ROLES = (
    WorkspaceRole.OWNER.value,
    WorkspaceRole.ADMIN.value,
    WorkspaceRole.MANAGER.value,
    WorkspaceRole.DISPATCHER.value,
)


async def workspace_notification_email_users(
    db: AsyncSession,
    workspace_id: uuid.UUID | str,
    *,
    recipient_user_ids: Sequence[int] | None = None,
) -> list[User]:
    """Return global operators, or any explicitly targeted workspace members."""
    workspace_uuid = uuid.UUID(str(workspace_id))
    query = (
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(WorkspaceMembership.workspace_id == workspace_uuid)
    )
    if recipient_user_ids is None:
        query = query.where(WorkspaceMembership.role.in_(_WORKSPACE_WIDE_EMAIL_ROLES))
    else:
        query = query.where(User.id.in_(recipient_user_ids))

    result = await db.execute(query)
    return list(result.scalars().all())
