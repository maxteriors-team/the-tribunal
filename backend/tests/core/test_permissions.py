"""Unit tests for the RBAC capability matrix (:mod:`app.core.permissions`).

Pure functions, no DB — these pin the six-tier policy so a careless edit to the
matrix fails loudly. Tiers (admin broadest → field narrowest):

    admin ← owner, admin
    manager ← manager, dispatcher
    sales ← sales_rep
    tech ← member
    lead ← lead_technician
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
    upsell_job_scope_required,
)

ALL_ROLES = [
    "owner",
    "admin",
    "manager",
    "dispatcher",
    "sales_rep",
    "lead_technician",
    "technician",
    "member",
]

_ALL_CAPABILITIES = frozenset(Capability)
_MANAGER_CAPABILITIES = frozenset(
    {
        Capability.CRM_READ,
        Capability.CRM_WRITE,
        Capability.PIPELINE_WRITE_OWN,
        Capability.PIPELINE_WRITE,
        Capability.JOBS_READ,
        Capability.JOBS_WRITE,
        Capability.ATTENDANCE_USE,
        Capability.COMMS_SEND,
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
        Capability.OUTREACH_WRITE,
        Capability.LOCATIONS_MANAGE,
        Capability.UPSELL_SELL,
        Capability.UPSELL_SELL_UNCAPPED,
    }
)
ROLE_CAPABILITY_MATRIX: dict[str, frozenset[Capability]] = {
    "owner": _ALL_CAPABILITIES,
    "admin": _ALL_CAPABILITIES,
    "manager": _MANAGER_CAPABILITIES,
    "dispatcher": _MANAGER_CAPABILITIES,
    "sales_rep": frozenset(
        {
            Capability.CRM_READ,
            Capability.PIPELINE_WRITE_OWN,
            Capability.JOBS_READ,
            Capability.ATTENDANCE_USE,
            Capability.COMMS_SEND,
            Capability.OUTREACH_WRITE,
            Capability.UPSELL_SELL,
            Capability.UPSELL_SELL_UNCAPPED,
        }
    ),
    "member": frozenset(
        {
            Capability.CRM_READ,
            Capability.JOBS_READ,
            Capability.ATTENDANCE_USE,
            Capability.COMMS_SEND,
            Capability.UPSELL_SELL,
            Capability.UPSELL_SELL_UNCAPPED,
        }
    ),
    "lead_technician": frozenset(
        {Capability.JOBS_READ, Capability.ATTENDANCE_USE, Capability.UPSELL_SELL}
    ),
    "technician": frozenset({Capability.JOBS_READ, Capability.ATTENDANCE_USE}),
}


@pytest.mark.parametrize(("role", "expected"), ROLE_CAPABILITY_MATRIX.items())
def test_eight_role_capability_matrix(role: str, expected: frozenset[Capability]) -> None:
    """Every role is checked against every capability, not selected examples."""
    assert capabilities_for(role) == expected
    for capability in Capability:
        assert role_can(role, capability) is (capability in expected), (role, capability)


@pytest.mark.parametrize(
    ("role", "tier"),
    [
        ("owner", Tier.ADMIN),
        ("admin", Tier.ADMIN),
        ("manager", Tier.MANAGER),
        ("dispatcher", Tier.MANAGER),
        ("sales_rep", Tier.SALES),
        ("lead_technician", Tier.LEAD),
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


def test_attendance_use_is_universal_and_manage_is_admin_only() -> None:
    for role in ALL_ROLES:
        assert role_can(role, Capability.ATTENDANCE_USE), role
        assert role_can(role, Capability.ATTENDANCE_MANAGE) is (role in {"owner", "admin"})


def test_capabilities_are_graded_admin_superset_of_all() -> None:
    admin = capabilities_for("admin")
    manager = capabilities_for("manager")
    sales = capabilities_for("sales_rep")
    tech = capabilities_for("member")
    lead = capabilities_for("lead_technician")
    field = capabilities_for("technician")
    # admin ⊇ manager ⊇ sales ⊇ tech ⊇ lead ⊇ field (nested containment).
    assert field < lead < tech < sales < manager < admin


def test_manager_runs_operations_but_not_reports_or_members() -> None:
    granted = {
        Capability.CRM_READ,
        Capability.CRM_WRITE,
        Capability.OUTREACH_WRITE,
        Capability.PIPELINE_WRITE,
        Capability.PIPELINE_WRITE_OWN,
        Capability.JOBS_READ,
        Capability.JOBS_WRITE,
        Capability.ATTENDANCE_USE,
        Capability.COMMS_SEND,
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
        Capability.LOCATIONS_MANAGE,
        Capability.UPSELL_SELL,
        Capability.UPSELL_SELL_UNCAPPED,
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
            Capability.ATTENDANCE_USE,
            Capability.COMMS_SEND,
            Capability.UPSELL_SELL,
            Capability.UPSELL_SELL_UNCAPPED,
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
        {
            Capability.CRM_READ,
            Capability.JOBS_READ,
            Capability.ATTENDANCE_USE,
            Capability.COMMS_SEND,
            Capability.UPSELL_SELL,
            Capability.UPSELL_SELL_UNCAPPED,
        }
    )


def test_field_technician_is_operational_only() -> None:
    # A field technician sees jobs and their own attendance clock — no CRM,
    # pipeline, campaigns, billing/pricing, comms, reports, or selling.
    assert capabilities_for("technician") == frozenset(
        {Capability.JOBS_READ, Capability.ATTENDANCE_USE}
    )
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


def test_locations_manage_is_admin_and_manager_only() -> None:
    # Managing business locations (branches) is an operations power: admin +
    # manager tier (owner/admin/manager/dispatcher). Everyone else only reads.
    for role in ("owner", "admin", "manager", "dispatcher"):
        assert role_can(role, Capability.LOCATIONS_MANAGE), role
    for role in ("sales_rep", "technician", "member"):
        assert not role_can(role, Capability.LOCATIONS_MANAGE), role


def test_reports_view_is_admin_only() -> None:
    assert role_can("admin", Capability.REPORTS_VIEW)
    assert role_can("owner", Capability.REPORTS_VIEW)
    for role in ["manager", "dispatcher", "sales_rep", "technician", "member"]:
        assert not role_can(role, Capability.REPORTS_VIEW), role


class TestUpsellSell:
    """``upsell:sell`` lets a crew lead sell an add-on on their own job.

    A plain technician does **not** hold it: quoting is a lead-technician
    responsibility. It is not a general grant even for those who do hold it —
    only ``app.api.v1.upsell`` honours it, and those routes re-scope to the
    caller's assigned jobs.
    """

    def test_a_plain_technician_cannot_sell(self) -> None:
        # The business rule: regular techs do not quote, they escalate to their
        # crew lead. Enforced in the matrix, so every upsell route refuses them.
        assert not role_can("technician", Capability.UPSELL_SELL)

    def test_every_tier_from_lead_up_can_upsell(self) -> None:
        for role in ALL_ROLES:
            if role == "technician":
                continue
            assert role_can(role, Capability.UPSELL_SELL), role

    def test_field_tier_is_exactly_jobs_and_own_attendance(self) -> None:
        # Field is the floor of the matrix: every other tier inherits these
        # operational capabilities, while selling power remains excluded.
        assert capabilities_for("technician") == frozenset(
            {Capability.JOBS_READ, Capability.ATTENDANCE_USE}
        )

    def test_upsell_does_not_smuggle_in_crm_billing_or_comms(self) -> None:
        # Regression guard for the tempting shortcut of "just give the seller
        # crm:read and comms:send". Delivery rides the scoped upsell route
        # instead, so a crew lead still cannot read the contact book or text
        # arbitrary people.
        for denied in (
            Capability.CRM_READ,
            Capability.CRM_WRITE,
            Capability.BILLING_READ,
            Capability.BILLING_WRITE,
            Capability.COMMS_SEND,
            Capability.PIPELINE_WRITE_OWN,
            Capability.JOBS_WRITE,
            Capability.REPORTS_VIEW,
        ):
            assert not role_can("lead_technician", denied), denied
            assert not role_can("technician", denied), denied

    def test_unknown_roles_cannot_sell(self) -> None:
        # Fail-closed lands on the field tier, which can no longer sell at all.
        assert not role_can("wizard", Capability.UPSELL_SELL)
        assert upsell_job_scope_required("wizard")


class TestLeadTechnician:
    """The crew lead: the one field worker trusted to sell on site.

    The role exists to answer one question — who may quote from a driveway — so
    the tests here are mostly about what it does *not* also grant.
    """

    def test_lead_is_field_plus_selling_and_nothing_else(self) -> None:
        assert capabilities_for("lead_technician") == frozenset(
            {
                Capability.JOBS_READ,
                Capability.ATTENDANCE_USE,
                Capability.UPSELL_SELL,
            }
        )

    def test_promoting_a_tech_to_lead_opens_no_other_door(self) -> None:
        # The entire delta between the two roles is one capability. A lead tech
        # is still a field worker: no contact book, no price book, no pipeline,
        # and no blanket messaging.
        assert capabilities_for("lead_technician") - capabilities_for("technician") == {
            Capability.UPSELL_SELL
        }
        for denied in (
            Capability.CRM_READ,
            Capability.CRM_WRITE,
            Capability.BILLING_READ,
            Capability.BILLING_WRITE,
            Capability.COMMS_SEND,
            Capability.JOBS_WRITE,
            Capability.REPORTS_VIEW,
            Capability.MEMBERS_MANAGE,
        ):
            assert not role_can("lead_technician", denied), denied

    def test_lead_is_still_confined_to_its_own_assigned_jobs(self) -> None:
        # Selling authority is not visibility: a crew lead sees exactly the jobs
        # a regular technician sees.
        assert upsell_job_scope_required("lead_technician")

    def test_the_crew_lead_is_the_one_seller_the_limit_applies_to(self) -> None:
        # Office tiers sell uncapped; the lead sells under the workspace limit;
        # the plain technician does not sell at all, so "capped" is moot there.
        for role in ALL_ROLES:
            if role in ("technician", "lead_technician"):
                assert not role_can(role, Capability.UPSELL_SELL_UNCAPPED), role
            else:
                assert role_can(role, Capability.UPSELL_SELL_UNCAPPED), role
        assert role_can("lead_technician", Capability.UPSELL_SELL)

    def test_unknown_roles_stay_capped(self) -> None:
        # Fail-closed lands on ``field``, which cannot sell at all.
        assert not role_can("wizard", Capability.UPSELL_SELL_UNCAPPED)
        assert not role_can("wizard", Capability.UPSELL_SELL)


class TestUpsellJobScope:
    """``upsell_job_scope_required`` decides who is confined to their own jobs."""

    def test_billing_writers_are_unrestricted(self) -> None:
        # They can already quote any contact through the quotes API, so scoping
        # them here would cost a query and buy nothing.
        for role in ("owner", "admin", "manager", "dispatcher"):
            assert not upsell_job_scope_required(role), role

    def test_field_sales_and_tech_are_confined_to_assigned_jobs(self) -> None:
        for role in ("technician", "sales_rep", "member"):
            assert upsell_job_scope_required(role), role

    def test_restriction_tracks_billing_write_not_a_role_list(self) -> None:
        # The rule is derived from the capability, so a future tier that gains
        # billing:write is automatically unrestricted and one that loses it is
        # automatically confined — no second list to keep in sync.
        for role in ALL_ROLES:
            assert upsell_job_scope_required(role) is not role_can(
                role, Capability.BILLING_WRITE
            ), role


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
