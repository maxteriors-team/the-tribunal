"""Regression tests for feature-level capability chokepoints.

These tests inspect the dependencies FastAPI actually mounted. That catches the
common regression where a new route keeps workspace membership scoping but omits
the feature's read/write capability gate.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

from app.api.deps import require_route_capabilities
from app.core.permissions import Capability, role_can
from app.main import app
from app.models.workspace import WorkspaceMembership

UNIFORM_ROUTE_POLICIES = {
    # Agent definitions/prompts are workspace configuration. Bookable staff is a
    # scheduling resource and intentionally keeps its narrower jobs policy.
    "/api/v1/workspaces/{workspace_id}/agents/{agent_id}/staff": (
        Capability.JOBS_READ,
        Capability.JOBS_READ,
    ),
    "/api/v1/workspaces/{workspace_id}/agents": (
        Capability.CRM_READ,
        Capability.WORKSPACE_MANAGE,
    ),
    "/api/v1/workspaces/{workspace_id}/suggestions": (
        Capability.CRM_READ,
        Capability.WORKSPACE_MANAGE,
    ),
    "/api/v1/workspaces/{workspace_id}/roleplay": (
        Capability.CRM_READ,
        Capability.CRM_READ,
    ),
    # Outreach authoring and execution surfaces.
    "/api/v1/workspaces/{workspace_id}/automations": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/campaigns": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/pre-booking": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/voice-campaigns": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/drip-campaigns": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/campaign-reports": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/message-tests": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/message-templates": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/email-templates": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/offers": (
        Capability.CRM_READ,
        Capability.OUTREACH_WRITE,
    ),
    # Money and reporting surfaces.
    "/api/v1/workspaces/{workspace_id}/catalog-items": (
        Capability.BILLING_READ,
        Capability.BILLING_WRITE,
    ),
    "/api/v1/workspaces/{workspace_id}/reports": (
        Capability.REPORTS_VIEW,
        Capability.REPORTS_VIEW,
    ),
    "/api/v1/workspaces/{workspace_id}/scorecard": (
        Capability.REPORTS_VIEW,
        Capability.REPORTS_VIEW,
    ),
    "/api/v1/workspaces/{workspace_id}/revenue-targets": (
        Capability.REPORTS_VIEW,
        Capability.WORKSPACE_MANAGE,
    ),
    # Settings sub-routers with a single policy.
    "/api/v1/workspaces/{workspace_id}/api-keys": (
        Capability.WORKSPACE_MANAGE,
        Capability.WORKSPACE_MANAGE,
    ),
    "/api/v1/workspaces/{workspace_id}/nudge-settings": (
        Capability.WORKSPACE_MANAGE,
        Capability.WORKSPACE_MANAGE,
    ),
}

SETTINGS_POLICIES = {
    ("GET", "integrations"): Capability.WORKSPACE_MANAGE,
    ("GET", "team"): Capability.MEMBERS_MANAGE,
    ("GET", "business-hours"): Capability.WORKSPACE_MANAGE,
    ("PUT", "business-hours"): Capability.WORKSPACE_MANAGE,
    ("GET", "proposal-template"): Capability.BILLING_READ,
    ("PUT", "proposal-template"): Capability.BILLING_WRITE,
    ("GET", "pricing"): Capability.BILLING_READ,
    ("PUT", "pricing"): Capability.BILLING_WRITE,
    ("GET", "neighbor-outreach"): Capability.CRM_READ,
    ("PUT", "neighbor-outreach"): Capability.OUTREACH_WRITE,
    ("GET", "post-estimate-followup"): Capability.CRM_READ,
    ("PUT", "post-estimate-followup"): Capability.OUTREACH_WRITE,
    ("GET", "unsold-quote-revival"): Capability.CRM_READ,
    ("PUT", "unsold-quote-revival"): Capability.OUTREACH_WRITE,
    ("GET", "deal-lifecycle"): Capability.CRM_READ,
    ("PUT", "deal-lifecycle"): Capability.PIPELINE_WRITE,
    ("GET", "lead-source-capture"): Capability.CRM_READ,
    ("PUT", "lead-source-capture"): Capability.CRM_WRITE,
    ("GET", "auto-pipeline"): Capability.CRM_READ,
    ("PUT", "auto-pipeline"): Capability.PIPELINE_WRITE,
    ("GET", "attach-rules"): Capability.BILLING_READ,
    ("PUT", "attach-rules"): Capability.BILLING_WRITE,
    ("GET", "call-forwarding"): Capability.COMMS_MANAGE,
    ("PUT", "call-forwarding"): Capability.COMMS_MANAGE,
    ("GET", "speed-to-lead"): Capability.CRM_READ,
    ("PUT", "speed-to-lead"): Capability.OUTREACH_WRITE,
    ("GET", "speed-to-lead/metrics"): Capability.CRM_READ,
    ("GET", "missed-call-textback"): Capability.CRM_READ,
    ("PUT", "missed-call-textback"): Capability.OUTREACH_WRITE,
    ("GET", "card-settings"): Capability.BILLING_READ,
    ("PUT", "card-settings"): Capability.BILLING_WRITE,
}


def _api_routes() -> Iterator[APIRoute]:
    return (route for route in app.routes if isinstance(route, APIRoute))


def _dependency_markers(route: APIRoute) -> list[object]:
    markers: list[object] = []

    def walk(dependant: object) -> None:
        call = getattr(dependant, "call", None)
        if call is not None:
            required = getattr(call, "required_capabilities", None)
            read = getattr(call, "read_capability", None)
            write = getattr(call, "write_capability", None)
            if required is not None:
                markers.append(required)
            if read is not None or write is not None:
                markers.append((read, write))
        for child in getattr(dependant, "dependencies", []):
            walk(child)

    walk(route.dependant)
    return markers


def _route_method(route: APIRoute) -> str:
    methods = route.methods or set()
    assert len(methods) == 1, (route.path, methods)
    return next(iter(methods))


def test_every_uniform_feature_route_has_its_read_write_chokepoint() -> None:
    routes = [
        route
        for route in _api_routes()
        if any(route.path.startswith(prefix) for prefix in UNIFORM_ROUTE_POLICIES)
    ]

    for prefix in UNIFORM_ROUTE_POLICIES:
        assert any(route.path.startswith(prefix) for route in routes), prefix

    for route in routes:
        matching_prefix = max(
            (prefix for prefix in UNIFORM_ROUTE_POLICIES if route.path.startswith(prefix)),
            key=len,
        )
        expected_policy = UNIFORM_ROUTE_POLICIES[matching_prefix]
        assert expected_policy in _dependency_markers(route), (
            route.path,
            route.methods,
            _dependency_markers(route),
        )


def test_every_workspace_settings_route_has_an_explicit_capability() -> None:
    prefix = "/api/v1/settings/workspaces/{workspace_id}/"
    routes = [route for route in _api_routes() if route.path.startswith(prefix)]
    actual_keys = {(_route_method(route), route.path.removeprefix(prefix)) for route in routes}
    assert actual_keys == set(SETTINGS_POLICIES)

    for route in routes:
        key = (_route_method(route), route.path.removeprefix(prefix))
        expected = frozenset({SETTINGS_POLICIES[key]})
        assert expected in _dependency_markers(route), (key, _dependency_markers(route))


def test_billing_read_write_routes_are_gated_but_webhook_stays_public() -> None:
    expected = {
        ("GET", "/api/v1/billing/status"): Capability.BILLING_READ,
        ("POST", "/api/v1/billing/checkout"): Capability.BILLING_WRITE,
        ("POST", "/api/v1/billing/portal"): Capability.BILLING_WRITE,
    }
    routes = {
        (_route_method(route), route.path): route
        for route in _api_routes()
        if route.path.startswith("/api/v1/billing/")
    }

    for key, capability in expected.items():
        assert frozenset({capability}) in _dependency_markers(routes[key])

    webhook = routes[("POST", "/api/v1/billing/webhook")]
    assert not _dependency_markers(webhook)


def test_sensitive_settings_subroutes_are_workspace_admin_only() -> None:
    explicit_paths = {
        "/api/v1/workspaces/{workspace_id}/integrations",
        "/api/v1/workspaces/{workspace_id}/integrations/{integration_type}",
        "/api/v1/workspaces/{workspace_id}/integrations/{integration_type}/test",
        "/api/v1/workspaces/{workspace_id}/reviews/settings",
    }
    routes = [route for route in _api_routes() if route.path in explicit_paths]
    assert routes
    expected = frozenset({Capability.WORKSPACE_MANAGE})
    for route in routes:
        markers = _dependency_markers(route)
        assert (
            expected in markers
            or (
                Capability.WORKSPACE_MANAGE,
                Capability.WORKSPACE_MANAGE,
            )
            in markers
        ), (route.path, route.methods, markers)


@pytest.mark.parametrize(
    ("role", "method"),
    [
        (role, method)
        for role in (
            "owner",
            "admin",
            "manager",
            "dispatcher",
            "sales_rep",
            "member",
            "lead_technician",
            "technician",
        )
        for method in ("GET", "POST")
    ],
)
@pytest.mark.asyncio
async def test_method_gate_enforces_the_eight_role_matrix(role: str, method: str) -> None:
    gate = require_route_capabilities(Capability.CRM_READ, Capability.WORKSPACE_MANAGE)
    request = Request({"type": "http", "method": method, "path": "/", "headers": []})
    membership = cast(WorkspaceMembership, SimpleNamespace(role=role))
    expected_capability = Capability.CRM_READ if method == "GET" else Capability.WORKSPACE_MANAGE

    if role_can(role, expected_capability):
        assert await gate(request, membership) is membership
    else:
        with pytest.raises(HTTPException) as exc_info:
            await gate(request, membership)
        assert exc_info.value.status_code == 403
        assert "permission" in str(exc_info.value.detail).lower()
