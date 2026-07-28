"""RBAC enforcement tests for the capability-gated API.

Two layers:

1. **Dependency level** — drive :func:`app.api.deps.require_capability` directly
   with a fabricated membership per role and assert it allows / raises 403. This
   is the exhaustive allow/deny matrix and needs no DB.
2. **Endpoint level** — mount the real app and override ``get_membership`` /
   ``get_current_user`` / ``get_db`` so a chosen role hits real routes. These
   assert the *authorization* outcome only: a denied caller gets exactly 403
   (the gate fires before the handler body), and an allowed caller gets past the
   gate (status is anything but 403). They deliberately do not assert the body's
   eventual success, which would couple the test to service internals.
"""

from __future__ import annotations

import types
import uuid
from collections.abc import AsyncIterator
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    CanManageActiveWorkspace,
    CanManageComms,
    CanManageMembers,
    CanReadBilling,
    CanSendComms,
    CanViewReports,
    CanWriteBilling,
    CanWriteCRM,
    CanWriteOutreach,
    CanWritePipelineOwn,
    get_active_workspace_membership,
    get_current_user,
    get_db,
    get_membership,
    require_active_workspace_capability,
    require_capability,
)
from app.core.permissions import Capability

# ``asyncio_mode = "auto"`` (pyproject) runs async tests without an explicit mark,
# so no module-level pytestmark is needed (and it would wrongly tag sync tests).

WORKSPACE_ID = uuid.uuid4()


def _membership(role: str) -> types.SimpleNamespace:
    """A stand-in WorkspaceMembership; the gate only reads ``.role``/``.workspace_id``."""
    return types.SimpleNamespace(role=role, workspace_id=WORKSPACE_ID, user_id=1)


# --------------------------------------------------------------------------- #
# 1. Dependency-level allow/deny matrix
# --------------------------------------------------------------------------- #
async def _run_gate(capability: Capability, role: str) -> bool:
    """Return True if ``role`` passes ``require_capability(capability)``, else False."""
    dependency = require_capability(capability)
    try:
        await dependency(membership=_membership(role))  # type: ignore[arg-type]
        return True
    except HTTPException as exc:
        assert exc.status_code == 403
        return False


# (capability, roles that MUST pass, roles that MUST be denied)
_MATRIX: list[tuple[Capability, list[str], list[str]]] = [
    # Field technicians (``technician``) are operational-only: no CRM read.
    (Capability.CRM_READ, ["owner", "admin", "manager", "sales_rep", "member"], ["technician"]),
    (Capability.CRM_WRITE, ["owner", "admin", "manager"], ["sales_rep", "technician", "member"]),
    # Outreach authoring (campaigns/segments/automations): sales + operations,
    # but NOT plain members or field technicians.
    (
        Capability.OUTREACH_WRITE,
        ["owner", "admin", "manager", "dispatcher", "sales_rep"],
        ["technician", "member"],
    ),
    # Everyone can see the jobs schedule, including field technicians.
    (
        Capability.JOBS_READ,
        ["owner", "admin", "manager", "dispatcher", "sales_rep", "technician", "member"],
        [],
    ),
    (
        Capability.BILLING_WRITE,
        ["owner", "admin", "manager"],
        ["sales_rep", "technician", "member"],
    ),
    (
        Capability.REPORTS_VIEW,
        ["owner", "admin"],
        ["manager", "dispatcher", "sales_rep", "technician", "member"],
    ),
    (
        Capability.MEMBERS_MANAGE,
        ["owner", "admin"],
        ["manager", "sales_rep", "technician", "member"],
    ),
    (
        Capability.COMMS_SEND,
        ["owner", "admin", "manager", "sales_rep", "member"],
        ["technician"],
    ),
    (
        Capability.COMMS_MANAGE,
        ["owner", "admin"],
        ["manager", "dispatcher", "sales_rep", "technician", "member"],
    ),
    (
        Capability.PIPELINE_WRITE_OWN,
        ["owner", "admin", "manager", "sales_rep"],
        ["technician", "member"],
    ),
    (
        Capability.PIPELINE_WRITE,
        ["owner", "admin", "manager"],
        ["sales_rep", "technician", "member"],
    ),
    # Workspace-level setup (integrations, agents, buying numbers) is owner/admin.
    (
        Capability.WORKSPACE_MANAGE,
        ["owner", "admin"],
        ["manager", "dispatcher", "sales_rep", "technician", "member"],
    ),
]


