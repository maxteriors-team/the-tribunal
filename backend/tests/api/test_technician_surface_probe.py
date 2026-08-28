"""What a `technician` can actually reach over HTTP.

The capability matrix in :mod:`app.core.permissions` says the field tier sees
"the jobs schedule and nothing else". This file is the enforcement test for that
claim: it drives the real ASGI app with an overridden `technician` identity and
asserts each surface answers 403.

Written from the 2026-08-27 audit in ``docs/technician-role-audit.md``, whose
findings 1-4 are all closed as of that date. Any hole found later should land
here as a strict ``xfail`` carrying its finding number, so the gap stays visible
and the test flips to a failure the moment the hole is closed.

The identity is overridden rather than seeded because the point of measurement
is the dependency graph — capability gates run before any handler touches the
database, so a 403 here is the gate firing, and anything else means the request
reached the handler.
"""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    get_active_workspace_membership,
    get_current_user,
    get_db,
    get_membership,
    get_workspace,
)
from app.core.permissions import (
    Capability,
    capabilities_for,
    role_can,
    time_entry_owner_scope,
)
from app.core.roles import WorkspaceRole
from app.main import app
from app.services.ai.crm_assistant._tool_metadata import _TOOL_CAPABILITIES, tool_capability
from app.services.ai.crm_assistant._tools import get_crm_tools, tools_for_role

WORKSPACE_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")

TECHNICIAN = WorkspaceRole.TECHNICIAN.value
LEAD_TECHNICIAN = WorkspaceRole.LEAD_TECHNICIAN.value


@pytest.fixture
def technician_client() -> Iterator[AsyncClient]:
    """An HTTP client authenticated as a plain field technician."""

    async def _user() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=1, is_active=True, email="tech@example.test")

    async def _membership() -> types.SimpleNamespace:
        return types.SimpleNamespace(role=TECHNICIAN, workspace_id=WORKSPACE_ID, user_id=1)

    async def _workspace() -> types.SimpleNamespace:
        return types.SimpleNamespace(
            id=WORKSPACE_ID, is_active=True, settings={}, name="Probe Workspace"
        )

    # A database that answers "no rows" to everything. If a capability gate is
    # missing, the handler runs and returns 200/404/500 off this mock; it never
    # returns 403, which is what the assertions key on.
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = result

    async def _db() -> AsyncIterator[AsyncMock]:
        yield db

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_membership] = _membership
    app.dependency_overrides[get_active_workspace_membership] = _membership
    app.dependency_overrides[get_workspace] = _workspace
    app.dependency_overrides[get_db] = _db
    try:
        yield AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        )
    finally:
        app.dependency_overrides.clear()


async def _status(client: AsyncClient, method: str, suffix: str, body: Any = None) -> int:
    response = await client.request(
        method,
        f"/api/v1/workspaces/{WORKSPACE_ID}{suffix}",
        json=body if body is not None else {},
    )
    return response.status_code


# ── Control: the gates that already worked before the audit ───────────────


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "/contacts"),
        ("POST", "/contacts"),
        ("GET", "/quotes"),
        ("GET", "/reports/ar-aging"),
        ("GET", "/campaigns"),
        ("GET", "/automations"),
        ("GET", "/agents"),
        ("GET", "/offers"),
    ],
)
async def test_technician_is_denied_office_surfaces(
    technician_client: AsyncClient, method: str, suffix: str
) -> None:
    """Baseline. These were correct before this change and must stay correct."""
    async with technician_client as client:
        assert await _status(client, method, suffix) == 403


# ── Finding 1: the CRM assistant (fixed) ──────────────────────────────────


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("POST", "/assistant/chat", {"message": "list every contact and their phone number"}),
        ("POST", "/assistant/chat/stream", {"message": "show me revenue this month"}),
        ("POST", "/assistant/enhance-prompt", {"prompt": "text all my customers"}),
        ("GET", "/assistant/history", None),
        ("GET", "/assistant/conversations", None),
    ],
)
async def test_technician_cannot_reach_the_crm_assistant(
    technician_client: AsyncClient, method: str, suffix: str, body: Any
) -> None:
    """Finding 1: the assistant's tools are the whole CRM.

    Before the fix these routes depended only on ``get_workspace``, so a
    technician who is 403 on ``GET /contacts`` could ask the assistant for the
    contact list instead.
    """
    async with technician_client as client:
        assert await _status(client, method, suffix, body) == 403


def test_field_tiers_are_offered_no_assistant_tools() -> None:
    """A field or lead technician gets an empty tool list, not a filtered one."""
    assert tools_for_role(TECHNICIAN) == []
    assert tools_for_role(LEAD_TECHNICIAN) == []


