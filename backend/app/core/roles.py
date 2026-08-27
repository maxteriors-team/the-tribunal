"""Workspace role definitions and rank-based authorization helpers.

Workspace membership roles are stored as plain strings on
:class:`app.models.workspace.WorkspaceMembership` (the ``role`` column). This
module is the single source of truth for the role vocabulary and the relative
privilege ordering used by the role-gated API dependencies in
:mod:`app.api.deps`.

Historically only ``owner``/``admin``/``member`` were used. The field-service
and sales features add operational roles (``manager``, ``dispatcher``,
``sales_rep``, ``technician``, ``lead_technician``) so dispatch boards,
maintenance management, and the sales portal can be scoped per login. Existing
string values remain valid — no data migration is required.

The ``role`` column is a plain ``String(50)`` with no database enum or check
constraint, so adding a role here is a code-only change.
"""

from enum import StrEnum
from typing import Literal, get_args


class WorkspaceRole(StrEnum):
    """Roles a user may hold within a workspace.

    Values are persisted verbatim in ``workspace_memberships.role``.
    """

    OWNER = "owner"
    ADMIN = "admin"
    MANAGER = "manager"
    DISPATCHER = "dispatcher"
    SALES_REP = "sales_rep"
    # The senior technician who runs a crew on site. Operationally identical to
    # ``TECHNICIAN`` — same schedule, same scoped customer access — but trusted
    # to quote: this is the only field role that may sell an add-on on site (see
    # :data:`Capability.UPSELL_SELL`), held to the workspace's proposal limit.
    LEAD_TECHNICIAN = "lead_technician"
    TECHNICIAN = "technician"
    MEMBER = "member"


# Relative privilege ordering. Higher rank == more privilege. Used by
# ``role_at_least`` for threshold checks; explicit allow-lists are preferred for
# the dependency factory so peer roles (e.g. dispatcher vs sales_rep, both 40)
# never accidentally inherit each other's access.
ROLE_RANK: dict[str, int] = {
    WorkspaceRole.OWNER.value: 100,
    WorkspaceRole.ADMIN.value: 80,
    WorkspaceRole.MANAGER.value: 60,
    WorkspaceRole.DISPATCHER.value: 40,
    WorkspaceRole.SALES_REP.value: 40,
    # Above ``technician`` (more selling authority), below ``dispatcher`` (a lead
    # tech runs a crew on a job, not the board).
    WorkspaceRole.LEAD_TECHNICIAN.value: 30,
    WorkspaceRole.TECHNICIAN.value: 20,
    WorkspaceRole.MEMBER.value: 10,
}


# Roles that may be assigned via invitation or role-change. ``owner`` is
# intentionally excluded: ownership is established at workspace creation and is
# transferred through dedicated flows, never handed out like a regular role.
AssignableRole = Literal[
    "admin",
    "manager",
    "dispatcher",
    "sales_rep",
    "lead_technician",
    "technician",
    "member",
]


def can_assign_workspace_role(actor_role: str, target_role: str) -> bool:
    """Return whether an actor may grant ``target_role`` to a workspace member."""
    if target_role not in get_args(AssignableRole):
        return False
    return actor_role == WorkspaceRole.OWNER or (
        actor_role == WorkspaceRole.ADMIN and target_role != WorkspaceRole.ADMIN
    )


def role_at_least(role: str, minimum: WorkspaceRole) -> bool:
    """Return True when ``role`` ranks at or above ``minimum``.

    Unknown role strings rank as ``0`` (below every real role) so a corrupted or
    legacy value fails closed rather than silently granting access.
    """
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum.value]
