# Can a `technician` be given a login safely?

**Audited 2026-08-27.** Question: is the field tier (`technician` → `Tier.FIELD`,
capabilities `jobs:read` + `attendance:use`) actually confined to the jobs
schedule, as `app/core/permissions.py` claims?

**Answer: findings 1-6 are closed.** The capability matrix itself was already
sound; the gap was *coverage* — ~40 workspace surfaces carried no capability
gate at all, so the matrix was not the enforcement point it claimed to be on
those routes.

**Status 2026-08-28:** findings 1-6 fixed, each with an assertion in
`backend/tests/api/test_technician_surface_probe.py` (55 tests, no xfails).
Finding 5 is documentation drift. The remaining ungated routes from the original
sweep have still not been re-triaged one by one — see "What is left". Anything
found later should land in that file as a strict `xfail` carrying its finding
number, so the gap stays visible and the test fails the moment it is closed.

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

### 2. ~~High~~ FIXED 2026-08-27 — workspace financials, prospect data, outbound spend

Six routers had no gate in the dependency tree and none in the handler. Each now
carries a **router-level** capability dependency, so a new endpoint added to any
of them inherits the gate instead of defaulting open:

| Router | Gate applied | Why |
|---|---|---|
| `dashboard.py` | `crm:read` floor; `revenue_stats` + `lead_source_roi_stats` need `reports:view` | the dashboard aggregates the whole CRM, including money |
| `prospects.py` | `outreach:write` | every route is paid people search or per-reveal enrichment |
| `find_leads_ai.py` | `outreach:write` | billed Google Places search plus bulk contact import |
| `ad_library.py` | `outreach:write` | billed provider search; promoting advertisers into contacts |
| `outbound_missions.py` | `outreach:write` | missions launch cold telephony/email at scale |
| `reviews.py` | `crm:read` floor; `POST /requests` needs `comms:send` | review requests text customers |

The spend items matter twice: they are money, and the field tier is deliberately
denied `comms:send` precisely so a technician cannot message customers.

**The revenue split is enforcement of documented policy, not a new product
call.** The matrix docstring already says the manager tier "run[s] operations
(CRM, jobs, billing); **no** reports". So the dollar-denominated blocks are
stripped server-side for anyone without `reports:view` rather than hidden in the
UI — the numbers never leave the process. `deal_coach_stats` deliberately stays:
it is pipeline *risk* triage the sales tier works from daily, not a revenue
report. The frontend cards now accept `null` and the dashboard hides both
shells, so a manager sees a shorter page rather than two empty cards.

Still open on this theme, and **not** fixed here: `POST /pending-actions/{id}/approve`
and `GET/POST /lead-magnets`, `/referral-partners`. They were listed in the
original finding but fall outside the routers named in this pass.

### 3. ~~High~~ FIXED 2026-08-27 — the customer address book via a side door

`GET /service-locations` returned 200 for a technician (`RUNTIME`): every
customer site address in the workspace, the same data the field tier is 403 on
at `/contacts`.

`locations_router` in `app/api/v1/field_service.py` now requires `crm:read`.
Field technicians still get the address for the job they are on — it is embedded
in the job payload as `JobSiteSummary`, scoped to their own assignments, which
`tests/api/test_rbac.py` already pins.

`crews_router` and `technicians_router` were left open on purpose: the crew
roster is not customer data, and a technician may see who else is on their crew.
A test asserts they stay reachable, so the gate cannot creep.

The false comment at `tests/api/test_rbac.py:598` claiming this was already
denied has been corrected.

### 4. ~~Medium~~ FIXED 2026-08-27 — time entries with no owner scoping

`DELETE /jobs/{job_id}/time-entries/{entry_id}` was workspace-scoped only, so a
technician could delete a colleague's payroll hours.

Fixed with object-level scoping rather than a capability gate, because a
technician correcting their *own* entry is routine: `time_entry_owner_scope()`
in `permissions.py` (matching the existing `pipeline_owner_scope` /
`quote_owner_scope` / `appointment_owner_scope` helpers) returns the caller's
user id unless they hold `attendance:manage`. The service applies it as an extra
filter on the lookup, so someone else's entry reads as **404** — its existence
is not disclosed.