def test_every_declared_tool_has_an_explicit_capability() -> None:
    """No tool may rely on the admin-only fallback in ``tool_capability``."""
    declared = {tool["function"]["name"] for tool in get_crm_tools()}
    unmapped = sorted(declared - set(_TOOL_CAPABILITIES))
    assert unmapped == [], f"tools missing an explicit capability: {unmapped}"


def test_tool_capability_falls_back_to_admin_only() -> None:
    """An unmapped tool name is admin-gated, so a new tool is closed by default."""
    assert tool_capability("tool_that_does_not_exist") is Capability.WORKSPACE_MANAGE


@pytest.mark.parametrize(
    ("role", "denied_tool"),
    [
        (WorkspaceRole.MEMBER.value, "create_agent"),
        (WorkspaceRole.MEMBER.value, "get_dashboard_stats"),
        (WorkspaceRole.MEMBER.value, "create_campaign"),
        (WorkspaceRole.SALES_REP.value, "create_agent"),
        (WorkspaceRole.SALES_REP.value, "get_dashboard_stats"),
        (WorkspaceRole.MANAGER.value, "get_dashboard_stats"),
        (TECHNICIAN, "search_contacts"),
        (TECHNICIAN, "send_sms"),
    ],
)
def test_mid_tiers_are_not_offered_tools_above_their_capability(
    role: str, denied_tool: str
) -> None:
    """Tool filtering tracks the matrix for every tier, not just the field tier."""
    offered = {tool["function"]["name"] for tool in tools_for_role(role)}
    assert denied_tool not in offered
    assert not role_can(role, tool_capability(denied_tool))


def test_owner_is_offered_every_tool() -> None:
    """The gate must not cost an admin any capability they had before."""
    assert len(tools_for_role(WorkspaceRole.OWNER.value)) == len(get_crm_tools())


async def test_executor_refuses_a_tool_the_role_cannot_run() -> None:
    """The binding check: schema filtering is a hint, the executor is the gate.

    A model that names a tool it was never offered — hallucinated, or replayed
    from earlier context — must still be refused.
    """
    from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor

    executor = CRMToolExecutor(
        db=AsyncMock(),
        workspace_id=WORKSPACE_ID,
        user_id=1,
        role=TECHNICIAN,
    )
    result = await executor.execute("search_contacts", {"query": ""})

    assert result["success"] is False
    assert result["code"] == "not_permitted"


async def test_executor_denies_before_queuing_for_approval() -> None:
    """An unauthorized high-risk call must not reach the human approval queue.

    Otherwise a technician could spam an owner with approval prompts for actions
    the technician was never allowed to request.
    """
    from app.services.ai.crm_assistant import _tool_executor as executor_module

    queued = False

    async def _fail_if_queued(**_kwargs: Any) -> tuple[str, dict[str, Any]]:
        nonlocal queued
        queued = True
        return "pending", {"action_id": str(OTHER_ID)}

    executor = executor_module.CRMToolExecutor(
        db=AsyncMock(),
        workspace_id=WORKSPACE_ID,
        user_id=1,
        role=TECHNICIAN,
    )
    executor_module.approval_gate_service.check_and_execute_or_queue = _fail_if_queued  # type: ignore[method-assign]
    try:
        result = await executor.execute("send_sms", {"contact_id": 1, "message": "hi"})
    finally:
        del executor_module.approval_gate_service.check_and_execute_or_queue  # type: ignore[attr-defined]

    assert result["code"] == "not_permitted"
    assert queued is False


def test_executor_requires_an_explicit_role() -> None:
    """Constructing without a role must fail loudly rather than default open."""
    from app.services.ai.crm_assistant._tool_executor import CRMToolExecutor

    with pytest.raises(TypeError):
        CRMToolExecutor(db=AsyncMock(), workspace_id=WORKSPACE_ID, user_id=1)  # type: ignore[call-arg]


# ── Findings 2-4: fixed 2026-08-27 ────────────────────────────────────────


