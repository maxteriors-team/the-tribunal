# Can a `technician` be given a login safely?

**Audited 2026-08-27.** Question: is the field tier (`technician` → `Tier.FIELD`,
capabilities `jobs:read` + `attendance:use`) actually confined to the jobs
schedule, as `app/core/permissions.py` claims?

**Answer: not yet, but the worst hole is closed.** The capability matrix itself
is sound and its gates work where they are applied. The gap is *coverage*: ~40
workspace surfaces carry no capability gate at all.

**Status 2026-08-27:** finding 1 (the CRM assistant) is fixed. Findings 2–4 are
still open and are pinned as strict `xfail` tests in
`backend/tests/api/test_technician_surface_probe.py`, so each one flips that
suite red the moment it is fixed — the file is the checklist.

## How this was checked

- `CODE` — walked every mounted route's FastAPI dependency tree for a capability
  marker (`required_capabilities` / `read_capability` / `write_capability`),
  a role allow-list, or `get_workspace_admin`. 126 authenticated,
  workspace-scoped routes carried none.
- `CODE` — for each of those, checked whether the handler enforces the role
  itself (`role_can(...)`, `_assert_may_*`). 12 do (members management, workspace
  delete, bookable-staff writes) and are **not** findings.
- `RUNTIME` — drove the real ASGI app as `role="technician"` (the
  `tests/api/test_rbac.py` override pattern) against 45 candidate routes and
  recorded status codes. Controls behaved: `/contacts`, `/quotes`,
  `/reports/ar-aging` returned 403. Everything listed below did not.

False positives dropped during triage: 12 of 45 probed routes (in-handler role
asserts, or 422 body validation firing before an existing check).

## Findings, worst first

### 1. ~~Critical~~ FIXED 2026-08-27 — the CRM assistant ignored the matrix entirely

`POST /api/v1/workspaces/{id}/assistant/chat` depends only on `get_workspace`
(any member). `RUNTIME`: a technician reaches the handler body (500 on the
mocked DB, never 403).

The assistant's tools are the whole CRM: `search_contacts`, `get_contact`,
`update_contact`, `create_contact`, `list_opportunities`, `get_dashboard_stats`,
`send_sms`, `create_campaign`, `start_campaign`, `create_agent`,
`delete_automation`, `create_appointment`
(`app/services/ai/crm_assistant/_tools.py`).

`CODE`: there is **no** `role_can` or `Capability` reference anywhere in
`app/services/ai/crm_assistant/`, and `CRMToolContext`
(`_tool_context.py`) carries only `db`, `workspace_id`, `user_id` — the tool
layer has no role to enforce with.

In plain terms: a technician who is 403 on `GET /contacts` can ask the assistant
for the contact list, the revenue dashboard, or to text a customer, and get it.
Every gate below is reachable through this one route, so it should be fixed
first.

**What was done:**

- `crm_assistant.router` now carries `require_capability(Capability.CRM_READ)`,
  declared on the router so a new assistant endpoint inherits it. Field and
  lead-technician tiers get 403, exactly as on `/contacts`.
- `CRMToolContext` and `CRMToolExecutor` carry the caller's `role`, resolved
  from their membership. `role` is a **required keyword argument** on the
  executor, so a caller that forgets it raises `TypeError` instead of running
  as somebody privileged.
- Every tool is mapped to a capability in `_TOOL_CAPABILITIES`
  (`_tool_metadata.py`), mirroring the gate on the equivalent HTTP route.
  Unmapped tools resolve to `workspace:manage`, so a new tool is admin-gated by
  omission rather than open by omission.
- `tools_for_role()` withholds schemas the caller cannot run, and
  `CRMToolExecutor.execute()` re-checks the capability on every call — before
  the approval gate, so an unauthorized call is never queued for a human to
  rubber-stamp. Schema filtering is the hint; the executor is the control.
- **The SMS path was the same hole.** Texting the workspace number from a
  registered phone routes into `process_assistant_message`
  (`app/services/telephony/inbound_text.py`), so a technician with their number
  on file had the same access by text. That path now resolves the texter's
  membership role and fails closed to the field tier if there is no membership.
- Post-approval execution re-checks the **requester's** capability, recorded in
  `PendingAction.context["role"]` at queue time. Approval clears the approval
  gate, not the caller's authority.