@pytest.mark.parametrize(("capability", "allowed", "denied"), _MATRIX)
async def test_require_capability_allows_and_denies(
    capability: Capability, allowed: list[str], denied: list[str]
) -> None:
    for role in allowed:
        assert await _run_gate(capability, role) is True, f"{role} should pass {capability}"
    for role in denied:
        assert await _run_gate(capability, role) is False, f"{role} should be denied {capability}"


# --------------------------------------------------------------------------- #
# 1b. Active-workspace gate (routes with no ``workspace_id`` path parameter)
# --------------------------------------------------------------------------- #
async def _run_active_gate(capability: Capability, role: str) -> bool:
    """Return True if ``role`` passes ``require_active_workspace_capability``."""
    dependency = require_active_workspace_capability(capability)
    try:
        await dependency(membership=_membership(role))  # type: ignore[arg-type]
        return True
    except HTTPException as exc:
        assert exc.status_code == 403
        return False


async def test_active_workspace_gate_matches_the_capability_matrix() -> None:
    """The workspace-less gate grades roles exactly like :func:`require_capability`."""
    for role in ("owner", "admin"):
        assert await _run_active_gate(Capability.WORKSPACE_MANAGE, role) is True, role
    for role in ("manager", "dispatcher", "sales_rep", "technician", "member", "bogus_role"):
        assert await _run_active_gate(Capability.WORKSPACE_MANAGE, role) is False, role


async def test_active_workspace_gate_defers_when_user_has_no_workspace() -> None:
    """No membership → no workspace to escalate into; the handler emits its own
    "create a workspace first" error rather than a misleading 403."""
    dependency = require_active_workspace_capability(Capability.WORKSPACE_MANAGE)
    assert await dependency(membership=None) is None


def test_capability_aliases_are_wired() -> None:
    """Each Annotated alias exists and is distinct (guards against copy-paste)."""
    aliases = [
        CanManageActiveWorkspace,
        CanReadBilling,
        CanWriteBilling,
        CanWriteCRM,
        CanWriteOutreach,
        CanWritePipelineOwn,
        CanSendComms,
        CanManageComms,
        CanViewReports,
        CanManageMembers,
    ]
    assert len(aliases) == len({str(a) for a in aliases})


# --------------------------------------------------------------------------- #
# 2. Endpoint-level authorization (real app, overridden identity)
# --------------------------------------------------------------------------- #
def _client_as(role: str) -> AsyncClient:
    """Build an AsyncClient against the real app, authenticated as ``role``."""
    from app.main import app

    async def _user_override() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=1, is_active=True, email="rbac@test.dev")

    async def _membership_override() -> types.SimpleNamespace:
        return _membership(role)

    async def _db_override() -> AsyncIterator[MagicMock]:
        yield MagicMock()

    app.dependency_overrides[get_current_user] = _user_override
    app.dependency_overrides[get_membership] = _membership_override
    # Routes without a ``workspace_id`` path parameter resolve the caller's active
    # workspace instead. The stub deliberately carries no ``is_default`` attribute:
    # a gate that consulted that flag as an authorization signal would blow up here.
    app.dependency_overrides[get_active_workspace_membership] = _membership_override
    app.dependency_overrides[get_db] = _db_override
    # raise_app_exceptions=False: an *allowed* caller reaches the handler body,
    # which then trips over the mocked DB and 500s. We only assert the gate's
    # verdict (403 vs not), so turn that body crash into a 500 response instead
    # of a raised exception.
    return AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    )


