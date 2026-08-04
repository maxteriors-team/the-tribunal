"""An invited teammate must land in the workspace that invited them.

Registration called ``ensure_personal_workspace`` unconditionally, so signing up
from an invitation email created a personal workspace ("Bob's Workspace") and
flagged it default. The invitation stayed pending, ``/auth/me`` kept resolving to
the personal workspace, and the operator's report was simply: "inviting a team
member creates their own workspace instead of adding them to ours."

These tests pin the fix at the seam that produced the bug —
:func:`onboard_user_workspace` — plus the guarantee that it never touches a user
who already belongs somewhere.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.encryption import hash_value
from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal, engine
from app.models.invitation import WorkspaceInvitation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership
from app.services.workspaces import onboard_user_workspace

# Hits the real database, so it is an integration test (deselected by default;
# run with `-m integration`).
pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(autouse=True)
async def _fresh_engine_pool():
    """Dispose the shared engine pool around each test (loop-affinity safety)."""
    await engine.dispose()
    yield
    await engine.dispose()


async def _make_user(db, email: str) -> User:
    user = User(
        email=email,
        email_hash=hash_value(email),
        hashed_password=get_password_hash("password123"),
        full_name="Invited Teammate",
    )
    db.add(user)
    await db.flush()
    return user


async def _make_workspace(db) -> Workspace:
    workspace = Workspace(
        id=uuid.uuid4(),
        name="Acme Home Services",
        slug=f"acme-{uuid.uuid4().hex[:8]}",
    )
    db.add(workspace)
    await db.flush()
    return workspace


async def _invite(
    db,
    workspace: Workspace,
    email: str,
    *,
    role: str = "member",
    status: str = "pending",
    expires_in: timedelta = timedelta(days=7),
) -> WorkspaceInvitation:
    invitation = WorkspaceInvitation(
        workspace_id=workspace.id,
        email=email,
        role=role,
        status=status,
        expires_at=datetime.now(UTC) + expires_in,
    )
    db.add(invitation)
    await db.flush()
    return invitation


async def _memberships(db, user_id: int) -> list[WorkspaceMembership]:
    rows = await db.execute(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
    )
    return list(rows.scalars().all())


async def test_invited_signup_joins_the_inviting_workspace_not_a_personal_one() -> None:
    """The reported bug: the invitee must not get a workspace of their own."""
    async with AsyncSessionLocal() as db:
        email = f"invitee-{uuid.uuid4().hex[:8]}@example.com"
        workspace = await _make_workspace(db)
        invitation = await _invite(db, workspace, email, role="admin")
        user = await _make_user(db, email)

        landed = await onboard_user_workspace(db, user)

        assert landed.id == workspace.id

        memberships = await _memberships(db, user.id)
        assert len(memberships) == 1
        assert memberships[0].workspace_id == workspace.id
        # The invited role is honoured, and this becomes their default so
        # /auth/me and the dashboard open the team's workspace.
        assert memberships[0].role == "admin"
        assert memberships[0].is_default is True

        await db.refresh(invitation)
        assert invitation.status == "accepted"
        assert invitation.accepted_at is not None

        await db.rollback()


async def test_invitation_email_casing_does_not_strand_the_invitee() -> None:
    """Invitations stored with the casing an admin typed must still match."""
    async with AsyncSessionLocal() as db:
        email = f"mixed-{uuid.uuid4().hex[:8]}@example.com"
        workspace = await _make_workspace(db)
        await _invite(db, workspace, email.upper())
        user = await _make_user(db, email)

        landed = await onboard_user_workspace(db, user)

        assert landed.id == workspace.id
        await db.rollback()


async def test_expired_or_cancelled_invitations_fall_back_to_a_personal_workspace() -> None:
    """A dead invitation must not be claimed, and must not leave the user stranded."""
    async with AsyncSessionLocal() as db:
        email = f"stale-{uuid.uuid4().hex[:8]}@example.com"
        workspace = await _make_workspace(db)
        await _invite(db, workspace, email, expires_in=timedelta(days=-1))
        await _invite(db, workspace, email, status="cancelled")
        user = await _make_user(db, email)

        landed = await onboard_user_workspace(db, user)

        assert landed.id != workspace.id
        memberships = await _memberships(db, user.id)
        assert len(memberships) == 1
        assert memberships[0].workspace_id == landed.id
        assert memberships[0].role == "owner"
        assert memberships[0].is_default is True

        await db.rollback()


async def test_uninvited_signup_still_gets_a_personal_workspace() -> None:
    """RF-001 must not regress: no invitation still means a usable workspace."""
    async with AsyncSessionLocal() as db:
        user = await _make_user(db, f"solo-{uuid.uuid4().hex[:8]}@example.com")

        landed = await onboard_user_workspace(db, user)

        memberships = await _memberships(db, user.id)
        assert len(memberships) == 1
        assert memberships[0].workspace_id == landed.id
        assert memberships[0].role == "owner"
        assert memberships[0].is_default is True

        await db.rollback()


async def test_existing_member_is_never_silently_added_to_a_new_workspace() -> None:
    """Login calls this on every request; a pending invite still needs an accept."""
    async with AsyncSessionLocal() as db:
        email = f"established-{uuid.uuid4().hex[:8]}@example.com"
        user = await _make_user(db, email)
        own = await _make_workspace(db)
        db.add(
            WorkspaceMembership(
                user_id=user.id, workspace_id=own.id, role="owner", is_default=True
            )
        )
        await db.flush()

        other = await _make_workspace(db)
        invitation = await _invite(db, other, email)

        landed = await onboard_user_workspace(db, user)

        assert landed.id == own.id
        memberships = await _memberships(db, user.id)
        assert len(memberships) == 1
        assert memberships[0].workspace_id == own.id

        await db.refresh(invitation)
        assert invitation.status == "pending"

        await db.rollback()
