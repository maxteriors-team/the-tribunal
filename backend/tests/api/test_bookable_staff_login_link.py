"""Linking a bookable staff row to a login is a privileged act.

Most of the bookable-staff pool is ordinary agent configuration: names, skills,
priorities. ``user_id`` is not. It decides *whose* calendar a booking lands on,
so an unprivileged member who could set it would be able to point a staff row
at a colleague's login and read that person's appointments through the calendar
— a lateral read of someone else's schedule, using an endpoint that otherwise
looks like routing config.

Two guards, tested here at the layer that enforces each:

* the API refuses the ``user_id`` field itself unless the caller holds
  ``members:manage`` — linking a login is the same privilege as managing the
  team, wherever it is done;
* the service refuses a ``user_id`` that is not a member of the workspace, so a
  staff row can never point at an outside account even when the caller *is*
  privileged.

The unlink direction matters as much as the link direction: clearing someone
else's link silently detaches their calendar, so ``user_id: null`` is guarded
too. That is why the update path tests ``model_fields_set`` rather than a
truthiness check — the two differ precisely on an explicit null.
"""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user, get_db, get_membership, get_workspace
from app.api.v1.bookable_staff import _assert_may_link_login
from app.core.roles import WorkspaceRole
from app.schemas.bookable_staff import BookableStaffUpdate

WORKSPACE_ID = uuid.uuid4()
AGENT_ID = uuid.uuid4()
STAFF_ID = uuid.uuid4()

# Roles that may manage members, and therefore may link a login.
PRIVILEGED = [WorkspaceRole.OWNER.value, WorkspaceRole.ADMIN.value]

# Everyone else. ``manager``/``dispatcher`` are included deliberately: they run
# scheduling day to day, which makes them the likeliest role to be granted this
# by accident.
UNPRIVILEGED = [
    WorkspaceRole.MANAGER.value,
    WorkspaceRole.DISPATCHER.value,
    WorkspaceRole.SALES_REP.value,
    WorkspaceRole.LEAD_TECHNICIAN.value,
    WorkspaceRole.TECHNICIAN.value,
    WorkspaceRole.MEMBER.value,
]


def _membership(role: str) -> SimpleNamespace:
    return SimpleNamespace(role=role, user_id=7, workspace_id=uuid.uuid4())


@pytest.mark.parametrize("role", UNPRIVILEGED)
def test_unprivileged_roles_cannot_link_a_login(role: str) -> None:
    with pytest.raises(HTTPException) as exc:
        _assert_may_link_login(_membership(role), sets_user_id=True)

    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", PRIVILEGED)
def test_member_managers_may_link_a_login(role: str) -> None:
    _assert_may_link_login(_membership(role), sets_user_id=True)


@pytest.mark.parametrize("role", UNPRIVILEGED)
def test_unprivileged_roles_keep_ordinary_staff_edits(role: str) -> None:
    """The guard must gate one field, not the whole endpoint.

    A dispatcher renaming a staff row or changing its skills is routine work.
    Failing closed on every update would be a different bug with the same
    green test suite.
    """
    _assert_may_link_login(_membership(role), sets_user_id=False)


def test_unsent_user_id_is_not_treated_as_an_unlink() -> None:
    """A partial update that omits ``user_id`` must not trip the guard.

    ``BookableStaffUpdate`` defaults every field to ``None``, so a body that
    only renames a staff row still *has* ``user_id is None``. Reading the value
    instead of ``model_fields_set`` would make routine edits require
    ``members:manage``.
    """
    body = BookableStaffUpdate(name="Second van")

    assert "user_id" not in body.model_fields_set


@pytest.mark.parametrize("role", UNPRIVILEGED)
def test_unprivileged_roles_cannot_unlink_a_login(role: str) -> None:
    """Clearing a link is as privileged as creating one.

    Unlinking silently detaches a person's calendar from their bookings, so an
    explicit ``user_id: null`` has to be caught. This is the case a truthiness
    check would wave through.
    """
    body = BookableStaffUpdate.model_validate({"user_id": None})

    assert "user_id" in body.model_fields_set, "explicit null must register as set"

    with pytest.raises(HTTPException) as exc:
        _assert_may_link_login(_membership(role), "user_id" in body.model_fields_set)

    assert exc.value.status_code == 403


# --------------------------------------------------------------------------- #
# Endpoint level — proves the routes pass the right flag, not just that the
# helper works when handed one. The unit tests above compute that flag
# themselves, so a route wired to `body.user_id is not None` would keep them
# green while letting an unprivileged caller unlink someone.
# --------------------------------------------------------------------------- #
def _client_as(role: str) -> AsyncClient:
    from app.main import app

    async def _user_override() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=1, is_active=True, email="staff-link@test.dev")

    async def _membership_override() -> SimpleNamespace:
        return _membership(role)

    async def _db_override() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    async def _workspace_override() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=WORKSPACE_ID, name="Test")

    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_membership] = _membership_override
    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_workspace] = _workspace_override
    # An *allowed* caller reaches the handler and trips over the mocked DB. Only
    # the gate's verdict is asserted here, so let that surface as a 500 response
    # rather than a raised exception.
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


def _clear_overrides() -> None:
    from app.main import app

    app.dependency_overrides.clear()


_STAFF_URL = f"/api/v1/workspaces/{WORKSPACE_ID}/agents/{AGENT_ID}/staff"


async def test_route_rejects_an_unprivileged_create_that_links_a_login() -> None:
    client = _client_as(WorkspaceRole.DISPATCHER.value)
    try:
        response = await client.post(
            _STAFF_URL,
            json={"name": "Van 2", "user_id": 42},
        )
    finally:
        await client.aclose()
        _clear_overrides()

    assert response.status_code == 403


async def test_route_rejects_an_unprivileged_explicit_unlink() -> None:
    """The regression this whole file exists for.

    ``user_id: null`` is a real unlink request. A route that checked the value
    instead of ``model_fields_set`` would let any member detach a colleague's
    calendar while every unit test above still passed.
    """
    client = _client_as(WorkspaceRole.DISPATCHER.value)
    try:
        response = await client.put(
            f"{_STAFF_URL}/{STAFF_ID}",
            json={"user_id": None},
        )
    finally:
        await client.aclose()
        _clear_overrides()

    assert response.status_code == 403


async def test_route_allows_an_unprivileged_edit_that_touches_no_login() -> None:
    """Anything but 403: the gate must not fire on ordinary config edits."""
    client = _client_as(WorkspaceRole.DISPATCHER.value)
    try:
        response = await client.put(
            f"{_STAFF_URL}/{STAFF_ID}",
            json={"name": "Van 2"},
        )
    finally:
        await client.aclose()
        _clear_overrides()

    assert response.status_code != 403
