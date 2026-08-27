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

import json
import re
import types
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import (
    CanManageActiveWorkspace,
    CanManageComms,
    CanManageMembers,
    CanReadBilling,
    CanReadQuotes,
    CanSendComms,
    CanViewReports,
    CanWriteBilling,
    CanWriteCRM,
    CanWriteOutreach,
    CanWritePipelineOwn,
    CanWriteQuotes,
    get_active_workspace_membership,
    get_current_user,
    get_db,
    get_membership,
    get_workspace,
    require_active_workspace_capability,
    require_capability,
)
from app.core.permissions import Capability
from app.models.contact import Contact
from app.models.field_service import Job, JobStatus, ServiceLocation, Technician
from app.models.invoice import InvoiceLineItem
from app.models.job_costing import TimeEntry
from app.services.jobs import JobCostingService, JobService

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
        Capability.QUOTES_READ,
        ["owner", "admin", "manager", "dispatcher", "sales_rep"],
        ["technician", "member", "lead_technician"],
    ),
    (
        Capability.QUOTES_WRITE,
        ["owner", "admin", "manager", "dispatcher", "sales_rep"],
        ["technician", "member", "lead_technician"],
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
    # Managing business locations (branches): admin + manager tier (which
    # includes dispatcher). Everyone else may only read the list.
    (
        Capability.LOCATIONS_MANAGE,
        ["owner", "admin", "manager", "dispatcher"],
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
        CanReadQuotes,
        CanWriteBilling,
        CanWriteQuotes,
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


async def test_revenue_targets_are_denied_to_manager_allowed_to_admin() -> None:
    """A month's goal, and the pace against it, read like the P&L: reports:view."""
    try:
        async with _client_as("manager") as client:
            assert (await client.get(_url("/revenue-targets"))).status_code == 403
            assert (await client.get(_url("/revenue-targets/pace"))).status_code == 403
        async with _client_as("admin") as client:
            assert (await client.get(_url("/revenue-targets"))).status_code != 403
            assert (await client.get(_url("/revenue-targets/pace"))).status_code != 403
    finally:
        _clear_overrides()


async def test_setting_a_revenue_target_is_owner_admin_only() -> None:
    """The goal is the owner's commitment, not an operational setting to move."""
    body = {"period_month": "2026-06-01", "revenue_goal": 130000}
    try:
        for role in ("manager", "dispatcher", "sales_rep", "member", "technician"):
            async with _client_as(role) as client:
                resp = await client.put(_url("/revenue-targets"), json=body)
                assert resp.status_code == 403, role
        async with _client_as("admin") as client:
            resp = await client.put(_url("/revenue-targets"), json=body)
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


async def test_invoice_receipt_retry_requires_billing_write() -> None:
    path = f"/invoices/{uuid.uuid4()}/receipt/retry"
    try:
        for role in ("technician", "sales_rep"):
            async with _client_as(role) as client:
                assert (await client.post(_url(path))).status_code == 403, role
        async with _client_as("manager") as client:
            assert (await client.post(_url(path))).status_code != 403
    finally:
        _clear_overrides()


async def test_invoice_manual_payment_requires_billing_write() -> None:
    path = f"/invoices/{uuid.uuid4()}/payments/manual"
    try:
        for role in ("technician", "sales_rep"):
            async with _client_as(role) as client:
                assert (await client.post(_url(path), json={})).status_code == 403, role
        async with _client_as("manager") as client:
            assert (await client.post(_url(path), json={})).status_code != 403
    finally:
        _clear_overrides()


async def test_sales_can_author_quotes_without_billing_access() -> None:
    try:
        async with _client_as("sales_rep") as client:
            assert (await client.get(_url("/quotes"))).status_code != 403
            assert (await client.post(_url("/quotes"), json={})).status_code != 403
        async with _client_as("technician") as client:
            assert (await client.get(_url("/quotes"))).status_code == 403
            assert (await client.post(_url("/quotes"), json={})).status_code == 403
    finally:
        _clear_overrides()


async def test_sensitive_quote_operations_stay_billing_gated() -> None:
    quote_id = uuid.uuid4()
    operations = (
        ("PUT", f"/quotes/{quote_id}/assignment"),
        ("POST", f"/quotes/{quote_id}/record-deposit"),
        ("POST", f"/quotes/{quote_id}/convert"),
        ("POST", "/quotes/estimate/comparison/test-token/send"),
    )
    try:
        async with _client_as("sales_rep") as client:
            for method, suffix in operations:
                response = await client.request(method, _url(suffix), json={})
                assert response.status_code == 403, suffix
        async with _client_as("manager") as client:
            for method, suffix in operations:
                response = await client.request(method, _url(suffix), json={})
                assert response.status_code != 403, suffix
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
        "/quotes",  # sell-side money
        "/opportunities",  # pipeline value
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


@pytest.mark.parametrize(
    ("method", "suffix"),
    [
        ("GET", "/contacts/5/attachments"),
        ("GET", f"/contacts/5/attachments/{uuid.uuid4()}/download"),
        ("POST", "/contacts/5/attachments"),
        ("DELETE", f"/contacts/5/attachments/{uuid.uuid4()}"),
        ("GET", "/contacts/5/companycam-photos"),
    ],
    ids=[
        "attachment-list",
        "attachment-download",
        "attachment-upload",
        "attachment-delete",
        "companycam-photo-read",
    ],
)
async def test_field_technician_is_denied_contact_media_routes(method: str, suffix: str) -> None:
    """Contact media follows the contact book's CRM read/write boundary."""
    from app.main import app

    async def _workspace_override() -> types.SimpleNamespace:
        # These routes use WorkspaceAccess separately from their capability gate.
        # Stub that real dependency so a missing gate reaches the handler body.
        return types.SimpleNamespace(id=WORKSPACE_ID, is_active=True)

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    async def _db_override() -> AsyncIterator[AsyncMock]:
        # A missing media gate should produce a normal handler response, not a
        # mock-induced 500 that could disguise which boundary regressed.
        yield db

    try:
        app.dependency_overrides[get_workspace] = _workspace_override
        async with _client_as("technician") as client:
            # _client_as installs its generic DB override when constructed; replace
            # it before the request with the route-compatible async session above.
            app.dependency_overrides[get_db] = _db_override
            if method == "POST":
                response = await client.post(
                    _url(suffix),
                    files={"file": ("jobsite.jpg", b"image bytes", "image/jpeg")},
                )
            else:
                response = await client.request(method, _url(suffix))
            assert response.status_code == 403, f"technician should be denied {method} {suffix}"
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
    field technician create an agent in an employer's workspace and spend the
    owner's money provisioning a Telnyx number. Every route must be gated on
    ``workspace:manage``.
    """
    csv_upload = {"file": ("leads.csv", b"first_name,phone\nDana,+15125550123\n", "text/csv")}
    onboard_body = {"area_code": "512"}
    try:
        for role in ("technician", "member", "sales_rep", "manager", "dispatcher"):
            async with _client_as(role) as client:
                assert (
                    await client.post("/api/v1/onboarding/onboard", json=onboard_body)
                ).status_code == 403, role
                assert (
                    await client.post("/api/v1/onboarding/campaigns", files=csv_upload)
                ).status_code == 403, role
        # …and an admin still gets past the gate (the body then trips the mocked DB).
        async with _client_as("admin") as client:
            assert (
                await client.post("/api/v1/onboarding/onboard", json=onboard_body)
            ).status_code != 403
            assert (
                await client.post("/api/v1/onboarding/campaigns", files=csv_upload)
            ).status_code != 403
    finally:
        _clear_overrides()


async def test_business_locations_read_open_write_gated() -> None:
    """Any member may read the business-location list (the filter dropdown), but
    only ``locations:manage`` holders (admin + manager) may create one."""
    try:
        # A plain member can read the list but cannot create a branch.
        async with _client_as("member") as client:
            assert (await client.get(_url("/business-locations"))).status_code != 403
            resp = await client.post(_url("/business-locations"), json={"name": "X"})
            assert resp.status_code == 403
        # A field technician cannot even read (no workspace read surface here?).
        # They still resolve membership, so the read gate (plain member) lets
        # them through; only the write is capability-gated.
        async with _client_as("technician") as client:
            resp = await client.post(_url("/business-locations"), json={"name": "X"})
            assert resp.status_code == 403
        # A manager can create (past the gate; the mocked DB may 500 in the body).
        async with _client_as("manager") as client:
            resp = await client.post(_url("/business-locations"), json={"name": "X"})
            assert resp.status_code != 403
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


# --------------------------------------------------------------------------- #
# 3. What rides on the JOB payload for a field technician
#
# A technician needs "what am I doing, and where": site address, customer name
# and phone, access notes, and the scope of work. They must receive **no money**.
# Because the field tier is denied ``/contacts`` and ``/service-locations``
# (crm:read), that data has to be embedded server-side — which makes the job
# payload the place a price could leak. These tests are the guard.
# --------------------------------------------------------------------------- #

# Every money-ish token the technician's payload is grepped for. Matched against
# the raw JSON body (keys *and* values) so a renamed field can't sneak a price
# through.
_MONEY_TOKENS = ("price", "rate", "cost", "amount", "discount", "subtotal", "tax", "currency")


@asynccontextmanager
async def _jobs_client_as(role: str) -> AsyncIterator[AsyncClient]:
    """:func:`_client_as` plus a stub workspace.

    The job routes depend on ``WorkspaceAccess`` as well as the membership, and
    ``get_workspace`` would otherwise hit the mocked DB and 500 before the
    capability gate could return its verdict.
    """
    from app.main import app

    async def _workspace_override() -> types.SimpleNamespace:
        return types.SimpleNamespace(id=WORKSPACE_ID, is_active=True)

    async with _client_as(role) as client:
        app.dependency_overrides[get_workspace] = _workspace_override
        yield client


def _priced_line_item(name: str, description: str | None, quantity: float) -> InvoiceLineItem:
    """A line item whose source row *does* carry money.

    The point of the fixture: the projection has to drop ``unit_price`` /
    ``discount`` / ``total``, so they are deliberately non-zero and distinctive.
    """
    return InvoiceLineItem(
        id=uuid.uuid4(),
        invoice_id=INVOICE_ID,
        name=name,
        description=description,
        quantity=quantity,
        unit_price=425.0,
        discount=10.0,
        total=1234.56,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


INVOICE_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()
SITE_ID = uuid.uuid4()


def _job_with_site_and_customer() -> tuple[Job, list[InvoiceLineItem]]:
    """A transient job graph mirroring what the eager-loaded read path returns."""
    now = datetime.now(UTC)
    contact = Contact(
        id=1349,
        workspace_id=WORKSPACE_ID,
        first_name="Helen",
        last_name="Vasquez",
        email="helen@example.com",
        phone_number="+15125550142",
        lead_score=87,
        notes="Haggled on price last time",
    )
    site = ServiceLocation(
        id=SITE_ID,
        workspace_id=WORKSPACE_ID,
        contact_id=1349,
        name="Helen Vasquez residence",
        address_line1="4412 Ridgeview Dr",
        address_line2=None,
        city="Austin",
        state="TX",
        postal_code="78731",
        country="US",
        access_notes="Gate code 4417. Dog in back yard — leash before starting.",
        latitude=30.3421,
        longitude=-97.7681,
    )
    job = Job(
        id=JOB_ID,
        workspace_id=WORKSPACE_ID,
        contact_id=1349,
        service_location_id=SITE_ID,
        crew_id=None,
        invoice_id=INVOICE_ID,
        title="Soft wash — two-story siding",
        description="Customer requested a call 30 min before arrival.",
        status=JobStatus.SCHEDULED,
        scheduled_start=now,
        scheduled_end=now,
        external_source=None,
        external_id=None,
        created_at=now,
        updated_at=now,
    )
    job.contact = contact
    job.service_location = site
    job.technicians = [
        Technician(
            id=uuid.uuid4(),
            workspace_id=WORKSPACE_ID,
            name="Marco Reyes",
            color="#0ea5e9",
        )
    ]
    line_items = [
        _priced_line_item("Soft wash - two-story siding", "All four elevations", 1.0),
        _priced_line_item("Gutter face brightening", None, 2.0),
    ]
    return job, line_items


def test_job_payload_carries_the_site_and_customer_a_technician_needs() -> None:
    """The site address, access notes, and customer name/phone ride on the job.

    Without this a technician cannot see where the job is: the field tier is 403
    on ``/contacts`` and ``/service-locations``, so the subtitle degraded to
    ``Customer #1349``.
    """
    job, line_items = _job_with_site_and_customer()
    payload = JobService._to_response(job, line_items).model_dump()

    site = payload["service_location"]
    assert site is not None
    assert site["address_line1"] == "4412 Ridgeview Dr"
    assert (site["city"], site["state"], site["postal_code"]) == ("Austin", "TX", "78731")
    assert "Gate code 4417" in site["access_notes"]
    assert (site["latitude"], site["longitude"]) == (30.3421, -97.7681)

    customer = payload["customer"]
    assert customer == {"id": 1349, "name": "Helen Vasquez", "phone_number": "+15125550142"}
    # Name and phone ONLY — the summary must not become a back door onto the
    # contact record for a tier that holds no crm:read.
    assert set(customer) == {"id", "name", "phone_number"}


def test_job_payload_scope_of_work_has_names_and_quantities_but_no_prices() -> None:
    """Line items ride on the job as scope of work, stripped of every money field."""
    job, line_items = _job_with_site_and_customer()
    payload = JobService._to_response(job, line_items).model_dump()

    items = payload["line_items"]
    assert [item["name"] for item in items] == [
        "Soft wash - two-story siding",
        "Gutter face brightening",
    ]
    assert [item["quantity"] for item in items] == [1.0, 2.0]
    assert items[0]["description"] == "All four elevations"
    # The source rows carry unit_price/discount/total; the projection drops them.
    for item in items:
        assert set(item) == {"id", "name", "description", "quantity"}


def _scalars(node: object) -> list[object]:
    """Every leaf value in a decoded payload, at any depth."""
    if isinstance(node, dict):
        return [leaf for value in node.values() for leaf in _scalars(value)]
    if isinstance(node, list):
        return [leaf for value in node for leaf in _scalars(value)]
    return [node]


def test_job_payload_serialized_for_a_technician_contains_no_money_anywhere() -> None:
    """Grep the *raw* serialized body: no money key, at any depth.

    Deliberately a substring scan over the raw JSON rather than a key check, so
    adding a priced field under any name (or nesting a priced sub-object) fails
    here. The source values are then checked as decoded scalars — a substring
    scan would false-positive (``87`` sits inside the postal code ``78731``).
    """
    job, line_items = _job_with_site_and_customer()
    payload = JobService._to_response(job, line_items)
    raw = payload.model_dump_json()

    for token in _MONEY_TOKENS:
        assert not re.search(token, raw, re.IGNORECASE), f"job payload leaked {token!r}: {raw}"

    # No money/CRM value from the source rows survives, under any key name:
    # unit_price, discount, line total, lead score, private notes.
    leaked = set(_scalars(payload.model_dump())) & {425.0, 10.0, 1234.56, 87}
    assert not leaked, f"job payload leaked source values {leaked}"
    assert "Haggled" not in raw


def test_job_payload_tolerates_a_job_with_no_site_invoice_or_line_items() -> None:
    """``service_location_id``/``invoice_id`` are nullable — the common seeded case."""
    now = datetime.now(UTC)
    job = Job(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        contact_id=7,
        service_location_id=None,
        crew_id=None,
        invoice_id=None,
        title="Unscheduled callback",
        description=None,
        status=JobStatus.UNSCHEDULED,
        scheduled_start=None,
        scheduled_end=None,
        external_source=None,
        external_id=None,
        created_at=now,
        updated_at=now,
    )
    job.contact = None
    job.service_location = None
    job.technicians = []

    payload = JobService._to_response(job).model_dump()
    assert payload["service_location"] is None
    assert payload["customer"] is None
    assert payload["line_items"] == []


async def test_technician_calendar_response_is_price_free_over_the_wire() -> None:
    """End-to-end through the real ASGI app: the field tier's calendar carries the
    site/customer/scope and not one money token."""
    from app.api.v1 import jobs as jobs_module

    job, line_items = _job_with_site_and_customer()
    projected = JobService._to_response(job, line_items)

    service = AsyncMock()
    service.list_for_user.return_value = {"items": [projected], "total": 1}

    try:
        with patch.object(jobs_module, "JobService", return_value=service):
            async with _jobs_client_as("technician") as client:
                resp = await client.get(_url("/jobs/calendar/mine"))

        assert resp.status_code == 200
        raw = resp.text
        body = json.loads(raw)
        item = body["items"][0]
        assert item["service_location"]["address_line1"] == "4412 Ridgeview Dr"
        assert item["customer"]["name"] == "Helen Vasquez"
        assert item["customer"]["phone_number"] == "+15125550142"
        assert [li["name"] for li in item["line_items"]] == [
            "Soft wash - two-story siding",
            "Gutter face brightening",
        ]
        # Scan the whole body except the list envelope's row count ("total": 1).
        scanned = raw.replace('"total":1', "").replace('"total": 1', "")
        for token in _MONEY_TOKENS:
            assert not re.search(token, scanned, re.IGNORECASE), f"leaked {token!r}"
    finally:
        _clear_overrides()


# --------------------------------------------------------------------------- #
# 4. Job costs are not readable by the field tier (server-side, not just hidden)
#
# edc79b5 hid rates/labor cost/expenses in the UI only; the payloads still
# carried them, so the network tab defeated it. billing:read is now the single
# boundary for money on a job.
# --------------------------------------------------------------------------- #
def _time_entry(rate: float) -> TimeEntry:
    now = datetime.now(UTC)
    started = datetime(2026, 7, 27, 9, 0, tzinfo=UTC)
    return TimeEntry(
        id=uuid.uuid4(),
        workspace_id=WORKSPACE_ID,
        job_id=JOB_ID,
        technician_id=None,
        started_at=started,
        ended_at=datetime(2026, 7, 27, 12, 0, tzinfo=UTC),
        rate=rate,
        note="Soft wash crew",
        created_at=now,
        updated_at=now,
    )


def test_time_entry_hides_rate_and_labor_cost_below_billing_read() -> None:
    """Hours stay (the tech needs them); the money on them is zeroed."""
    entry = _time_entry(rate=92.5)

    priced = JobCostingService._time_entry_response(entry, include_costs=True)
    assert (priced.rate, priced.labor_cost, priced.duration_hours) == (92.5, 277.5, 3.0)

    redacted = JobCostingService._time_entry_response(entry, include_costs=False)
    assert (redacted.rate, redacted.labor_cost) == (0.0, 0.0)
    # Operational fields survive redaction, so clock in/out still works.
    assert redacted.duration_hours == 3.0
    assert redacted.note == "Soft wash crew"
    assert "92.5" not in redacted.model_dump_json()
    assert "277.5" not in redacted.model_dump_json()


def test_a_rate_submitted_without_billing_read_is_dropped_not_stored() -> None:
    """A technician's clock-in cannot poison the workspace's labour costs."""
    assert JobCostingService._rate_for(999.0, include_costs=False) == 0.0
    assert JobCostingService._rate_for(92.5, include_costs=True) == 92.5


async def test_job_expenses_are_denied_to_the_field_tier() -> None:
    """An expense row is nothing but a cost, so the read is gated outright —
    while a technician may still record that one happened, and time entries
    (money-redacted) stay readable so the timer keeps working."""
    try:
        async with _jobs_client_as("technician") as client:
            assert (await client.get(_url(f"/jobs/{JOB_ID}/expenses"))).status_code == 403
            assert (await client.get(_url(f"/jobs/{JOB_ID}/profitability"))).status_code == 403
            # Not gated: logging time and recording an expense.
            assert (await client.get(_url(f"/jobs/{JOB_ID}/time-entries"))).status_code != 403
            assert (await client.post(_url(f"/jobs/{JOB_ID}/expenses"), json={})).status_code != 403
        # Billing-capable roles keep the full priced view — no dispatcher regression.
        for role in ("dispatcher", "manager", "owner", "admin"):
            async with _jobs_client_as(role) as client:
                assert (await client.get(_url(f"/jobs/{JOB_ID}/expenses"))).status_code != 403, role
                assert (
                    await client.get(_url(f"/jobs/{JOB_ID}/profitability"))
                ).status_code != 403, role
    finally:
        _clear_overrides()


@asynccontextmanager
async def _time_entries_client_as(role: str, entry: TimeEntry) -> AsyncIterator[AsyncClient]:
    """Drive the real ``/time-entries`` route with the real service over one row.

    Everything below the route is genuine — :class:`JobCostingService` and its
    serializer both run — so the only thing under test is whether the *route*
    hands the service the caller's cost visibility. Only the two DB round trips
    are faked: the job-ownership assertion and the row fetch.
    """
    scalars = MagicMock()
    scalars.all.return_value = [entry]
    result = MagicMock()
    result.scalars.return_value = scalars

    db = AsyncMock()
    db.execute.return_value = result

    async def _db_override() -> AsyncIterator[AsyncMock]:
        yield db

    with patch.object(JobCostingService, "_assert_job", AsyncMock(return_value=None)):
        async with _jobs_client_as(role) as client:
            from app.main import app

            app.dependency_overrides[get_db] = _db_override
            yield client


async def test_time_entry_money_is_redacted_by_the_route_not_just_the_serializer() -> None:
    """The field tier and a billing role read the *same* row and see different money.

    ``test_time_entry_hides_rate_and_labor_cost_below_billing_read`` covers the
    serializer in isolation, but the serializer is only ever as good as the
    ``include_costs`` the route passes it — and
    ``JobCostingService.list_time_entries`` defaults that argument to ``True``.
    A route that stopped forwarding the caller's tier would therefore re-leak
    every rate while the unit test stayed green. This drives the HTTP boundary
    to close that gap."""
    try:
        async with _time_entries_client_as("technician", _time_entry(rate=92.5)) as client:
            tech_resp = await client.get(_url(f"/jobs/{JOB_ID}/time-entries"))
        _clear_overrides()
        async with _time_entries_client_as("owner", _time_entry(rate=92.5)) as client:
            owner_resp = await client.get(_url(f"/jobs/{JOB_ID}/time-entries"))

        assert (tech_resp.status_code, owner_resp.status_code) == (200, 200)
        tech_entry = tech_resp.json()[0]
        owner_entry = owner_resp.json()[0]

        # The owner sees what is actually on the row: 3h at $92.50 = $277.50.
        assert (owner_entry["rate"], owner_entry["labor_cost"]) == (92.5, 277.5)
        # The technician reads the same row with the money zeroed…
        assert (tech_entry["rate"], tech_entry["labor_cost"]) == (0.0, 0.0)
        # …and no priced value survives anywhere in the raw body.
        assert not re.search(r"92\.5|277\.5", tech_resp.text), tech_resp.text
        # Hours are operational, not monetary: both tiers keep them so the
        # timer and the payroll export still agree on elapsed time.
        assert tech_entry["duration_hours"] == owner_entry["duration_hours"] == 3.0
    finally:
        _clear_overrides()
