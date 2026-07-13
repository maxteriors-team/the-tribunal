"""Unit tests for the RBAC capability matrix (:mod:`app.core.permissions`).

Pure functions, no DB — these pin the five-tier policy so a careless edit to the
matrix fails loudly. Tiers (admin broadest → field narrowest):

    admin ← owner, admin
    manager ← manager, dispatcher
    sales ← sales_rep
    tech ← member
    field ← technician  (and any unknown/legacy string, fail-closed)
"""

from __future__ import annotations

import pytest

from app.core.permissions import (
    Capability,
    Tier,
    capabilities_for,
    pipeline_owner_scope,
    role_can,
    role_tier,
)

ALL_ROLES = ["owner", "admin", "manager", "dispatcher", "sales_rep", "technician", "member"]


@pytest.mark.parametrize(
    ("role", "tier"),
    [
        ("owner", Tier.ADMIN),
        ("admin", Tier.ADMIN),
        ("manager", Tier.MANAGER),
        ("dispatcher", Tier.MANAGER),
        ("sales_rep", Tier.SALES),
        ("technician", Tier.FIELD),
        ("member", Tier.TECH),
    ],
)
def test_role_tier_mapping(role: str, tier: Tier) -> None:
    assert role_tier(role) is tier


def test_unknown_role_fails_closed_to_field() -> None:
    assert role_tier("wizard") is Tier.FIELD
    assert role_tier("") is Tier.FIELD
    # And therefore only ever gets the minimal (operational-only) capability set.
    assert capabilities_for("wizard") == capabilities_for("technician")


def test_admin_has_every_capability() -> None:
    assert capabilities_for("admin") == frozenset(Capability)
    assert capabilities_for("owner") == frozenset(Capability)


def test_capabilities_are_graded_admin_superset_of_all() -> None:
    admin = capabilities_for("admin")
    manager = capabilities_for("manager")
    sales = capabilities_for("sales_rep")
    tech = capabilities_for("member")
    field = capabilities_for("technician")
    # admin ⊇ manager ⊇ sales ⊇ tech ⊇ field (nested containment).
    assert field < tech < sales < manager < admin


def test_manager_runs_operations_but_not_reports_or_members() -> None:
    granted = {
        Capability.CRM_READ,
        Capability.CRM_WRITE,
        Capability.OUTREACH_WRITE,
        Capability.PIPELINE_WRITE,
        Capability.PIPELINE_WRITE_OWN,
        Capability.JOBS_READ,
        Capability.JOBS_WRITE,
        Capability.COMMS_SEND,
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
    }
    assert capabilities_for("manager") == frozenset(granted)
    for denied in (
        Capability.REPORTS_VIEW,
        Capability.MEMBERS_MANAGE,
        Capability.WORKSPACE_MANAGE,
        Capability.COMMS_MANAGE,
    ):
        assert not role_can("manager", denied)


def test_sales_owns_pipeline_and_authors_outreach() -> None:
    assert capabilities_for("sales_rep") == frozenset(
        {
            Capability.CRM_READ,
            Capability.OUTREACH_WRITE,
            Capability.PIPELINE_WRITE_OWN,
            Capability.JOBS_READ,
            Capability.COMMS_SEND,
        }
    )
    # Sales can author outreach (campaigns/segments/automations)…
    assert role_can("sales_rep", Capability.OUTREACH_WRITE)
    # …but not the destructive contact powers that ride on crm:write.
    for denied in (
        Capability.PIPELINE_WRITE,
        Capability.CRM_WRITE,
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
        Capability.JOBS_WRITE,
        Capability.REPORTS_VIEW,
        Capability.COMMS_MANAGE,
    ):
        assert not role_can("sales_rep", denied)


def test_crm_write_always_implies_outreach_write() -> None:
    # Writing contacts is strictly more than authoring outreach, so the invariant
    # must hold for every role that can write the CRM.
    for role in ALL_ROLES:
        caps = capabilities_for(role)
        if Capability.CRM_WRITE in caps:
            assert Capability.OUTREACH_WRITE in caps, role


def test_outreach_write_holders() -> None:
    # Sales + operations tiers author outreach; field techs and members do not.
    for role in ("owner", "admin", "manager", "dispatcher", "sales_rep"):
        assert role_can(role, Capability.OUTREACH_WRITE), role
    for role in ("technician", "member"):
        assert not role_can(role, Capability.OUTREACH_WRITE), role


def test_member_is_read_plus_messaging_only() -> None:
    assert capabilities_for("member") == frozenset(
        {Capability.CRM_READ, Capability.JOBS_READ, Capability.COMMS_SEND}
    )


def test_field_technician_is_operational_only() -> None:
    # A field technician sees only the jobs schedule: no CRM, pipeline,
    # campaigns, billing/pricing, comms, or reports.
    assert capabilities_for("technician") == frozenset({Capability.JOBS_READ})
    for denied in (
        Capability.CRM_READ,
        Capability.CRM_WRITE,
        Capability.PIPELINE_WRITE,
        Capability.PIPELINE_WRITE_OWN,
        Capability.JOBS_WRITE,
        Capability.COMMS_SEND,
        Capability.COMMS_MANAGE,
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
        Capability.REPORTS_VIEW,
        Capability.MEMBERS_MANAGE,
        Capability.WORKSPACE_MANAGE,
    ):
        assert not role_can("technician", denied), denied


def test_pipeline_write_implies_write_own() -> None:
    for role in ALL_ROLES:
        caps = capabilities_for(role)
        if Capability.PIPELINE_WRITE in caps:
            assert Capability.PIPELINE_WRITE_OWN in caps, role


def test_comms_send_is_broad_but_field_and_manage_are_excluded() -> None:
    # Every tier except field technicians can text/call customers.
    for role in ["owner", "admin", "manager", "dispatcher", "sales_rep", "member"]:
        assert role_can(role, Capability.COMMS_SEND), role
    # Field technicians are operational-only — no customer messaging.
    assert not role_can("technician", Capability.COMMS_SEND)
    for role in ["manager", "dispatcher", "sales_rep", "technician", "member"]:
        assert not role_can(role, Capability.COMMS_MANAGE), role
    assert role_can("admin", Capability.COMMS_MANAGE)
    assert role_can("owner", Capability.COMMS_MANAGE)


def test_reports_view_is_admin_only() -> None:
    assert role_can("admin", Capability.REPORTS_VIEW)
    assert role_can("owner", Capability.REPORTS_VIEW)
    for role in ["manager", "dispatcher", "sales_rep", "technician", "member"]:
        assert not role_can(role, Capability.REPORTS_VIEW), role


class TestPipelineOwnerScope:
    """``pipeline_owner_scope`` decides the sales tier's object-level restriction."""

    def test_managers_and_admins_see_all(self) -> None:
        for role in ("owner", "admin", "manager", "dispatcher"):
            assert pipeline_owner_scope(role, 99) is None, role

    def test_sales_is_restricted_to_own_user_id(self) -> None:
        assert pipeline_owner_scope("sales_rep", 99) == 99

    def test_read_only_tiers_are_not_restricted(self) -> None:
        # tech/member can read all (workspace-scoped); their writes are blocked
        # by the capability gate, not by an owner restriction.
        for role in ("technician", "member", "unknown"):
            assert pipeline_owner_scope(role, 99) is None, role
