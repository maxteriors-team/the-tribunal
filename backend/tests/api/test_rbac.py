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
    CanManageComms,
    CanManageMembers,
    CanReadBilling,
    CanSendComms,
    CanViewReports,
    CanWriteBilling,
    CanWriteCRM,
    CanWritePipelineOwn,
    get_current_user,
    get_db,
    get_membership,
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
]


@pytest.mark.parametrize(("capability", "allowed", "denied"), _MATRIX)
async def test_require_capability_allows_and_denies(
    capability: Capability, allowed: list[str], denied: list[str]
) -> None:
    for role in allowed:
        assert await _run_gate(capability, role) is True, f"{role} should pass {capability}"
    for role in denied:
        assert await _run_gate(capability, role) is False, f"{role} should be denied {capability}"


def test_capability_aliases_are_wired() -> None:
    """Each Annotated alias exists and is distinct (guards against copy-paste)."""
    aliases = [
        CanReadBilling,
        CanWriteBilling,
        CanWriteCRM,
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


async def test_segments_and_automations_require_crm_capability() -> None:
    """Segments/automations reads need crm:read (member+), writes need crm:write
    (manager+); a field technician is denied both."""
    try:
        async with _client_as("technician") as client:
            assert (await client.get(_url("/segments"))).status_code == 403
            assert (await client.get(_url("/automations"))).status_code == 403
        # Member: crm:read → may read, but not create (needs crm:write).
        async with _client_as("member") as client:
            assert (await client.get(_url("/segments"))).status_code != 403
            assert (await client.post(_url("/segments"), json={})).status_code == 403
        # Manager: crm:write → may create.
        async with _client_as("manager") as client:
            assert (await client.post(_url("/segments"), json={})).status_code != 403
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
