"""Tenant scoping on the surfaces that are not authenticated HTTP routes.

Every capability gate this codebase has lives on an API route
(``docs/technician-role-audit.md``, findings 1-9). These surfaces do not go
through those dependencies at all, so they need their own proof:

* **WebSockets** (``app/websockets/``) \u2014 authenticate from a JWT ticket, then
  bind the URL's workspace to the caller's membership.
* **Webhooks** (``app/api/webhooks/``) \u2014 unauthenticated by design, so tenancy
  must come from a verified signature or a bearer token, never the payload.
* **Public routes** \u2014 tenancy must come from an unguessable token or slug.
* **API keys** \u2014 workspace-scoped, and must not widen to the user's other
  workspaces.

The single rule these all share: **the workspace is derived from the
authenticated principal or a verified secret, never from a caller-supplied id.**
Audited 2026-08-28; finding 10.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from fastapi.routing import APIRoute

from app.main import app
from app.services.calls.live_call_registry import LiveCallRegistry
from app.websockets import call_supervisor as cs

OURS = uuid.uuid4()
THEIRS = uuid.uuid4()


def _ws_mock() -> MagicMock:
    ws = MagicMock()
    ws.query_params = {"token": "a-valid-looking-ticket"}
    ws.cookies = {}
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


# ── WebSockets ────────────────────────────────────────────────────────────


async def test_supervisor_socket_cannot_attach_to_another_tenants_live_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dangerous case: the call is real, but belongs to another workspace.

    ``TestEndpointAuth`` already covers a missing token and a call that does not
    exist. Neither reaches the tenancy branch \u2014 an attacker with a valid ticket
    for their *own* workspace supervising somebody else's live call is the real
    risk, because the socket streams live customer audio.

    Auth is stubbed to succeed deliberately: this asserts the workspace binding
    holds *after* authentication, which is exactly the check a valid session
    would otherwise sail past.
    """
    registry = LiveCallRegistry()
    live = MagicMock()
    live.workspace_id = str(THEIRS)
    registry._calls["their-call"] = live

    monkeypatch.setattr(cs, "get_live_call_registry", lambda: registry)

    async def _auth_ok(_ws: Any, _workspace: str, _log: Any) -> bool:
        return True

    monkeypatch.setattr(cs, "_authenticate_websocket", _auth_ok)

    ws = _ws_mock()
    await cs.call_supervisor_endpoint(ws, str(OURS), "their-call")

    # Indistinguishable from a call that does not exist: no audio, no metadata,
    # and not even confirmation that the id is real somewhere else.
    sent = ws.send_json.await_args_list[0].args[0]
    assert sent == {"type": "error", "message": "Call not active"}
    codes = [c.kwargs.get("code") for c in ws.close.await_args_list]
    assert status.WS_1008_POLICY_VIOLATION in codes