def _clear_overrides() -> None:
    from app.main import app

    app.dependency_overrides.clear()


def _url(suffix: str) -> str:
    return f"/api/v1/workspaces/{WORKSPACE_ID}{suffix}"


async def test_reports_are_denied_to_manager_allowed_to_admin() -> None:
    try:
        async with _client_as("manager") as client:
            resp = await client.get(_url("/reports/ar-aging"))
            assert resp.status_code == 403
        async with _client_as("admin") as client:
            resp = await client.get(_url("/reports/ar-aging"))
            assert resp.status_code != 403
    finally:
        _clear_overrides()


async def test_invoice_create_denied_to_tech_and_sales_allowed_to_manager() -> None:
    try:
        for role in ("technician", "sales_rep"):
            async with _client_as(role) as client:
                resp = await client.post(_url("/invoices"), json={})
                assert resp.status_code == 403, role
        async with _client_as("manager") as client:
            resp = await client.post(_url("/invoices"), json={})
            assert resp.status_code != 403
    finally:
        _clear_overrides()


async def test_estimate_render_denied_to_sales_allowed_to_manager() -> None:
    # The AI render spends on the workspace's OpenAI account, so it is billing:write
    # gated like other quote mutations. Proves the route is registered and gated
    # through the real ASGI app (the allowed path then 500s on the mocked DB).
    body = {"image": "data:image/png;base64,AAAA", "mode": "seasonal"}
    try:
        for role in ("technician", "sales_rep"):
            async with _client_as(role) as client:
                resp = await client.post(_url("/quotes/estimate/render"), json=body)
                assert resp.status_code == 403, role
        async with _client_as("manager") as client:
            resp = await client.post(_url("/quotes/estimate/render"), json=body)
            assert resp.status_code != 403
    finally:
        _clear_overrides()


async def test_number_provisioning_is_admin_only() -> None:
    body = {"phone_number": "+15551230000"}
    try:
        for role in ("technician", "manager", "sales_rep"):
            async with _client_as(role) as client:
                resp = await client.post(_url("/phone-numbers/purchase"), json=body)
                assert resp.status_code == 403, role
        async with _client_as("admin") as client:
            resp = await client.post(_url("/phone-numbers/purchase"), json=body)
            assert resp.status_code != 403
    finally:
        _clear_overrides()


async def test_field_technician_is_locked_to_operational_surfaces() -> None:
    """A field technician sees only the jobs schedule; every other CRM surface
    (segments/automations/campaigns/pricing) is denied at the API."""
    denied_reads = [
        "/contacts",
        "/segments",
        "/automations",
        "/campaigns",
        "/catalog-items",  # price book
        "/invoices",
    ]
    try:
        async with _client_as("technician") as client:
            for suffix in denied_reads:
                resp = await client.get(_url(suffix))
                assert resp.status_code == 403, f"technician should be denied GET {suffix}"
            # The jobs schedule (operational) is reachable: the gate lets it
            # through (non-403; the mocked DB may 500 in the handler body).
            resp = await client.get(_url("/jobs"))
            assert resp.status_code != 403
    finally:
        _clear_overrides()


