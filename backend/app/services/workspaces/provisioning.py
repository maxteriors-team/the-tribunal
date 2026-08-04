"""Personal workspace provisioning for new/first-login users.

A freshly-registered :class:`~app.models.user.User` with no
:class:`~app.models.workspace.WorkspaceMembership` leaves the frontend with
``default_workspace_id=null`` and ``currentWorkspace=null``, which freezes every
workspace-scoped page on its loading skeleton (finding RF-001). This module
guarantees every user lands in a usable default workspace that mirrors
:func:`app.api.v1.workspaces.create_workspace`: an owner membership plus a
default pipeline via :func:`ensure_default_pipeline`.

:func:`ensure_personal_workspace` is idempotent and flushes but does not commit
— the caller owns the transaction.
"""

from __future__ import annotations

import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.opportunities import ensure_default_pipeline

logger = structlog.get_logger()


def _slugify(value: str) -> str:
    """Reduce ``value`` to the workspace slug charset (``^[a-z0-9-]+$``)."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:80]


def _workspace_name(user: User) -> str:
    """Pick a friendly personal-workspace name from the user's identity."""
    if user.full_name and user.full_name.strip():
        first = user.full_name.strip().split()[0]
        return f"{first}'s Workspace"
    return "My Workspace"


async def _unique_slug(db: AsyncSession, base: str) -> str:
    """Return a globally-unique slug derived from ``base``.

    The ``workspaces.slug`` column is globally unique, so a personal workspace
    cannot reuse another tenant's slug. We try the base slug first, then append a
    short random suffix until free.
    """
    base = _slugify(base) or "workspace"
    slug = base
    while True:
        existing = await db.execute(select(Workspace.id).where(Workspace.slug == slug))
        if existing.scalar_one_or_none() is None:
            return slug
        slug = f"{base}-{uuid.uuid4().hex[:6]}"


async def resolve_existing_workspace(db: AsyncSession, user: User) -> Workspace | None:
    """Return the user's default (else earliest) workspace, or ``None``.

    ``None`` means the user belongs to no workspace at all and needs to be
    landed somewhere — see
    :func:`app.services.workspaces.invitations.onboard_user_workspace`.
    """
    existing = await db.execute(
        select(Workspace)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == user.id)
        .order_by(
            WorkspaceMembership.is_default.desc(),
            WorkspaceMembership.created_at.asc(),
        )
        .limit(1)
    )
    return existing.scalar_one_or_none()


async def ensure_personal_workspace(db: AsyncSession, user: User) -> Workspace:
    """Return the user's default workspace, creating a personal one if absent.

    Idempotent: if the user already has any membership, their default (or
    earliest) workspace is returned unchanged. Otherwise a personal workspace
    with an owner membership and a default pipeline is provisioned. Flushes but
    does not commit; the caller owns the transaction.

    Callers on the register/login path should prefer
    :func:`app.services.workspaces.invitations.onboard_user_workspace`, which
    honours a pending invitation before falling back to a personal workspace.
    """
    workspace = await resolve_existing_workspace(db, user)
    if workspace is not None:
        return workspace

    name = _workspace_name(user)
    slug = await _unique_slug(db, name)
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    await db.flush()

    db.add(
        WorkspaceMembership(
            user_id=user.id,
            workspace_id=workspace.id,
            role="owner",
            is_default=True,
        )
    )

    # Mirror create_workspace: provision a default pipeline so the opportunities
    # board renders and the promotion flow has a pipeline to open into.
    #
    # Deliberately no `ensure_default_agent` here, and deliberately no
    # `onboarding_completed_at`: a freshly provisioned personal workspace has
    # never been configured, so it must be offered onboarding. Seeding an agent
    # to "match" create_workspace would not make the two paths consistent in any
    # useful way — setup state is the explicit
    # :attr:`Workspace.onboarding_completed_at` stamp, written only when the
    # wizard completes.
    await ensure_default_pipeline(db, workspace.id)
    await db.flush()

    logger.info(
        "personal_workspace_provisioned",
        user_id=user.id,
        workspace_id=str(workspace.id),
        slug=slug,
    )
    return workspace
