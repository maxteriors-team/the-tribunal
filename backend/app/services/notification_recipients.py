"""Authorize recipients for internal workspace notification emails."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.notification_policy import roles_for


async def workspace_notification_email_users(
    db: AsyncSession,
    workspace_id: uuid.UUID | str,
    *,
    notification_type: str | None = None,
    recipient_user_ids: Sequence[int] | None = None,
) -> list[User]:
    """Return the active members this event is for, or explicitly targeted ones.

    ``notification_type`` selects the audience via
    :mod:`app.services.notification_policy` — a deposit reaches sales, a failed
    automation does not. Omitting it stays admin-only, so a caller that has not
    declared what it is sending cannot widen its own blast radius.
    """
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
        query = query.where(WorkspaceMembership.role.in_(roles_for(notification_type)))
    else:
        query = query.where(User.id.in_(recipient_user_ids))

    result = await db.execute(query)
    return list(result.scalars().all())