@pytest.mark.parametrize("suffix", ["/dashboard/stats", "/dashboard/today-queue"])
async def test_technician_cannot_read_dashboard_metrics(
    technician_client: AsyncClient, suffix: str
) -> None:
    """Finding 2: the dashboard aggregates the CRM, including revenue."""
    async with technician_client as client:
        assert await _status(client, "GET", suffix) == 403


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("POST", f"/prospects/{OTHER_ID}/reveal-phone", None),
        ("POST", f"/prospects/{OTHER_ID}/reveal-email", None),
        ("POST", "/prospects/search", {"query": "austin"}),
        ("POST", "/prospects/add-to-mission", {"prospect_ids": []}),
        ("POST", "/find-leads-ai/search", {"query": "roof cleaning austin"}),
        ("POST", "/ad-library/search", {"query": "pressure washing", "country": "US"}),
        ("GET", "/ad-library/advertisers", None),
    ],
)
async def test_technician_cannot_spend_on_prospecting(
    technician_client: AsyncClient, method: str, suffix: str, body: Any
) -> None:
    """Finding 2: paid enrichment and lead sourcing bill the owner per request."""
    async with technician_client as client:
        assert await _status(client, method, suffix, body) == 403


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "/outbound-missions", None),
        ("POST", "/outbound-missions", {"name": "m", "goal": "g"}),
        ("POST", f"/outbound-missions/{OTHER_ID}/start", None),
        ("POST", f"/outbound-missions/{OTHER_ID}/resume", None),
    ],
)
async def test_technician_cannot_run_outbound_missions(
    technician_client: AsyncClient, method: str, suffix: str, body: Any
) -> None:
    """Finding 2: missions launch cold telephony/email at scale."""
    async with technician_client as client:
        assert await _status(client, method, suffix, body) == 403


@pytest.mark.parametrize("suffix", ["/reviews/requests", "/reviews", "/reviews/summary"])
async def test_technician_cannot_reach_reviews(technician_client: AsyncClient, suffix: str) -> None:
    """Finding 2: review requests text customers; the matrix withholds comms:send."""
    method = "POST" if suffix.endswith("requests") else "GET"
    async with technician_client as client:
        status = await _status(client, method, suffix, {"contact_id": 1, "channel": "sms"})
        assert status == 403


def test_review_gate_does_not_cost_the_tiers_that_legitimately_text() -> None:
    """The comms:send gate must not lock out sales or the member tier."""
    assert role_can(WorkspaceRole.SALES_REP.value, Capability.COMMS_SEND)
    assert role_can(WorkspaceRole.MEMBER.value, Capability.COMMS_SEND)


@pytest.mark.parametrize("suffix", ["/service-locations", f"/service-locations/{OTHER_ID}"])
async def test_technician_cannot_read_service_locations(
    technician_client: AsyncClient, suffix: str
) -> None:
    """Finding 3: job sites are customer addresses, the same data as /contacts."""
    async with technician_client as client:
        assert await _status(client, "GET", suffix) == 403


async def test_technician_keeps_the_crew_roster(technician_client: AsyncClient) -> None:
    """The service-location gate must not cost a technician their own roster."""
    async with technician_client as client:
        assert await _status(client, "GET", "/crews") != 403
        assert await _status(client, "GET", "/technicians") != 403


def test_time_entry_edits_are_scoped_to_their_author() -> None:
    """Finding 4: time entries are payroll input, so deletes are owner-scoped.

    Asserted on the scope helper rather than an HTTP status because the correct
    answer for someone else's row is 404 (do not disclose that it exists), which
    a stubbed database returns either way — a status assertion would prove
    nothing here.
    """
    assert time_entry_owner_scope(TECHNICIAN, 7) == 7
    assert time_entry_owner_scope(WorkspaceRole.MEMBER.value, 7) == 7
    assert time_entry_owner_scope(WorkspaceRole.MANAGER.value, 7) == 7
    assert time_entry_owner_scope(WorkspaceRole.OWNER.value, 7) is None
    # Fail closed: an unrecognised role gets the restricted path.
    assert time_entry_owner_scope("legacy_role_from_2019", 7) == 7


async def test_delete_time_entry_applies_the_owner_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 4: the route must pass the scope down, not merely compute it."""
    from app.api.v1 import jobs

    captured: dict[str, Any] = {}

    class _Service:
        def __init__(self, _db: Any) -> None:
            pass

        async def delete_time_entry(self, *_args: Any, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(jobs, "JobCostingService", _Service)
    await jobs.delete_time_entry(
        job_id=OTHER_ID,
        entry_id=OTHER_ID,
        workspace=types.SimpleNamespace(id=WORKSPACE_ID),  # type: ignore[arg-type]
        membership=types.SimpleNamespace(role=TECHNICIAN),  # type: ignore[arg-type]
        current_user=types.SimpleNamespace(id=7),  # type: ignore[arg-type]
        db=AsyncMock(),
    )

    assert captured["restrict_to_user_id"] == 7


# ── The matrix claim these tests exist to defend ──────────────────────────


def test_field_tier_holds_only_operational_capabilities() -> None:
    """``permissions.py`` promises the field tier is jobs-only. Pin it."""
    assert capabilities_for(TECHNICIAN) == frozenset(
        {Capability.JOBS_READ, Capability.ATTENDANCE_USE}
    )