Because 404 is the correct answer, a status-code assertion would prove nothing
against a stubbed database; the test asserts the scope helper's decisions and
that the route actually passes the value down.

`GET /jobs/{id}/neighbors` was also named here and is now closed — see finding
6. `GET /jobs/{id}/materials` stays open deliberately: materials consumed on a
job are operational data a technician needs, and the route already redacts unit
costs below `billing:read` via `_can_see_costs()`.

### 5. Low — documentation drift

- `Capability.UPSELL_SELL`'s docstring says it is "Granted to every tier
  including `field`"; `_build_matrix()` withholds it from `field`. The code is
  the intended behaviour (a plain technician escalates to a crew lead); the
  comment is stale.
- `appointment_owner_scope` correctly restricts `GET /appointments` to the
  caller's own rows, so that surface is **not** a leak — but the route itself is
  ungated, so the protection rests entirely on that one helper call.

### 6. High — FIXED 2026-08-28 — the surfaces the first pass named but left open

The first pass listed these as known-open and did not gate them. Each now
carries a capability dependency, and each has a test asserting **both** halves:
the field tier gets 403, and a role that legitimately holds the capability
reaches the handler and gets a real 2xx.

| Surface | Gate | Why |
|---|---|---|
| `lead_magnets.py` (router) | `outreach:write` | public-facing marketing collateral; two routes generate it with billed AI calls |
| `pending_actions.py` (router) | `crm:read` | queued payloads carry contact details and draft message bodies |
| `POST /pending-actions/{id}/approve` | `outreach:write` | deciding whether a queued AI action runs is outreach authority |
| `POST /pending-actions/{id}/reject` | `outreach:write` | clearing another operator's queue is a quieter version of the same harm |
| `GET /jobs/{id}/neighbors` | `crm:read` | see below |

**The neighbour read was defended by a comment that is false.** The route was
deliberately open to any member, reasoning that a technician should see who else
on the street to leave a door hanger with, and that an entry's `label` is "the
site's own name, never the address". The second half does not hold:
`app/services/jobber/mapping.py` names an imported site after its
`address_line1`, so for any workspace migrated from Jobber the label **is** the
street address. Together with `customer_name`, the read returned neighbours'
names and addresses — the same data the field tier is 403 on at `/contacts` and
`/service-locations`, reached through a different door.

That is a real cost to a real workflow: a technician can no longer pull the
door-hanger list themselves. The alternative was redacting `label` and
`customer_name` for callers below `crm:read`, which leaves entries carrying only
a distance and a status — not enough to knock on a door. Restoring the workflow
for the field tier needs a purpose-built payload, not an ungated read.

This is the second time a comment asserting a surface was safe turned out to be
wrong (the first was `/service-locations` in `test_rbac.py`). Both are now
pinned by tests rather than prose.

The approver's gate is **separate from the requester's**: the queued tool
re-checks the role recorded in `PendingAction.context["role"]` at execution
time, so approval clears the approval gate only.

## Not checked

- The frontend mirror (`frontend/src/lib/permissions.ts`) — nav filtering is not
  a control and was out of scope for this pass.
- WebSocket / realtime bridges (`app/websockets/`), public webhook routes, the
  embeddable widget, and API-key (non-session) authentication paths.
- Whether cross-**workspace** isolation holds; this audit only varied the role
  within one workspace.
- Data-layer (row-level) enforcement — every check found here is at the API
  layer, so a future service-layer caller bypasses all of it.

### 7. High — FIXED 2026-08-28 — the full ungated-route sweep

Every earlier pass gated routers a human had *noticed*. This one walked every
mounted route's dependency tree looking for a capability marker, a role
allow-list, a custom dependency that calls `role_can`, or an owner-scope helper.
**50 workspace-scoped routes had none of them.** 19 are now gated; the remaining
31 are open on purpose and listed below.

