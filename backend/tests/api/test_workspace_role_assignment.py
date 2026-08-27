"""Regression tests for privilege-sensitive workspace role assignment.

These drive the real FastAPI handlers through HTTP while replacing only identity
and persistence.  ``members:manage`` lets owners and admins manage ordinary
roles, but granting ``admin`` is an owner-only action at both creation and
acceptance time.
"""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_current_user,
    get_db,
    get_membership,
    get_optional_current_user,
)
from app.api.v1 import invitations, workspaces

WORKSPACE_ID = uuid.uuid4()
OWNER_ID = 101
ADMIN_ID = 102
TARGET_ID = 201
INVITEE_ID = 202
INVITATION_TOKEN = "pending-admin-invitation"


def _result(*, scalar: object | None = None, first: object | None = None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    result.scalar_one.return_value = scalar
    result.scalars.return_value.first.return_value = first
    result.scalars.return_value.all.return_value = []
    result.first.return_value = first
    return result


def _db() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


def _app(
    db: MagicMock,
    *,
    user: types.SimpleNamespace | None = None,
    membership_role: str | None = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(workspaces.router, prefix="/api/v1/workspaces")
    app.include_router(
        invitations.router,
        prefix="/api/v1/workspaces/{workspace_id}/invitations",
    )
    app.include_router(invitations.public_router, prefix="/api/v1/invitations")

    async def override_db() -> AsyncIterator[MagicMock]:
        yield db

    async def override_user() -> types.SimpleNamespace | None:
        return user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_optional_current_user] = override_user

    if membership_role is not None:

        async def override_membership() -> types.SimpleNamespace:
            return types.SimpleNamespace(
                role=membership_role,
                workspace_id=WORKSPACE_ID,
                user_id=user.id if user is not None else 1,
            )

        app.dependency_overrides[get_membership] = override_membership

    return app


async def test_owner_may_grant_admin_role_to_an_existing_member() -> None:
    db = _db()
    target = types.SimpleNamespace(
        user_id=TARGET_ID,
        workspace_id=WORKSPACE_ID,
        role="member",
    )
    db.execute.return_value = _result(scalar=target)
    app = _app(db, membership_role="owner")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/workspaces/{WORKSPACE_ID}/members/{TARGET_ID}/role",
            json={"role": "admin"},
        )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert target.role == "admin"
    db.commit.assert_awaited_once()


async def test_admin_cannot_promote_a_non_admin_to_admin() -> None:
    db = _db()
    target = types.SimpleNamespace(
        user_id=TARGET_ID,
        workspace_id=WORKSPACE_ID,
        role="member",
    )
    db.execute.return_value = _result(scalar=target)
    app = _app(db, membership_role="admin")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put(
            f"/api/v1/workspaces/{WORKSPACE_ID}/members/{TARGET_ID}/role",
            json={"role": "admin"},
        )

    assert response.status_code == 403
    assert target.role == "member"
    db.commit.assert_not_awaited()


async def test_admin_cannot_invite_an_admin(monkeypatch: Any) -> None:
    db = _db()
    actor = types.SimpleNamespace(
        id=ADMIN_ID,
        email="admin@example.com",
        full_name="Workspace Admin",
        is_active=True,
    )
    actor_membership = types.SimpleNamespace(
        user_id=ADMIN_ID,
        workspace_id=WORKSPACE_ID,
        role="admin",
    )
    workspace = types.SimpleNamespace(id=WORKSPACE_ID, name="Role Guard Co")
    db.execute.side_effect = [
        _result(scalar=actor_membership),
        _result(scalar=workspace),
        _result(),
        _result(),
    ]

    async def commit_with_invitation_defaults() -> None:
        invitation = db.add.call_args.args[0]
        invitation.id = uuid.uuid4()
        invitation.token = "created-invitation"
        invitation.status = "pending"
        invitation.expires_at = datetime.now(UTC) + timedelta(days=7)
        invitation.created_at = datetime.now(UTC)
        invitation.accepted_at = None

    db.commit.side_effect = commit_with_invitation_defaults
    send_email = AsyncMock()
    monkeypatch.setattr(invitations, "send_invitation_email", send_email)
    app = _app(db, user=actor)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/workspaces/{WORKSPACE_ID}/invitations",
            json={"email": "new-admin@example.com", "role": "admin"},
        )

    assert response.status_code == 403
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
    send_email.assert_not_awaited()


async def test_pending_admin_invitation_fails_if_inviter_is_no_longer_owner() -> None:
    db = _db()
    invitee = types.SimpleNamespace(
        id=INVITEE_ID,
        email="invitee@example.com",
        full_name="Invited User",
        is_active=True,
    )
    former_owner_membership = types.SimpleNamespace(
        user_id=OWNER_ID,
        workspace_id=WORKSPACE_ID,
        role="admin",
    )
    invitation = types.SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        email=invitee.email,
        role="admin",
        token=INVITATION_TOKEN,
        status="pending",
        invited_by_id=OWNER_ID,
        expires_at=datetime.now(UTC) + timedelta(days=1),
        accepted_at=None,
        is_expired=False,
        is_valid=True,
        workspace=types.SimpleNamespace(name="Role Guard Co", slug="role-guard-co"),
    )

    async def execute(statement: Any) -> MagicMock:
        params = statement.compile().params.values()
        if INVITATION_TOKEN in params:
            return _result(scalar=invitation)
        if OWNER_ID in params:
            # The inviter still belongs to the workspace but has been demoted.
            return _result(scalar=former_owner_membership, first=former_owner_membership)
        return _result()

    db.execute.side_effect = execute
    app = _app(db, user=invitee)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/invitations/{INVITATION_TOKEN}/accept",
        )

    assert response.status_code == 403
    assert invitation.status == "pending"
    assert invitation.accepted_at is None
    db.add.assert_not_called()
    db.commit.assert_not_awaited()
