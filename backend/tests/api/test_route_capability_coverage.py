"""CI gate: a new workspace route may not ship without a capability decision.

Every prior RBAC pass fixed routes that were *already* open
(``docs/technician-role-audit.md``, findings 1-8). Each fix was a point repair;
nothing stopped the next route from landing ungated, and that is exactly how the
50 routes in finding 7 accumulated.

This is the ratchet. It walks the routes FastAPI actually mounted and fails when
a workspace-scoped route enforces nothing — no capability marker, no role
allow-list, no owner-scope helper, no admin dependency, and no inline check.

**The allow-list below is the only escape.** Adding a route to it is a deliberate
statement that the surface is safe for the field tier, written down with the
reason. The assertion is an equality, not a subset, so it fails in both
directions:

* a **new** ungated route fails \u2014 the author must gate it or justify it here;
* a **gated** route still listed here fails \u2014 the entry is stale and must go, so
  the list cannot rot into a list of things nobody has looked at.

Detection deliberately mirrors ``tests/api/test_technician_surface_probe.py``:
that file proves specific routes answer 403 for a technician, this one proves no
route escapes having *an* answer at all.
"""

from __future__ import annotations

import inspect
import re

from fastapi.routing import APIRoute

from app.main import app

# Any of these appearing in a dependency's or handler's source counts as an
# enforcement decision. Deliberately broad: this gate asks "did anyone think
# about authorization here?", not "is the answer correct?". Whether the answer is
# *right* is what the probe suite and the capability matrix test cover.
_ENFORCEMENT_SOURCE = re.compile(
    r"role_can"  # direct matrix check
    r"|_assert_may"  # service-layer assertion helpers
    r"|owner_scope"  # object-level scoping (appointments, time entries, expenses)
    r"|can_assign_workspace_role"
    r"|verify_workspace_admin"  # invitations' custom admin dependency
    r"|Capability\."  # any explicit capability reference
)

_AUTH_DEPENDENCIES = frozenset({"get_current_user", "get_current_active_user"})