async def test_supervisor_socket_attaches_within_the_same_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scoping must not break supervision inside your own workspace."""
    registry = LiveCallRegistry()
    live = MagicMock()
    live.workspace_id = str(OURS)
    live.info.return_value.as_dict.return_value = {"call_id": "our-call"}
    registry._calls["our-call"] = live

    monkeypatch.setattr(cs, "get_live_call_registry", lambda: registry)

    async def _auth_ok(_ws: Any, _workspace: str, _log: Any) -> bool:
        return True

    async def _supervise_noop(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(cs, "_authenticate_websocket", _auth_ok)
    monkeypatch.setattr(cs, "_supervise", _supervise_noop)
    monkeypatch.setattr(cs, "_resolve_operator_user_id", AsyncMock(return_value=1))

    ws = _ws_mock()
    await cs.call_supervisor_endpoint(ws, str(OURS), "our-call")

    sent = ws.send_json.await_args_list[0].args[0]
    assert sent["type"] == "attached"


def test_websocket_auth_binds_the_url_workspace_to_a_membership() -> None:
    """The socket's authenticator must check membership, not just the token.

    A valid JWT proves *who* you are; it does not prove you belong to the
    workspace named in the URL. Asserted on the source because the function
    opens its own database session and closes the socket rather than returning
    a value that could be inspected.
    """
    import inspect

    from app.websockets.voice_test import _authenticate_websocket

    source = inspect.getsource(_authenticate_websocket)
    assert "WorkspaceMembership" in source
    assert "WorkspaceMembership.workspace_id == workspace_id" in source
    assert "WorkspaceMembership.user_id == user_id" in source


# ── Public routes ─────────────────────────────────────────────────────────


def _public_routes() -> list[APIRoute]:
    auth_deps = {
        "get_current_user",
        "get_current_active_user",
        "get_workspace",
        "get_membership",
        "get_active_workspace_membership",
        "get_workspace_admin",
    }

    def dependency_names(route: APIRoute) -> set[str]:
        names: set[str] = set()

        def walk(dependant: object) -> None:
            call = getattr(dependant, "call", None)
            if call is not None:
                names.add(getattr(call, "__name__", ""))
            for child in getattr(dependant, "dependencies", []):
                walk(child)

        walk(route.dependant)
        return names

    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and not (dependency_names(route) & auth_deps)
    ]


# Webhooks legitimately carry a provider-side identifier in the path. The id
# selects *which secret verifies the request*, so a forged one yields a key the
# caller cannot sign for \u2014 it is a lookup, not a tenancy claim.
WEBHOOK_PATH_ID_ROUTES = frozenset({"/webhooks/quo/{workspace_integration_id}"})


def test_no_public_route_takes_a_caller_supplied_workspace_id() -> None:
    """The invariant for every unauthenticated surface.

    A public route naming a workspace in its path or query is the shape most
    likely to be a tenant leak: nothing authenticates the caller, so the id *is*
    the claim unless a signature or an unguessable token proves otherwise.

    All 40+ current public routes key on a token, slug, or public id instead.
    This fails the moment one is added that does not.
    """
    offenders = []
    for route in _public_routes():
        if route.path in WEBHOOK_PATH_ID_ROUTES:
            continue
        params = {p.name for p in route.dependant.path_params} | {
            p.name for p in route.dependant.query_params
        }
        if "workspace_id" in params or "{workspace_id}" in route.path:
            offenders.append(f"{sorted(route.methods or [])} {route.path}")

    assert not offenders, (
        "These unauthenticated routes accept a workspace id from the caller, so "
        "anyone can name any tenant:\n\n"
        + "\n".join(f"  {o}" for o in offenders)
        + "\n\nDerive the workspace from a verified signature, a bearer token, or "
        "an unguessable public token instead."
    )


# ── Webhooks ──────────────────────────────────────────────────────────────


def test_telnyx_webhooks_verify_the_signature_before_parsing() -> None:
    """Order matters: parsing an unverified body is acting on attacker input.

    Telnyx routes derive the workspace from the *phone number row* the message
    arrived on, but that lookup is only trustworthy if the payload is genuine.
    """
    import inspect

    from app.api.webhooks.telnyx_parser import verify_and_parse

    source = inspect.getsource(verify_and_parse)
    verify_line = source.index("verify_telnyx_webhook")
    parse_line = source.index("request.json()")
    assert verify_line < parse_line, "signature must be verified before the body is parsed"


def test_mac_relay_derives_the_tenant_from_the_bearer_token() -> None:
    """The relay's token is the tenancy decision, not anything in the body."""
    import inspect

    from app.api.webhooks import mac_relay

    source = inspect.getsource(mac_relay._authenticate_mac_relay)
    # An unresolvable token must raise, never fall through to a body-derived id.
    assert "HTTP_401_UNAUTHORIZED" in source
    assert "resolve_mac_relay_credential" in source


# ── API keys ──────────────────────────────────────────────────────────────


def test_every_workspace_resolving_dependency_enforces_the_api_key_binding() -> None:
    """An API key for workspace A must not reach workspace B.

    The underlying user is often a member of both, so without this check the key
    silently widens to every workspace they belong to. There are four
    workspace-resolving dependencies and *each* must call the enforcement helper
    \u2014 one that forgets is a privilege-escalation path, so this is asserted per
    function rather than as a file-wide count.
    """
    import inspect

    from app.api import deps

    for name in (
        "get_workspace",
        "get_workspace_admin",
        "get_membership",
        "get_active_workspace_membership",
    ):
        source = inspect.getsource(getattr(deps, name))
        assert "_enforce_api_key_workspace" in source, (
            f"{name} resolves a workspace but never enforces the API key's "
            "workspace binding, so a key issued for one workspace would work "
            "against another."
        )
