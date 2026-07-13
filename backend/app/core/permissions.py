"""Capability-based authorization for workspace members.

This is the policy layer that sits on top of the role *vocabulary* in
:mod:`app.core.roles`. Where ``roles.py`` answers "what role string does this
membership hold", this module answers "what is that role allowed to do".

The CRM has accumulated seven role strings (``owner, admin, manager, dispatcher,
sales_rep, technician, member``). For access control they collapse into **five
graded tiers**, admin broadest:

============== ============================== ==========================================
tier           maps from roles                intent
============== ============================== ==========================================
``admin``      ``owner``, ``admin``           everything: members, billing, reports, settings
``manager``    ``manager``, ``dispatcher``    run operations (CRM, jobs, billing); **no** reports
``sales``      ``sales_rep``                  manage **own** pipeline; read CRM; text/call
``tech``       ``member``                     read CRM + jobs; log time; text/call
``field``      ``technician``                 operational only: view assigned jobs on the schedule
============== ============================== ==========================================

Field technicians are deliberately the narrowest tier: they see only the jobs
schedule, with no access to contacts, pipeline, campaigns, billing/pricing, or
any other CRM surface. Reads on those surfaces are capability-gated, so the
matrix here is the enforcement point, not just a nav filter.

Unknown / legacy role strings fall through to the **field** tier (lowest
privilege) so a corrupted or unrecognised value fails closed rather than
silently escalating.

API dependencies in :mod:`app.api.deps` consume :func:`role_can` /
:func:`capabilities_for` to gate endpoints; the frontend mirrors this matrix in
``frontend/src/lib/permissions.ts``. Keep the two in sync.
"""

from __future__ import annotations

from enum import StrEnum

from app.core.roles import WorkspaceRole


class Capability(StrEnum):
    """A discrete, resource-level permission an endpoint can require."""

    CRM_READ = "crm:read"
    CRM_WRITE = "crm:write"
    # ``pipeline:write`` = manage *any* opportunity; ``pipeline:write_own`` =
    # manage only opportunities the caller is the assigned owner of. The former
    # always implies the latter (see ``_TIER_CAPABILITIES`` construction).
    PIPELINE_WRITE = "pipeline:write"
    PIPELINE_WRITE_OWN = "pipeline:write_own"
    JOBS_READ = "jobs:read"
    JOBS_WRITE = "jobs:write"
    # ``comms:send`` = use workspace numbers to text/call customers (every tier);
    # ``comms:manage`` = provision numbers (search/purchase/release) — admin only,
    # because it spends money.
    COMMS_SEND = "comms:send"
    COMMS_MANAGE = "comms:manage"
    BILLING_READ = "billing:read"
    BILLING_WRITE = "billing:write"
    REPORTS_VIEW = "reports:view"
    MEMBERS_MANAGE = "members:manage"
    WORKSPACE_MANAGE = "workspace:manage"


class Tier(StrEnum):
    """The access tier a role collapses into. Ordered admin → field."""

    ADMIN = "admin"
    MANAGER = "manager"
    SALES = "sales"
    TECH = "tech"
    FIELD = "field"


# Role string → tier. Anything not listed resolves to ``Tier.FIELD`` via
# :func:`role_tier` (fail-closed), so new/legacy/corrupt strings never escalate.
_ROLE_TIERS: dict[str, Tier] = {
    WorkspaceRole.OWNER.value: Tier.ADMIN,
    WorkspaceRole.ADMIN.value: Tier.ADMIN,
    WorkspaceRole.MANAGER.value: Tier.MANAGER,
    WorkspaceRole.DISPATCHER.value: Tier.MANAGER,
    WorkspaceRole.SALES_REP.value: Tier.SALES,
    WorkspaceRole.TECHNICIAN.value: Tier.FIELD,
    WorkspaceRole.MEMBER.value: Tier.TECH,
}


def _build_matrix() -> dict[Tier, frozenset[Capability]]:
    """Construct the tier→capabilities matrix.

    ``admin`` is granted every capability automatically so a newly added
    capability is never accidentally withheld from admins. ``pipeline:write``
    implies ``pipeline:write_own`` everywhere, enforced here rather than relying
    on each tier's list being written correctly.
    """
    manager: set[Capability] = {
        Capability.CRM_READ,
        Capability.CRM_WRITE,
        Capability.PIPELINE_WRITE,
        Capability.JOBS_READ,
        Capability.JOBS_WRITE,
        Capability.COMMS_SEND,
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
    }
    sales: set[Capability] = {
        Capability.CRM_READ,
        Capability.PIPELINE_WRITE_OWN,
        Capability.JOBS_READ,
        Capability.COMMS_SEND,
    }
    tech: set[Capability] = {
        Capability.CRM_READ,
        Capability.JOBS_READ,
        Capability.COMMS_SEND,
    }
    # Field technicians are operational-only: the jobs schedule and nothing else.
    # No CRM/pipeline/campaigns/billing, so pricing and customer data stay hidden.
    field: set[Capability] = {
        Capability.JOBS_READ,
    }

    matrix: dict[Tier, set[Capability]] = {
        Tier.ADMIN: set(Capability),
        Tier.MANAGER: manager,
        Tier.SALES: sales,
        Tier.TECH: tech,
        Tier.FIELD: field,
    }

    # Invariant: anyone who can write any opportunity can write their own.
    for caps in matrix.values():
        if Capability.PIPELINE_WRITE in caps:
            caps.add(Capability.PIPELINE_WRITE_OWN)

    return {tier: frozenset(caps) for tier, caps in matrix.items()}


TIER_CAPABILITIES: dict[Tier, frozenset[Capability]] = _build_matrix()


def role_tier(role: str) -> Tier:
    """Return the access tier for a role string, defaulting to ``Tier.FIELD``.

    Fail-closed: unknown/legacy/corrupt strings get the lowest tier.
    """
    return _ROLE_TIERS.get(role, Tier.FIELD)


def capabilities_for(role: str) -> frozenset[Capability]:
    """Return the full set of capabilities a role string is granted."""
    return TIER_CAPABILITIES[role_tier(role)]


def role_can(role: str, capability: Capability) -> bool:
    """Return True when ``role`` is granted ``capability``."""
    return capability in capabilities_for(role)


def pipeline_owner_scope(role: str, user_id: int) -> int | None:
    """Return the user id a caller's pipeline access is restricted to, or ``None``.

    Object-level scoping for the sales pipeline:

    - Roles with ``pipeline:write`` (admin, manager) manage **every** opportunity
      → ``None`` (no restriction).
    - The sales tier holds only ``pipeline:write_own`` → restricted to deals it
      owns (``assigned_user_id == user_id``).
    - Read-only tiers (tech) hold neither write capability → ``None``; they may
      *read* every opportunity (workspace-scoped) but the capability gate blocks
      them from writing regardless.
    """
    if role_can(role, Capability.PIPELINE_WRITE):
        return None
    if role_can(role, Capability.PIPELINE_WRITE_OWN):
        return user_id
    return None
