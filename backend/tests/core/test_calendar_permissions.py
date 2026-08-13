"""Calendar RBAC policy tests."""

import pytest

from app.core.permissions import appointment_owner_scope


@pytest.mark.parametrize("role", ["owner", "admin", "manager", "dispatcher"])
def test_supervisory_roles_can_view_every_calendar(role: str) -> None:
    assert appointment_owner_scope(role, 17) is None


@pytest.mark.parametrize(
    "role", ["sales_rep", "sales", "lead_technician", "technician", "member", "viewer", "unknown"]
)
def test_non_supervisory_roles_are_confined_to_their_calendar(role: str) -> None:
    assert appointment_owner_scope(role, 17) == 17
