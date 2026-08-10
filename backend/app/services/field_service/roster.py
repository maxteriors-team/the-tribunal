"""Keep the dispatch roster in step with workspace membership.

Dispatch tags a :class:`~app.models.field_service.Technician` onto a job — not a
:class:`~app.models.workspace.WorkspaceMembership`. The two tables are separate
on purpose: a roster entry may exist without a login (a subcontractor, or a crew
imported from Jobber), and a login may exist without ever touching a job. But
nothing bridged them, so hiring a field worker the only ways the product offers
— invite them, or provision them in bulk, with the ``technician`` role — left
the dispatch board empty. Every job dialog reported "No technicians in this
workspace yet" and the new hire could not be tagged to any work.

Provisioning is deliberately one-way:

- A member holding a **field role** (``technician`` / ``lead_technician``) gets
  an active roster row — created when missing, reactivated when it was retired.
- Moving a member *off* a field role never removes their roster row. Field work
  and CRM permissions are different axes (an owner or manager who runs jobs
  belongs on the board), so taking someone off the roster stays a deliberate
  act, never a side effect of a role change.
- Removing the member from the workspace *does* retire the row: it drops the
  login link and deactivates. Historical job assignments survive, while the
  person disappears from the assignable list — and the row stays editable,
  because a roster row still pointing at a non-member is rejected by
  :func:`app.services.field_service._refs.assert_user_is_member` on every later
  update.

Callers own the transaction: every function here flushes and never commits.
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.roles import WorkspaceRole
from app.models.field_service import Technician
from app.models.user import User

logger = structlog.get_logger()

# Roles that put a member on the dispatch board. Kept as a frozenset (not a
# rank threshold) because roster membership is not a privilege ladder: a
# dispatcher outranks a technician but does not swing a pressure washer.
FIELD_ROLES: frozenset[str] = frozenset(
    {
        WorkspaceRole.TECHNICIAN.value,
        WorkspaceRole.LEAD_TECHNICIAN.value,
    }
)

# Mirrors the ``technicians`` column widths so a long profile value can never
# fail the insert with a DataError.
_NAME_MAX = 200
_EMAIL_MAX = 255
_PHONE_MAX = 50


def is_field_role(role: str | None) -> bool:
    """Return True when ``role`` is a field role that belongs on the roster."""
    return role in FIELD_ROLES


def _display_name(user: User) -> str:
    """Best available human label for a roster row.

    Falls back to the email local-part because ``full_name`` is optional on an
    invited account, and ``technicians.name`` is NOT NULL and is the only thing
    a dispatcher sees in the "tag workers" list. The last resort is numbered so
    two unnamed hires never collapse into one indistinguishable entry.
    """
    name = (user.full_name or "").strip()
    if not name:
        name = (user.email or "").strip().split("@", 1)[0]
    return (name or f"Technician #{user.id}")[:_NAME_MAX]


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:limit] or None


async def _find_roster_entry(
    db: AsyncSession, workspace_id: uuid.UUID, user: User
) -> Technician | None:
    """Find this person's existing roster row, linked by login or by email."""
    linked = (
        await db.execute(
            select(Technician)
            .where(
                Technician.workspace_id == workspace_id,
                Technician.user_id == user.id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if linked is not None:
        return linked

    email = (user.email or "").strip().lower()
    if not email:
        return None
    # Claim a row that was imported or typed without a login (Jobber sync, or a
    # dispatcher who added the crew by hand before the hire got an account)
    # instead of listing the same person on the board twice.
    return (
        (
            await db.execute(
                select(Technician)
                .where(
                    Technician.workspace_id == workspace_id,
                    Technician.user_id.is_(None),
                    func.lower(Technician.email) == email,
                )
                .order_by(Technician.created_at)
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def ensure_member_on_roster(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user: User,
    role: str,
) -> Technician | None:
    """Make a field-role member taggable to jobs. Flushes; does not commit.

    Returns the roster row, or ``None`` when ``role`` is not a field role (the
    caller's membership write stands either way).
    """
    if not is_field_role(role):
        return None

    entry = await _find_roster_entry(db, workspace_id, user)
    if entry is None:
        entry = Technician(
            workspace_id=workspace_id,
            user_id=user.id,
            name=_display_name(user),
            email=_truncate(user.email, _EMAIL_MAX),
            phone=_truncate(user.phone_number, _PHONE_MAX),
            is_active=True,
        )
        db.add(entry)
        await db.flush()
        logger.info(
            "technician_roster_created",
            workspace_id=str(workspace_id),
            user_id=user.id,
            technician_id=str(entry.id),
            role=role,
        )
        return entry

    changed = False
    if entry.user_id is None:
        entry.user_id = user.id
        changed = True
    if not entry.is_active:
        entry.is_active = True
        changed = True
    if changed:
        await db.flush()
        logger.info(
            "technician_roster_restored",
            workspace_id=str(workspace_id),
            user_id=user.id,
            technician_id=str(entry.id),
            role=role,
        )
    return entry


async def retire_member_from_roster(
    db: AsyncSession, *, workspace_id: uuid.UUID, user_id: int
) -> int:
    """Take a departing member off the assignable roster.

    Unlinks the login and deactivates the row rather than deleting it, so the
    jobs they already worked keep their assignment history. Returns the number
    of rows retired. Flushes; does not commit.
    """
    entries = (
        (
            await db.execute(
                select(Technician).where(
                    Technician.workspace_id == workspace_id,
                    Technician.user_id == user_id,
                )
            )
        )
        .scalars()
        .all()
    )
    if not entries:
        return 0

    for entry in entries:
        entry.user_id = None
        entry.is_active = False
    await db.flush()
    logger.info(
        "technician_roster_retired",
        workspace_id=str(workspace_id),
        user_id=user_id,
        technicians=len(entries),
    )
    return len(entries)