async def test_segments_and_automations_gated_reads_and_outreach_writes() -> None:
    """Reads need crm:read (member+); authoring needs outreach:write (sales+).
    Sales can create outreach but a plain member cannot; field techs get neither."""
    try:
        # Field technician: denied read and write.
        async with _client_as("technician") as client:
            assert (await client.get(_url("/segments"))).status_code == 403
            assert (await client.get(_url("/automations"))).status_code == 403
            assert (await client.post(_url("/segments"), json={})).status_code == 403
        # Member: crm:read → may read, but has no outreach:write → cannot create.
        async with _client_as("member") as client:
            assert (await client.get(_url("/segments"))).status_code != 403
            assert (await client.post(_url("/segments"), json={})).status_code == 403
        # Sales rep: outreach:write → may author outreach…
        async with _client_as("sales_rep") as client:
            assert (await client.post(_url("/segments"), json={})).status_code != 403
            assert (await client.post(_url("/campaigns"), json={})).status_code != 403
        # Manager (crm:write → outreach:write): may create too.
        async with _client_as("manager") as client:
            assert (await client.post(_url("/segments"), json={})).status_code != 403
    finally:
        _clear_overrides()


async def test_sales_cannot_delete_contacts_despite_authoring_outreach() -> None:
    """The outreach:write split must NOT hand sales destructive contact powers:
    delete/bulk-delete stay on crm:write (manager+)."""
    try:
        async with _client_as("sales_rep") as client:
            assert (await client.delete(_url("/contacts/5"))).status_code == 403
            assert (await client.post(_url("/contacts/bulk-delete"), json={})).status_code == 403
        async with _client_as("manager") as client:
            assert (await client.delete(_url("/contacts/5"))).status_code != 403
    finally:
        _clear_overrides()


async def test_onboarding_is_denied_to_non_admin_roles() -> None:
    """Self-serve onboarding is owner/admin only.

    These routes take no ``workspace_id``: they act on the caller's *default*
    workspace, and any member can move their own default with
    ``POST /workspaces/{id}/set-default``. Authentication alone therefore let a
    field technician create an agent in, and overwrite the Cal.com credential of,
    an employer's workspace — and spend the owner's money provisioning a Telnyx
    number. Every route must be gated on ``workspace:manage``.
    """
    csv_upload = {"file": ("leads.csv", b"first_name,phone\nDana,+15125550123\n", "text/csv")}
    onboard_body = {
        "calcom_api_key": "cal_live_injected",
        "calcom_event_type_id": "12345",
        "area_code": "512",
    }
    try:
        for role in ("technician", "member", "sales_rep", "manager", "dispatcher"):
            async with _client_as(role) as client:
                assert (
                    await client.post("/api/v1/onboarding/onboard", json=onboard_body)
                ).status_code == 403, role
                assert (
                    await client.post("/api/v1/onboarding/campaigns", files=csv_upload)
                ).status_code == 403, role
                assert (
                    await client.post(
                        "/api/v1/onboarding/parse-calcom-url",
                        json={"url": "https://cal.com/dana/intro"},
                    )
                ).status_code == 403, role
                assert (
                    await client.get("/api/v1/onboarding/verify-calcom?api_key=cal_live_injected")
                ).status_code == 403, role
        # …and an admin still gets past the gate (the body then trips the mocked DB).
        async with _client_as("admin") as client:
            assert (
                await client.post("/api/v1/onboarding/onboard", json=onboard_body)
            ).status_code != 403
            assert (
                await client.post("/api/v1/onboarding/campaigns", files=csv_upload)
            ).status_code != 403
            assert (
                await client.post(
                    "/api/v1/onboarding/parse-calcom-url",
                    json={"url": "https://cal.com/dana/intro"},
                )
            ).status_code != 403
    finally:
        _clear_overrides()


async def test_texting_a_contact_is_allowed_for_messaging_tiers() -> None:
    body = {"body": "hello", "from_number": "+15551230000"}
    try:
        # Sales/manager/admin (and member) can text customers…
        for role in ("sales_rep", "manager", "admin", "member"):
            async with _client_as(role) as client:
                resp = await client.post(_url("/contacts/5/messages"), json=body)
                assert resp.status_code != 403, role
        # …but a field technician is operational-only and cannot message contacts.
        async with _client_as("technician") as client:
            resp = await client.post(_url("/contacts/5/messages"), json=body)
            assert resp.status_code == 403
    finally:
        _clear_overrides()
