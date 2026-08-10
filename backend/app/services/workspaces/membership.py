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
authorizes is provably the same membership the service layer then acts on, and
the single *write* point (:func:`set_default_membership`) for moving a user's
default — "at most one default per user" is an invariant the whole codebase reads
but nothing used to enforce.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.services.exceptions import NotFoundError


async def resolve_active_membership(
    user_id: int,
    db: AsyncSession,
) -> WorkspaceMembership | None:
    """Return the caller's membership in their active workspace, or ``None``.

    The active workspace is the caller's default membership; when no default is
    flagged, their earliest membership is used. ``None`` means the user belongs
    to no workspace at all.

    Deliberately tolerant of more than one default row. ``POST /workspaces``
    used to flag its new membership default without clearing the caller's
    existing one, so real rows carry duplicate defaults; an unbounded
    ``scalar_one_or_none()`` here raised ``MultipleResultsFound`` and turned
    every ``/onboarding/*`` call into a 500 for those users. The ordering is the
    same tie-break the repair migration uses (earliest membership wins), so
    resolution is identical before and after the data is cleaned up.
    """
    result = await db.execute(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.is_default.is_(True),
        )
        .order_by(
            WorkspaceMembership.created_at.asc(),
            WorkspaceMembership.id.asc(),
        )
        .limit(1)
    )
    membership: WorkspaceMembership | None = result.scalar_one_or_none()
    if membership is not None:
        return membership

    fallback = await db.execute(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .order_by(
            WorkspaceMembership.created_at.asc(),
            WorkspaceMembership.id.asc(),
        )
        .limit(1)
    )
    return fallback.scalar_one_or_none()


async def assert_active_workspace_member(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: int,
) -> User:
    """Return an active user who belongs to ``workspace_id`` or tenant-safe 404."""
    result = await db.execute(
        select(User)
        .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            User.id == user_id,
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise NotFoundError("Active workspace member not found")
    return user


async def set_default_membership(
    db: AsyncSession,
    user_id: int,
    workspace_id: uuid.UUID,
) -> None:
    """Make ``workspace_id`` the user's one and only default membership.

    Clears every other default **first**, then promotes the target, as two
    ordered statements. The order is load-bearing: the partial unique index
    ``uq_workspace_membership_default_per_user`` is not deferrable (Postgres
    cannot defer a *partial* unique index), so promoting before clearing — or
    letting the ORM flush a batch of ``is_default`` assignments in its own
    arbitrary order — would transiently hold two default rows and fail.

    The target membership must already be flushed; a pending, unflushed row is
    invisible to an UPDATE and would leave the user with no default at all.
    Flushes but does not commit — the caller owns the transaction.
    """
    await db.execute(
        update(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id != workspace_id,
            WorkspaceMembership.is_default.is_(True),
        )
        .values(is_default=False)
    )
    await db.execute(
        update(WorkspaceMembership)
        .where(
            WorkspaceMembership.user_id == user_id,
            WorkspaceMembership.workspace_id == workspace_id,
        )
        .values(is_default=True)
    )
    await db.flush()
