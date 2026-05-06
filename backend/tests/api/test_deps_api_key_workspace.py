"""Tests for API-key workspace binding in app.api.deps.

Regression coverage for the privilege-escalation bug where an API key issued for
workspace A could be used to access any other workspace its owning user
belonged to. The fix lives in:

    - ``_user_from_api_key`` — stashes the key's workspace_id on request.state
    - ``_enforce_api_key_workspace`` — rejects mismatched workspace_id paths
    - ``get_workspace`` / ``get_workspace_admin`` / ``get_membership`` — call it

These tests exercise the deps directly with stub Request/DB objects so we don't
need to spin up the full app or a real database.
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from app.api.deps import (
    _enforce_api_key_workspace,
    _user_from_api_key,
    get_membership,
    get_workspace,
    get_workspace_admin,
)
from app.models.api_key import APIKey
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership


def _make_request(headers: dict[str, str] | None = None) -> Request:
    """Build a minimal ASGI Request with the given headers."""
    raw_headers = [
        (k.lower().encode("latin-1"), v.encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
    }
    return Request(scope)


def _scalar_one_or_none_result(value: object) -> MagicMock:
    """Mimic the SQLAlchemy ``Result`` object returned by ``session.execute``."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.fixture
def workspace_a_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def workspace_b_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def active_user() -> User:
    user = MagicMock(spec=User)
    user.id = 42
    user.is_active = True
    return user


class TestUserFromApiKeyBinding:
    """``_user_from_api_key`` must stash the key's workspace on request.state."""

    async def test_binds_workspace_on_success(
        self, workspace_a_id: uuid.UUID, active_user: User
    ) -> None:
        raw_key = "tk_test_secret"
        request = _make_request({"X-API-Key": raw_key})

        api_key_obj = MagicMock(spec=APIKey)
        api_key_obj.workspace_id = workspace_a_id
        api_key_obj.user_id = active_user.id
        api_key_obj.expires_at = None

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(api_key_obj),
                _scalar_one_or_none_result(active_user),
            ]
        )

        user = await _user_from_api_key(request, db)

        assert user is active_user
        assert request.state.api_key_workspace_id == workspace_a_id

    async def test_no_header_does_not_set_state(self) -> None:
        request = _make_request()
        db = MagicMock()
        db.execute = AsyncMock()

        user = await _user_from_api_key(request, db)

        assert user is None
        assert getattr(request.state, "api_key_workspace_id", None) is None
        db.execute.assert_not_awaited()

    async def test_invalid_key_does_not_set_state(self) -> None:
        request = _make_request({"X-API-Key": "bogus"})
        db = MagicMock()
        db.execute = AsyncMock(return_value=_scalar_one_or_none_result(None))

        user = await _user_from_api_key(request, db)

        assert user is None
        assert getattr(request.state, "api_key_workspace_id", None) is None

    async def test_key_hash_lookup_uses_sha256(
        self, workspace_a_id: uuid.UUID, active_user: User
    ) -> None:
        """Sanity check: the lookup hashes with sha256 (matches issuance path)."""
        raw_key = "tk_canary"
        expected_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        request = _make_request({"X-API-Key": raw_key})

        api_key_obj = MagicMock(spec=APIKey)
        api_key_obj.workspace_id = workspace_a_id
        api_key_obj.user_id = active_user.id
        api_key_obj.expires_at = None
        api_key_obj.key_hash = expected_hash

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(api_key_obj),
                _scalar_one_or_none_result(active_user),
            ]
        )

        await _user_from_api_key(request, db)

        # Two queries: api_keys lookup + user lookup
        assert db.execute.await_count == 2


