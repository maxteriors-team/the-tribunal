"""Audience policy for operator notifications.

The bug these lock down: a field technician was pushed every customer deposit,
while the sales rep who sold the job was emailed none of them.
"""

import pytest

from app.core.permissions import Tier
from app.core.roles import ROLE_RANK, WorkspaceRole
from app.services.notification_policy import audience_for, role_receives, roles_for

MONEY_TYPES = ("payment", "quote_accepted")
FIELD_ROLES = (WorkspaceRole.TECHNICIAN.value, WorkspaceRole.LEAD_TECHNICIAN.value)


@pytest.mark.parametrize("notification_type", MONEY_TYPES)
@pytest.mark.parametrize("role", FIELD_ROLES)
def test_field_roles_never_hear_about_money(role: str, notification_type: str) -> None:
    assert not role_receives(role, notification_type)


@pytest.mark.parametrize("notification_type", MONEY_TYPES)
def test_sales_hears_about_money(notification_type: str) -> None:
    assert role_receives(WorkspaceRole.SALES_REP.value, notification_type)


@pytest.mark.parametrize("role", [r.value for r in WorkspaceRole])
def test_job_assignment_reaches_every_role_including_the_crew(role: str) -> None:
    assert role_receives(role, "job_assignment")


@pytest.mark.parametrize("notification_type", ["review", "roleplay", "automation"])
def test_back_office_noise_stops_at_manager(notification_type: str) -> None:
    assert role_receives(WorkspaceRole.MANAGER.value, notification_type)
    assert not role_receives(WorkspaceRole.SALES_REP.value, notification_type)
    assert not role_receives(WorkspaceRole.TECHNICIAN.value, notification_type)


@pytest.mark.parametrize("notification_type", [None, "some_future_event"])
def test_unknown_type_fails_closed_to_admin(notification_type: str | None) -> None:
    assert audience_for(notification_type) == frozenset({Tier.ADMIN})
    assert role_receives(WorkspaceRole.OWNER.value, notification_type)
    assert not role_receives(WorkspaceRole.MANAGER.value, notification_type)


def test_corrupt_role_string_gets_dispatch_only() -> None:
    assert not role_receives("cfo_of_vibes", "payment")
    assert role_receives("cfo_of_vibes", "job_assignment")


def test_owner_and_admin_receive_every_mapped_type() -> None:
    for notification_type in (*MONEY_TYPES, "new_lead", "review", "job_assignment", "call"):
        assert role_receives(WorkspaceRole.OWNER.value, notification_type)
        assert role_receives(WorkspaceRole.ADMIN.value, notification_type)


def test_roles_for_returns_known_role_strings_only() -> None:
    payment_roles = roles_for("payment")
    assert set(payment_roles) <= set(ROLE_RANK)
    assert WorkspaceRole.SALES_REP.value in payment_roles
    assert WorkspaceRole.TECHNICIAN.value not in payment_roles
    assert WorkspaceRole.MEMBER.value not in payment_roles
