"""Landing a brand-new account in the workspace that invited it.

Registration used to call :func:`ensure_personal_workspace` unconditionally, so
an invited teammate who created their account got a *personal* workspace of
their own: the email said "join Acme", the invitee signed up, and landed in an
empty "Bob's Workspace" with none of the team's data. The pending invitation sat
unclaimed, and because the personal membership was flagged ``is_default``,
``/auth/me`` kept resolving to it even after the invitation was later accepted.

:func:`onboard_user_workspace` is the single entry point for "which workspace
does this user land in": a workspace that invited them if one exists, otherwise a
personal one. It only ever acts on a user with **no** memberships, so it never
silently adds an established user to a workspace, and never fights the
``uq_workspace_membership_default_per_user`` partial unique index.

Flushes but does not commit — the caller owns the transaction.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invitation import WorkspaceInvitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership

from .provisioning import ensure_personal_workspace, resolve_existing_workspace

logger = structlog.get_logger()


async def claim_pending_invitations(db: AsyncSession, user: User) -> Workspace | None:
    """Turn every valid pending invitation for ``user``'s email into a membership.

    Returns the workspace the user should land in (the earliest invitation
    claimed), or ``None`` when there was nothing to claim.

    ``workspace_invitations.email`` is a plain column while ``users.email`` is
    encrypted with a random IV, so the match is done in Python-normalized form
    against ``lower(email)`` — historical rows were stored with whatever casing
    the inviting admin typed.

    The caller must only invoke this for a user with no memberships; the first
    claimed workspace is flagged ``is_default`` unconditionally.
    """
    email = (user.email or "").strip().lower()
    if not email:
        return None

    now = datetime.now(UTC)
    invitations = (
        (
            await db.execute(
                select(WorkspaceInvitation)
                .where(
                    func.lower(WorkspaceInvitation.email) == email,
                    WorkspaceInvitation.status == "pending",
                    WorkspaceInvitation.expires_at > now,
                )
                .order_by(WorkspaceInvitation.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    if not invitations:
        return None

    landing_workspace_id: uuid.UUID | None = None
    claimed_workspace_ids: set[uuid.UUID] = set()

    for invitation in invitations:
        if invitation.workspace_id not in claimed_workspace_ids:
            db.add(
                WorkspaceMembership(
                    user_id=user.id,
                    workspace_id=invitation.workspace_id,
                    role=invitation.role,
                    # The first claim becomes the default so the very first login
                    # opens the inviting workspace instead of a personal one.
                    is_default=landing_workspace_id is None,
                )
            )
            claimed_workspace_ids.add(invitation.workspace_id)

        invitation.status = "accepted"
        invitation.accepted_at = now
        if landing_workspace_id is None:
            landing_workspace_id = invitation.workspace_id

    await db.flush()

    logger.info(
        "pending_invitations_claimed",
        user_id=user.id,
        invitations=len(invitations),
        workspace_ids=[str(ws_id) for ws_id in claimed_workspace_ids],
    )

    return await db.get(Workspace, landing_workspace_id)


async def onboard_user_workspace(db: AsyncSession, user: User) -> Workspace:
    """Return the workspace ``user`` belongs in, provisioning one if needed.

    Resolution order, for a user with no memberships:

    1. a workspace that invited them (invitation is claimed and marked accepted),
    2. otherwise a freshly provisioned personal workspace.

    Idempotent: a user who already has any membership gets their existing default
    (or earliest) workspace back untouched.
    """
    existing = await resolve_existing_workspace(db, user)
    if existing is not None:
        return existing

    invited = await claim_pending_invitations(db, user)
    if invited is not None:
        return invited

    return await ensure_personal_workspace(db, user)
