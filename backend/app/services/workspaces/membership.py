"""Resolution of the workspace a caller is implicitly acting in.

A few self-serve surfaces (the onboarding wizard, billing) act on "the
workspace I am currently in" rather than taking a ``workspace_id`` path
parameter. They resolve that workspace from the caller's **default** membership,
falling back to their earliest membership.

``is_default`` is a *selection* signal, never an authorization signal: every
member of a workspace may flip their own default via
``POST /api/v1/workspaces/{workspace_id}/set-default``. Any caller that reads
privileged state or mutates the resolved workspace must therefore additionally
check the role it holds **in that workspace** (see
:mod:`app.core.permissions`).

This module is the single resolution point so the membership an API dependency
authorizes is provably the same membership the service layer then acts on.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import WorkspaceMembership


async def resolve_active_membership(
    user_id: int,
    db: AsyncSession,
) -> WorkspaceMembership | None:
    """Return the caller's membership in their active workspace, or ``None``.

    The active workspace is the caller's default membership; when no default is
    flagged, their earliest membership is used. ``None`` means the user belongs
    to no workspace at all.
    """
    result = await db.execute(
        select(WorkspaceMembership).where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.is_default.is_(True),
        )
    )
    membership: WorkspaceMembership | None = result.scalar_one_or_none()
    if membership is not None:
        return membership

    fallback = await db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(WorkspaceMembership.created_at.asc())
        .limit(1)
    )
    return fallback.scalar_one_or_none()