# Routes that are workspace-scoped, authenticated, and deliberately enforce
# nothing beyond membership. Every entry was triaged in the 2026-08-28 sweep
# (finding 7). Grouped by the reason they are safe.
JUSTIFIED_UNGATED_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        # ── The caller's own workspace record ─────────────────────────────
        # Reading the workspace you are a member of, and choosing which of your
        # own workspaces is default. DELETE checks ``role != "owner"`` inline
        # (a raw string rather than the matrix, but it is a real check).
        ("GET", "/api/v1/workspaces/{workspace_id}"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}"),
        ("POST", "/api/v1/workspaces/{workspace_id}/set-default"),
        # ── Appointments: scoped by _calendar_scope_user_id, not a gate ────
        # Sales and below see only their own rows; dispatchers and up see the
        # team. Reads and writes both run through that helper, so a capability
        # gate would be redundant and would break the field tier's schedule.
        # send-reminder is covered by its own invariant test (it takes no
        # request body, so it cannot be used to send arbitrary content).
        ("GET", "/api/v1/workspaces/{workspace_id}/appointments"),
        ("POST", "/api/v1/workspaces/{workspace_id}/appointments"),
        ("GET", "/api/v1/workspaces/{workspace_id}/appointments/stats"),
        ("GET", "/api/v1/workspaces/{workspace_id}/appointments/{appointment_id}"),
        ("PUT", "/api/v1/workspaces/{workspace_id}/appointments/{appointment_id}"),
        ("DELETE", "/api/v1/workspaces/{workspace_id}/appointments/{appointment_id}"),
        (
            "POST",
            "/api/v1/workspaces/{workspace_id}/appointments/{appointment_id}/send-reminder",
        ),
        # ── The field tier's actual work ──────────────────────────────────
        # Jobs, visits, time tracking and plans are what a technician is
        # employed to do. Money on a job is separately gated: expense *reads*
        # need billing:read and expense *deletes* are owner-scoped, so what
        # remains open here discloses no cost. Recording an expense only echoes
        # back the amount the caller just submitted.
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/calendar/mine"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/visits"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/materials"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/installation-plan"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/inventory-plan"),
        ("GET", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries"),
        ("POST", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries"),
        ("POST", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/clock-in"),
        ("POST", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/time-entries/clock-out"),
        ("POST", "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/expenses"),
        ("GET", "/api/v1/workspaces/{workspace_id}/recurring-jobs"),
        ("GET", "/api/v1/workspaces/{workspace_id}/recurring-jobs/{template_id}"),
        # ── The crew roster, not customer data ────────────────────────────
        # Who else is on the crew, and which of the company's own locations
        # exist. Customer *sites* are a different surface and DO need crm:read
        # (``/service-locations``, finding 3).
        ("GET", "/api/v1/workspaces/{workspace_id}/crews"),
        ("GET", "/api/v1/workspaces/{workspace_id}/crews/{crew_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/technicians"),
        ("GET", "/api/v1/workspaces/{workspace_id}/technicians/{technician_id}"),
        ("GET", "/api/v1/workspaces/{workspace_id}/business-locations"),
        ("GET", "/api/v1/workspaces/{workspace_id}/business-locations/{location_id}"),
    }
)


def _enforces_authorization(route: APIRoute) -> bool:
    """Whether anything in this route's dependency tree makes an authz decision.

    Checks three shapes, because the codebase uses all three: marker attributes
    set by ``require_capability`` and friends, a role allow-list closure from
    ``require_workspace_roles``, and plain source-level checks in a custom
    dependency (``verify_workspace_admin``) or in the handler itself.
    """
    found = False

    def walk(dependant: object) -> None:
        nonlocal found
        call = getattr(dependant, "call", None)
        if call is not None:
            name = getattr(call, "__name__", "")
            if name == "get_workspace_admin":
                found = True
            if getattr(call, "required_capabilities", None):
                found = True
            if getattr(call, "read_capability", None) or getattr(call, "write_capability", None):
                found = True
            # require_workspace_roles returns a closure over a set of role names.
            if name == "_require" and not getattr(call, "required_capabilities", None):
                for cell in call.__closure__ or ():
                    value = cell.cell_contents
                    if isinstance(value, set) and value and all(isinstance(v, str) for v in value):
                        found = True
            try:
                if _ENFORCEMENT_SOURCE.search(inspect.getsource(call)):
                    found = True
            except (OSError, TypeError):
                pass
        for child in getattr(dependant, "dependencies", []):
            walk(child)

    walk(route.dependant)
    if found:
        return True

    try:
        return bool(_ENFORCEMENT_SOURCE.search(inspect.getsource(route.endpoint)))
    except OSError:
        return False


def _is_authenticated(route: APIRoute) -> bool:
    """Whether the route resolves a logged-in user at all.

    Public surfaces (lead forms, offers, webhooks, the widget) are out of scope
    here: they have no membership to check, and their controls are signature
    verification and rate limiting, audited separately.
    """
    seen: set[str] = set()

    def walk(dependant: object) -> None:
        call = getattr(dependant, "call", None)
        if call is not None:
            seen.add(getattr(call, "__name__", ""))
        for child in getattr(dependant, "dependencies", []):
            walk(child)

    walk(route.dependant)
    return bool(_AUTH_DEPENDENCIES & seen)


def _ungated_workspace_routes() -> set[tuple[str, str]]:
    """Every authenticated workspace route that enforces nothing."""
    ungated: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if "{workspace_id}" not in route.path:
            continue
        if not _is_authenticated(route):
            continue
        if _enforces_authorization(route):
            continue
        for method in route.methods or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            ungated.add((method, route.path))
    return ungated


def test_no_workspace_route_ships_without_an_authorization_decision() -> None:
    """The ratchet. Fails on a new ungated route, and on a stale allow-list entry."""
    ungated = _ungated_workspace_routes()

    unjustified = sorted(ungated - JUSTIFIED_UNGATED_ROUTES)
    assert not unjustified, (
        "These workspace routes enforce no authorization beyond membership, so "
        "any member of the workspace \u2014 including a field technician \u2014 can reach "
        "them:\n\n"
        + "\n".join(f"  {method} {path}" for method, path in unjustified)
        + "\n\nGate the route (see app/api/v1/dashboard.py for the router-level "
        "pattern), or add it to JUSTIFIED_UNGATED_ROUTES in this file with a "
        "comment saying why the field tier may reach it."
    )

    stale = sorted(JUSTIFIED_UNGATED_ROUTES - ungated)
    assert not stale, (
        "These routes are listed as deliberately ungated but now enforce "
        "something (or no longer exist):\n\n"
        + "\n".join(f"  {method} {path}" for method, path in stale)
        + "\n\nRemove them from JUSTIFIED_UNGATED_ROUTES \u2014 a stale entry hides "
        "the next real regression on that path."
    )


def test_the_gate_can_actually_see_an_ungated_route() -> None:
    """Guard the guard: prove the detector is not vacuously passing.

    If a refactor made ``_enforces_authorization`` return ``True`` for
    everything, the test above would pass forever while enforcing nothing. A
    synthetic route with only ``get_current_user`` and no gate must be detected.
    """
    from fastapi import APIRouter, Depends, FastAPI

    from app.api.deps import get_current_user

    probe = FastAPI()
    router = APIRouter()

    @router.get("/api/v1/workspaces/{workspace_id}/probe-unguarded")
    async def _unguarded(workspace_id: str, _user: object = Depends(get_current_user)) -> dict:
        return {}

    probe.include_router(router)
    route = next(r for r in probe.routes if isinstance(r, APIRoute) and "probe" in r.path)

    assert _is_authenticated(route), "detector no longer recognises an authenticated route"
    assert not _enforces_authorization(route), (
        "detector reports enforcement on a route that has none \u2014 "
        "test_no_workspace_route_ships_without_an_authorization_decision is vacuous"
    )


def test_the_gate_recognises_a_real_capability_dependency() -> None:
    """The other half: a genuinely gated route must not be reported as ungated.

    Without this, a detector that returned ``False`` for everything would make
    the allow-list explode and the failure message meaningless.
    """
    gated = [
        r
        for r in app.routes
        if isinstance(r, APIRoute)
        and r.path == "/api/v1/workspaces/{workspace_id}/dashboard/stats"
    ]
    assert gated, "dashboard/stats route not mounted; update this test's anchor"
    assert _enforces_authorization(gated[0])
