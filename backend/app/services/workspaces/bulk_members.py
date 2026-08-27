"""Bulk creation of workspace members.

Provisions many team logins in a single request for a workspace. Each input row
resolves to exactly one outcome:

- ``created`` — a brand-new :class:`~app.models.user.User` plus a membership in
  the target workspace. New accounts are made *default* to this workspace so the
  member's first login lands here instead of triggering personal-workspace
  provisioning.
- ``added_existing`` — the email already had an account; it is attached to this
  workspace as a member with the requested role. Existing passwords are never
  changed and any supplied ``password`` is ignored.
- ``already_member`` — the account was already a member; nothing changes.
- ``skipped`` — the row was not applied: a duplicate email within the request, a
  permission guard (only the owner may mint admins), or a DB conflict.

Rows provisioned with a field role (``technician``/``lead_technician``) also get
a dispatch-roster entry via :mod:`app.services.field_service.roster`, so a crew
hired here can be tagged to jobs without a second manual step.

The whole batch runs inside the caller's transaction. Each row executes inside a
SAVEPOINT so a single conflicting row rolls back on its own without poisoning the
rest of the batch; the caller owns the final commit.
"""

from __future__ import annotations

import secrets
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import hash_value
from app.core.roles import can_assign_workspace_role
from app.core.security import get_password_hash
from app.models.user import User
from app.models.workspace import WorkspaceMembership
from app.schemas.bulk_members import (
    BulkMemberCreateResponse,
    BulkMemberItem,
    BulkMemberResultItem,
)
from app.services.field_service import ensure_member_on_roster

logger = structlog.get_logger()

# Entropy for generated temporary passwords. 12 bytes -> 16 url-safe chars,
# comfortably above the 8-char minimum enforced on caller-supplied passwords.
_TEMP_PASSWORD_BYTES = 12


def generate_temp_password() -> str:
    """Return a strong, URL-safe temporary password."""
    return secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)


async def _attach_existing_member(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user: User,
    role: str,
    email_norm: str,
) -> BulkMemberResultItem:
    """Attach an account that already exists to this workspace. Flushes.

    Runs inside the caller's per-row SAVEPOINT, so a conflict here rolls back
    this member only.
    """
    db.add(
        WorkspaceMembership(
            user_id=user.id,
            workspace_id=workspace_id,
            role=role,
            is_default=False,
        )
    )
    await db.flush()
    await ensure_member_on_roster(db, workspace_id=workspace_id, user=user, role=role)
    return BulkMemberResultItem(
        email=email_norm,
        status="added_existing",
        user_id=user.id,
        role=role,
    )


async def bulk_create_members(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    caller_role: str,
    items: list[BulkMemberItem],
) -> BulkMemberCreateResponse:
    """Create/attach many members in one batch. Flushes; does not commit."""
    results: list[BulkMemberResultItem] = []

    # Normalize emails and drop intra-request duplicates (first occurrence wins).
    deduped: list[tuple[BulkMemberItem, str, str]] = []
    seen: set[str] = set()
    for item in items:
        email_norm = item.email.strip().lower()
        if email_norm in seen:
            results.append(
                BulkMemberResultItem(
                    email=email_norm,
                    status="skipped",
                    error="Duplicate email in request",
                )
            )
            continue
        seen.add(email_norm)
        deduped.append((item, email_norm, hash_value(email_norm)))

    # Preload existing accounts and their memberships so the common path avoids
    # per-row lookups; SAVEPOINTs still guard against races on insert.
    email_hashes = [email_hash for (_, _, email_hash) in deduped]
    existing_users: dict[str, User] = {}
    if email_hashes:
        rows = (
            (await db.execute(select(User).where(User.email_hash.in_(email_hashes))))
            .scalars()
            .all()
        )
        existing_users = {user.email_hash: user for user in rows}

    member_user_ids: set[int] = set()
    existing_user_ids = [user.id for user in existing_users.values()]
    if existing_user_ids:
        member_rows = (
            (
                await db.execute(
                    select(WorkspaceMembership.user_id).where(
                        WorkspaceMembership.workspace_id == workspace_id,
                        WorkspaceMembership.user_id.in_(existing_user_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        member_user_ids = set(member_rows)

    for item, email_norm, email_hash in deduped:
        if not can_assign_workspace_role(caller_role, item.role):
            results.append(
                BulkMemberResultItem(
                    email=email_norm,
                    status="skipped",
                    error=(
                        "Only the workspace owner can grant the admin role"
                        if item.role == "admin"
                        else "Not authorized to assign workspace roles"
                    ),
                )
            )
            continue

        existing = existing_users.get(email_hash)
        try:
            async with db.begin_nested():
                if existing is not None:
                    if existing.id in member_user_ids:
                        results.append(
                            BulkMemberResultItem(
                                email=email_norm,
                                status="already_member",
                                user_id=existing.id,
                                role=None,
                            )
                        )
                        continue
                    results.append(
                        await _attach_existing_member(
                            db,
                            workspace_id=workspace_id,
                            user=existing,
                            role=item.role,
                            email_norm=email_norm,
                        )
                    )
                    member_user_ids.add(existing.id)
                    continue

                temp_password = item.password or generate_temp_password()
                # The account is created with a password the admin knows (either
                # generated here or supplied in the request), so require a reset
                # on first login in both cases.
                user = User(
                    email=email_norm,
                    email_hash=email_hash,
                    hashed_password=get_password_hash(temp_password),
                    full_name=item.full_name,
                    must_change_password=True,
                )
                db.add(user)
                await db.flush()
                # Default into THIS workspace so first login lands here rather
                # than auto-provisioning a personal workspace.
                db.add(
                    WorkspaceMembership(
                        user_id=user.id,
                        workspace_id=workspace_id,
                        role=item.role,
                        is_default=True,
                    )
                )
                await db.flush()
                # A crew provisioned in bulk is hired to work jobs, so a
                # field-role row lands on the dispatch board immediately —
                # inside this row's SAVEPOINT, so a conflict skips just this
                # member instead of poisoning the batch.
                await ensure_member_on_roster(
                    db,
                    workspace_id=workspace_id,
                    user=user,
                    role=item.role,
                )
                existing_users[email_hash] = user
                member_user_ids.add(user.id)
                results.append(
                    BulkMemberResultItem(
                        email=email_norm,
                        status="created",
                        user_id=user.id,
                        role=item.role,
                        # Only surface a password we generated, never a caller's.
                        temporary_password=None if item.password else temp_password,
                    )
                )
        except IntegrityError:
            # Lost a race (e.g. the account/membership was created concurrently).
            results.append(
                BulkMemberResultItem(
                    email=email_norm,
                    status="skipped",
                    error="Could not create member due to a conflict",
                )
            )

    counts = {"created": 0, "added_existing": 0, "already_member": 0, "skipped": 0}
    for result in results:
        counts[result.status] += 1

    logger.info(
        "bulk_members_processed",
        workspace_id=str(workspace_id),
        total=len(items),
        **counts,
    )

    return BulkMemberCreateResponse(total=len(items), results=results, **counts)