**One deliberate policy call, not a mirror:** appointment writes are mapped to
`jobs:write` because `app/api/v1/appointments.py` has no gate to mirror. Tiers
below dispatch keep booking through the appointments UI, which is untouched.

**Operational note:** pending actions queued *before* this change have no role
in their context and now fail closed on approval. The operator re-asks the
assistant; nothing is lost but the queued request.

### 2. High — workspace financials, prospect data, and outbound spend

No gate in the dependency tree and none in the handler
(`app/api/v1/dashboard.py`, `prospects.py`, `outbound_missions.py`,
`ad_library.py`, `reviews.py`, `pending_actions.py` contain zero `role_can`
calls):

| Surface | What a technician gets | Should be |
|---|---|---|
| `GET /dashboard/stats`, `/dashboard/today-queue` | revenue, campaign, agent metrics | `reports:view` (owner/admin) |
| `POST /prospects/{id}/reveal-phone` \| `reveal-email` | paid enrichment on the owner's account | `crm:write` / `outreach:write` |
| `POST /prospects/search`, `/find-leads-ai/search`, `/ad-library/search` | paid lead sourcing | `outreach:write` |
| `POST /outbound-missions`, `/outbound-missions/{id}/start` | launches outbound telephony/email | `outreach:write` |
| `POST /reviews/requests` | sends SMS to customers | `comms:send` (field tier lacks it by design) |
| `POST /pending-actions/{id}/approve` | approves queued AI actions | `outreach:write` or higher |
| `GET/POST /lead-magnets`, `/referral-partners` | marketing collateral + partner payouts | `outreach:write` |

The spend items matter twice: they are money, and the field tier is deliberately
denied `comms:send` precisely so a technician cannot message customers.

### 3. High — the customer address book via a side door

`GET /service-locations` returns 200 for a technician (`RUNTIME`).
`app/api/v1/field_service.py` has no capability check, so every customer site
address in the workspace is readable — the same data the field tier is 403 on at
`/contacts`. `tests/api/test_rbac.py:598` asserts in a comment that this surface
*is* denied; that comment is wrong, and no test covers it.

`GET /crews`, `/technicians`, `/recurring-jobs` are open on the same router.
Crew/technician rosters are arguably fine for the field tier; the site list is
not.

### 4. Medium — job-adjacent writes with no owner scoping

`DELETE /jobs/{job_id}/time-entries/{entry_id}` reached the handler as a
technician (`RUNTIME` 404, i.e. past authorization to the row lookup). Time
entries are payroll input; nothing checks that the entry belongs to the caller.
`GET /jobs/{id}/materials` and `/jobs/{id}/neighbors` are likewise open, and
`/neighbors` is a lead-generation surface, not an operational one.

### 5. Low — documentation drift

- `Capability.UPSELL_SELL`'s docstring says it is "Granted to every tier
  including `field`"; `_build_matrix()` withholds it from `field`. The code is
  the intended behaviour (a plain technician escalates to a crew lead); the
  comment is stale.
- `appointment_owner_scope` correctly restricts `GET /appointments` to the
  caller's own rows, so that surface is **not** a leak — but the route itself is
  ungated, so the protection rests entirely on that one helper call.

## Not checked

- The frontend mirror (`frontend/src/lib/permissions.ts`) — nav filtering is not
  a control and was out of scope for this pass.
- WebSocket / realtime bridges (`app/websockets/`), public webhook routes, the
  embeddable widget, and API-key (non-session) authentication paths.
- Whether cross-**workspace** isolation holds; this audit only varied the role
  within one workspace.
- Data-layer (row-level) enforcement — every check found here is at the API
  layer, so a future service-layer caller bypasses all of it.

## Suggested order

1. ~~Assistant tool surface (finding 1)~~ — **done 2026-08-27.**
2. ~~Fix the false `/service-locations` comment in `test_rbac.py`~~ — **done.**
3. Dashboard + spend routes (finding 2).
4. `/service-locations` (finding 3).
5. Time-entry ownership (finding 4).
6. Extend `tests/api/test_capability_route_matrix.py` to fail on **any** new
   workspace route that ships without a capability marker, so coverage cannot
   silently regress again.