| Surface | Gate | Why |
|---|---|---|
| `scraping.py` (router) | `outreach:write` | `/search` spends billed Google Places calls, `/import` bulk-creates contacts |
| `nudges.py` (router) | `crm:read` | every nudge carries `contact_name`, `contact_phone`, `contact_company` |
| `call_feedback.py` (router) | `crm:read` | operator commentary on a specific customer call |
| `call_outcomes.py` (router) | `crm:read` | the disposition of a customer conversation; feeds pipeline reporting |
| `referral_partners.py` (router) | `crm:read` | partner name, email, phone, and a link to the CRM contact they already are |
| `GET /integrations/quo/active-line` | `crm:read` | see below |
| `DELETE /jobs/{id}/expenses/{id}` | owner-scoped | see below |

**`/quo/active-line` was the only ungated route in a credentials module** where
every sibling requires `workspace:manage`. It leaks no secret, but passing
`contact_id` returns whether that contact has Quo conversation history — an
existence oracle over the same contacts the field tier is 403 on at
`/contacts`. It takes the lower `crm:read` floor because the messaging UI calls
it as a pre-flight check.

**Job expenses could be deleted by anyone but read by almost nobody.**
`GET /jobs/{id}/expenses` requires `billing:read` with an explicit comment
saying a technician has no use for job costs — while `DELETE` next to it had no
check at all. Recording an expense stays open (a technician logs that a cost
happened, and the response only echoes what they submitted), and undoing their
own is part of that; `job_expense_owner_scope()` confines deletes to the
recorder unless the caller holds `billing:write`. Another member's expense reads
as 404.

#### Considered and deliberately rejected

`POST /appointments/{id}/send-reminder` sends an SMS with no `comms:send` check,
and was gated during this pass. **The gate was reverted**: it broke
`tests/api/test_calendar_scope_api.py`, which pins the opposite intent, and on
reading the route the existing design is coherent. The payload is a *templated*
reminder, for an appointment the caller can already see
(`_calendar_scope_user_id`), rate-limited per user. A technician reminding their
own customer about today's job is the field workflow, not an escape from it.
Both the route and the probe test now carry that reasoning, so the next sweep
argues with it rather than rediscovering it. If the payload ever widens to free
text, the reasoning no longer holds.

#### Left open, with reasons

31 routes. Broadly: the jobs surface (`/jobs`, `calendar/mine`, time entries,
visits, clock-in/out, installation and inventory plans, materials) is the field
tier's actual work; `crews`, `technicians` and `business-locations` are the crew
roster rather than customer data; `recurring-jobs` are schedule templates;
`GET /workspaces/{id}` and `/set-default` are the caller's own workspace and own
preference. `DELETE /workspaces/{id}` checks `role != "owner"` inline — correct,
though it compares a raw string instead of using the matrix. Appointment CRUD
and `invitations` read as ungated to a naive scan but are enforced by
`_calendar_scope_user_id` and `verify_workspace_admin` respectively.

A test pins the operational surfaces as reachable, so a later pass cannot gate
the field tier's own work by reflex.

## What is left

1. ~~Assistant tool surface (finding 1)~~ — **done 2026-08-27.**
2. ~~Fix the false `/service-locations` comment in `test_rbac.py`~~ — **done.**
3. ~~Dashboard + spend routers (finding 2)~~ — **done.**
4. ~~`/service-locations` (finding 3)~~ — **done.**
5. ~~Time-entry ownership (finding 4)~~ — **done.**
6. ~~`/pending-actions/approve`, `/lead-magnets`, `/jobs/{id}/neighbors`
   (finding 6)~~ — **done 2026-08-28.**
7. ~~Re-run the full ungated-route sweep (finding 7)~~ — **done 2026-08-28.**
   17 routers now carry a capability gate.
8. Extend `tests/api/test_capability_route_matrix.py` to fail on **any** new
   workspace route that ships without a capability marker, so coverage cannot
   silently regress again. The 31 justified-open routes above are the seed for
   its allow-list. Router-level dependencies (the pattern used throughout) make
   the check cheap to satisfy. **This is now the last open item.**
9. Still unexamined, and larger than anything above: cross-**workspace**
   isolation, and the non-HTTP surfaces (websockets, webhooks, the embeddable
   widget, API-key auth). Every gate found by this audit lives at the API layer,
   so a service-layer caller bypasses all of them.