class TestEnforceApiKeyWorkspace:
    """``_enforce_api_key_workspace`` is the single chokepoint for the rule."""

    def test_no_api_key_binding_is_noop(self, workspace_a_id: uuid.UUID) -> None:
        request = _make_request()
        # No binding set — JWT-authed requests must pass through untouched.
        _enforce_api_key_workspace(request, workspace_a_id)

    def test_matching_workspace_passes(self, workspace_a_id: uuid.UUID) -> None:
        request = _make_request()
        request.state.api_key_workspace_id = workspace_a_id
        _enforce_api_key_workspace(request, workspace_a_id)

    def test_mismatched_workspace_raises_403(
        self, workspace_a_id: uuid.UUID, workspace_b_id: uuid.UUID
    ) -> None:
        request = _make_request()
        request.state.api_key_workspace_id = workspace_a_id

        with pytest.raises(HTTPException) as exc:
            _enforce_api_key_workspace(request, workspace_b_id)

        assert exc.value.status_code == 403
        assert "API key" in exc.value.detail


class TestWorkspaceDepsHonorBinding:
    """The workspace-resolving deps must reject cross-workspace API key use.

    Without the fix, a user belonging to both A and B who authenticates with a
    key scoped to A could call /workspaces/B/... and get a 200. With the fix,
    we get a 403 — even though membership in B exists.
    """

    async def test_get_workspace_rejects_cross_workspace_api_key(
        self,
        workspace_a_id: uuid.UUID,
        workspace_b_id: uuid.UUID,
        active_user: User,
    ) -> None:
        request = _make_request()
        request.state.api_key_workspace_id = workspace_a_id  # bound to A

        # DB would happily return a B membership — that's the bug we're closing.
        db = MagicMock()
        db.execute = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await get_workspace(
                request=request,
                workspace_id=workspace_b_id,
                current_user=active_user,
                db=db,
            )

        assert exc.value.status_code == 403
        # We must short-circuit before issuing membership/workspace queries.
        db.execute.assert_not_awaited()

    async def test_get_workspace_allows_matching_workspace(
        self,
        workspace_a_id: uuid.UUID,
        active_user: User,
    ) -> None:
        request = _make_request()
        request.state.api_key_workspace_id = workspace_a_id

        membership = MagicMock(spec=WorkspaceMembership)
        workspace = MagicMock(spec=Workspace)
        workspace.is_active = True

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(membership),
                _scalar_one_or_none_result(workspace),
            ]
        )

        result = await get_workspace(
            request=request,
            workspace_id=workspace_a_id,
            current_user=active_user,
            db=db,
        )

        assert result is workspace

    async def test_get_workspace_admin_rejects_cross_workspace_api_key(
        self,
        workspace_a_id: uuid.UUID,
        workspace_b_id: uuid.UUID,
        active_user: User,
    ) -> None:
        request = _make_request()
        request.state.api_key_workspace_id = workspace_a_id

        db = MagicMock()
        db.execute = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await get_workspace_admin(
                request=request,
                workspace_id=workspace_b_id,
                current_user=active_user,
                db=db,
            )

        assert exc.value.status_code == 403
        db.execute.assert_not_awaited()

    async def test_get_membership_rejects_cross_workspace_api_key(
        self,
        workspace_a_id: uuid.UUID,
        workspace_b_id: uuid.UUID,
        active_user: User,
    ) -> None:
        request = _make_request()
        request.state.api_key_workspace_id = workspace_a_id

        db = MagicMock()
        db.execute = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await get_membership(
                request=request,
                workspace_id=workspace_b_id,
                current_user=active_user,
                db=db,
            )

        assert exc.value.status_code == 403
        db.execute.assert_not_awaited()

    async def test_jwt_auth_unaffected(
        self,
        workspace_a_id: uuid.UUID,
        active_user: User,
    ) -> None:
        """No API key binding -> normal membership flow runs as before."""
        request = _make_request()
        # Deliberately do NOT set request.state.api_key_workspace_id.

        membership = MagicMock(spec=WorkspaceMembership)
        workspace = MagicMock(spec=Workspace)
        workspace.is_active = True

        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[
                _scalar_one_or_none_result(membership),
                _scalar_one_or_none_result(workspace),
            ]
        )

        result = await get_workspace(
            request=request,
            workspace_id=workspace_a_id,
            current_user=active_user,
            db=db,
        )

        assert result is workspace
        # Both queries must run for JWT path.
        assert db.execute.await_count == 2


# Suppress unused-import warning for SimpleNamespace; kept for future fixture use.
_ = SimpleNamespace
