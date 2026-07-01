# Replace Jobber with The Tribunal — Gap Analysis & Build Roadmap

## Goal

Make The Tribunal a complete replacement for Jobber for a field-service business:
clients, properties, requests → **quotes → jobs → dispatch → invoices → payment**,
plus the field-team execution loop (time, costing). One system of record. **No
ongoing two-way Jobber sync** — a one-time historical import, then Jobber is retired.

> **Scope note (updated):** a **client-facing proposal page is now shipped** — a
> branded, no-auth `/p/quotes/{token}` view where a client reviews line items and
> **approves/declines online** (public `quotes.public_router` + a per-quote share
> token, mirroring the reviews `public_router`). A full self-service **client hub**
> (login, history, multi-document portal) remains **deferred**. Quote-send emails now
> link straight to the proposal page. Everything else below is operator-facing in the
> Tribunal dashboard.

This document is the program plan. Each phase below is independently shippable
behind the same CI gates (`make ci.all`) and lands on `main` in order. The
`## Steps` section at the end is the concrete execution sequence.

---

## Working agreement (per user feedback — READ FIRST)

**Build one step at a time. Prove each step works before starting the next. Show
it on the UI.** This is a hard rule for every step in this program:

1. **Build** the smallest shippable slice of the step.
2. **Test it** — automated gate appropriate to the change: backend unit/integration
   tests, `make ci.*`, plus a live runtime probe (the `.ezcoder/eyes/` `http.sh` /
   `logs.sh` / `mail.sh` probes) so we catch real behavior, not just type checks.
3. **Show it on the UI** — start the local dev servers and capture a **browser
   screenshot** of the actual feature working in the app (the same way the invoices
   page was verified). Every phase ends with a screenshot of the new capability
   rendered and usable at `http://localhost:3000`.
4. **Stop and confirm** — report the passing tests + the screenshot, and only move
   to the next step after it's confirmed good. No batching multiple phases.

**Definition of done for a step = green tests + a screenshot of it working in the
browser.** If a step can't be shown in the UI on its own (e.g. a backend webhook),
its UI proof is the downstream screen that reflects it (e.g. an invoice flipping to
`paid` in the list). No step is "done" on backend tests alone.

---

## Where things stand today (verified against the code on `main`)

### Already shipped on `main` (Phases 0–6 + 6.5)

The two core modules that were once divergent branches are now **merged, linear, and
live in production**. Verified against `main`: invoices, field service (crews/
technicians/service-locations/**jobs + dispatch**), quotes, catalog, time tracking +
costing, recurring jobs, reporting, workspace roles, and the Stripe payment webhook
all exist under `backend/app/` and `frontend/src/app/` and pass `make ci.all`. The
Alembic graph has a single head; production runs `alembic upgrade head` on deploy.

Historical note: these shipped as `feat/field-service-job-scheduler` (larger base)
with `feat/invoices-domain` rebased on top, which is why the early drafts of this doc
flagged "unmerged branches" as the #1 risk. **That reconciliation (Phase 0) is
complete** — the risk is retired.

### What the field-service branch already gives us (reuse, do not rebuild)

- **Clients' work sites** — `ServiceLocation` model + API.
- **Team** — `Technician` (optional `user_id` login link), `Crew`, workspace **roles**.
- **Jobs / work orders** — `field_service_jobs`: status enum (`unscheduled →
  scheduled → in_progress → completed → cancelled`), nullable time window, crew
  lane, customer link, `external_source/external_id` idempotency columns.
- **Worker assignment** — `field_service_job_assignments` M2M (job ↔ technician).
- **Dispatch board** — `/jobs` week-grid calendar, technician avatar chips, status
  badges, unscheduled "inbox" lane, **"My jobs"** toggle (`/calendar/mine`).
- **`JobService`** — schedule, assign/unassign, `list_for_user` (user → technician → their jobs).
- **Jobber GraphQL client** — real `httpx` client, but **users-only**, **manual CLI**,
  **no OAuth**, **no webhook**, **no scheduled worker**.

### What invoices already gives us

- `invoices` + `invoice_line_items`, computed totals, statuses
  (`draft/sent/paid/partial/void/overdue`), send/void, summary email with Stripe
  "Pay now" link, `create_payment_link` (Stripe Checkout), and a **written but
  UNWIRED** `reconcile_checkout_session` (no Stripe webhook route exists).
- Stripe Checkout infra already exists (`services/payments/call_payment_service.py`).
- Frontend: `/invoices` list + create dialog + quick-action wiring.

### Jobber feature → Tribunal status map

| Jobber capability | Tribunal today | Gap |
|---|---|---|
| Clients (CRM) | ✅ `contacts` | Minor: company-vs-person, multi-property |
| Properties | ✅ `service_locations` (shipped) | Done |
| Requests (inbound) | ✅✅ leads, forms, lead magnets, AI intake | None — Tribunal is *stronger* |
| **Quotes / Estimates** | ✅ **shipped (Phase 3)** | Done; lifecycle automation events wired (Phase 6.5) |
| Price book / catalog | ✅ **shipped (Phase 4)** | Done; line-item picker wired into quotes + invoices |
| Jobs / work orders | ✅ shipped | Done |
| Scheduling / dispatch | ✅ shipped | Done |
| Invoicing | ✅ shipped | Done |
| Online payments | ✅ Stripe webhook wired (Phase 1) | Done; `checkout.session.completed` reconcile is idempotent |
| **Client-facing proposal** | ✅ **shipped** — public `/p/quotes/{token}` view + approve/decline | Full self-service hub still deferred |
| Client comms (SMS/voice/email) | ✅✅ campaigns, nudges, voice AI | None — *far* beyond Jobber |
| Reviews / reputation | ✅ review requests + reputation worker | None |
| Team management | ✅ technicians/crews/roles (shipped) | Done |
| **Time tracking** | ✅ **shipped (Phase 5)** | Done; clock in/out + manual entries |
| **Expenses / job costing** | ✅ **shipped (Phase 5)** | Done; per-job P&L (revenue−labor−expenses) |
| **Recurring jobs / contracts** | ✅ **shipped (Phase 6)** | Done; templates + hourly materializer worker |
| Field mobile experience | ✅ **mobile-responsive (Phase 5)** | Jobs agenda + job detail work at phone width |
| Reporting | ✅ **job P&L + AR aging (Phase 6)** | Done; /reports page (scorecard + ROI still exist) |

**Net:** Phases 0–6 (+6.5 quote automation events) are **shipped on `main`**, plus a
**client-facing proposal page** added on top. The **only remaining roadmap item is the
one-time Jobber data migration (Phase 2)**, which is blocked on a Jobber API token /
export from the user. (A full client self-service hub remains deferred — see scope
note above.)

---

## Architecture decisions (locked for this program)

1. **One system of record.** Tribunal owns clients, jobs, quotes, invoices,
   payments after cutover. Jobber is read-only source for the **one-time import only**.
2. **Money lives in one place.** Quotes and invoices both reuse the existing
   invoice line-item shape and `Decimal` money handling. Stripe is the only
   payment rail. No invoice ever syncs back to Jobber.
3. **Quote approval is via emailed link** (operator-facing dashboard otherwise).
   The deferred client portal would reuse the proven `public_router` + signed-token
   pattern (`offers.py` / reviews; frontend `/p/...` routes) — so adding it later
   needs no rework, but it is **not** built in this roadmap.
4. **Migrations stay linear.** Every phase adds at most one migration, always
   chained off the current real head. Production CRM data is backed up before any
   schema change touching contacts/invoices (per CLAUDE.md).
5. **Codegen discipline.** Every backend contract change → `make ci.codegen`,
   commit `openapi.json` + `_generated.ts`.

---

## Phase 0 — Reconcile onto `main` (FOUNDATION) — ✅ SHIPPED

**Status:** done. Field service + invoices are merged on `main` with a single linear
Alembic head; production migrates cleanly on deploy. The rest of this section is kept
for historical context.

**Why it was first:** nothing could be built "for production" while the two core
modules lived on divergent unmerged branches.

- Create integration branch `feat/field-service-and-invoices` off `main`.
- Land field-service first (it is the larger base: crews/techs/locations/jobs/roles/
  Jobber sync/lead-source ROI), then rebase invoices **on top**, re-pointing the
  invoices migration `down_revision` from `a0e8a88f7801` to the field-service head
  (`c4f9e2b1a7d8`) so history is linear.
- Resolve frontend collisions: nav (`app-nav.ts`), `query-keys.ts`, `types/index.ts`,
  shared UI — both branches touched these.
- Regenerate `openapi.json` + `_generated.ts`.
- Run migration up/down/up on a scratch DB; `make ci.all` green; smoke `/readyz`,
  `/invoices`, `/jobs`.
- Open one PR to `main`. **Exit criteria:** `main` has invoices + dispatch together,
  CI green, dev DB migrates cleanly from `a0e8a88f7801` to the new head.
- **TEST GATE:** `make ci.all` green + `http.sh` 2xx on `/readyz`, `/invoices`, `/jobs`.
- **UI PROOF:** start dev servers; screenshot **both** the `/invoices` list and the
  `/jobs` dispatch board rendering together in one running app. Confirm before Phase 1.

## Phase 1 — Close the payment loop (small, high value) — ✅ SHIPPED

**Status:** done. The signature-verified Stripe webhook is wired and
`reconcile_checkout_session` runs idempotently (`test_billing_webhook_route.py`). A
live `$1` end-to-end payment confirmation on production is tracked separately in the
go-live checklist.

- Add the **Stripe webhook route** (`backend/app/api/webhooks/stripe.py`) with
  signature verification; on `checkout.session.completed`, call the already-written
  `reconcile_checkout_session` (idempotent). Wire into `main.py` / webhooks router.
- Reconcile in-call payments + invoice payments through the same handler (branch on
  Stripe metadata tag).
- Tests: signed payload → invoice flips `sent → paid`, retries are no-ops, bad
  signature → 400. Eyes: replay payload via `http.sh`, confirm logs + status.
- **TEST GATE:** webhook unit tests pass; `http.sh` POST of a signed sample event
  returns 2xx and `logs.sh` shows the reconcile (no traceback).
- **UI PROOF:** in the browser, an invoice that was `sent` shows as **`paid`** in the
  `/invoices` list after the webhook fires (seed → trigger reconcile → screenshot the
  paid badge + amount-paid column). Confirm before Phase 2.
- **Exit:** an emailed invoice's "Pay now" link results in an auto-`paid` invoice.

## Phase 2 — One-time Jobber data migration — ⏳ BLOCKED (needs Jobber token/export)

**Status:** the importer work is the last remaining roadmap item; running it is
blocked on a Jobber API token or `jobber_export.json` from the user.

- Extend the existing Jobber GraphQL client beyond `users`: add `clients`
  (+ `properties`), and `jobs` (with assignments/visits) connections.
- New mapping + importer (mirror `services/jobber/sync.py` idempotency, keyed on
  `external_source='jobber'` + Jobber id, reusing the partial-unique indexes):
  - Jobber **clients → contacts**; client **properties → service_locations**.
  - Jobber **jobs → field_service_jobs** (status mapped; assign technicians by
    previously-synced `external_id`).
  - Jobber **open invoices → invoices** (historical/AR only; do **not** re-bill).
- CLI command(s) with `--dry-run` (rolls back) and per-object summary counts;
  CI/cron-friendly exit codes (same shape as `jobber-sync technicians`).
- Tests on mapping + idempotent re-run; dry-run against a sandbox token.
- **TEST GATE:** mapping tests pass; a `--dry-run` import runs clean and re-running
  the real import creates **zero** duplicates (idempotency proven).
- **UI PROOF:** after a real import into a dev workspace, screenshot imported
  **clients in `/contacts`**, **jobs on the `/jobs` board**, and imported invoices in
  `/invoices` — i.e. real Jobber data visibly living in Tribunal. Confirm before Phase 3.
- **Exit:** a dry-run import reports accurate create/update counts for clients,
  properties, jobs, and open invoices for one workspace.

## Phase 3 — Quotes / Estimates (biggest functional gap) — ✅ SHIPPED

**Status:** done. `quotes` + `quote_line_items`, `QuoteService` (CRUD, send, operator
approve/decline, convert to job+invoice), the `/quotes` UI, **and** a client-facing
`/p/quotes/{token}` proposal page with online approve/decline are all live on `main`.

- `quotes` + `quote_line_items` models (reuse invoice line-item pattern + money
  handling); statuses `draft/sent/approved/declined/expired`; link to contact and
  optional service-location.
- `QuoteService`: CRUD, send (email with view link), operator **approve/decline**
  (mark on the client's behalf from the dashboard), and **convert** → Job and/or →
  Invoice (copies line items; sets `external`/source links so the chain is auditable).
- API router under `/workspaces/{id}/quotes`. (A public client approve/decline token
  route is **deferred with the client portal** — not built here.)
- Frontend: `/quotes` list (status badges), create dialog (line-item editor reused
  from invoices), operator approve/decline, and "Convert to job/invoice" actions.
- Codegen + tests + eyes smoke (create → send → approve → convert).
- **TEST GATE:** `QuoteService` tests (CRUD, approve/decline, convert) + `make
  ci.backend`/`ci.frontend` green; `http.sh` create→send→approve→convert flow 2xx.
- **UI PROOF:** screenshot the `/quotes` page with a quote, then the **converted job
  on `/jobs`** and the **converted invoice on `/invoices`** — the full quote→job→invoice
  chain visible in the UI. Confirm before Phase 4.
- **Exit:** quote can be created, sent, marked approved by the operator, and
  converted into a scheduled job and an invoice.

## Phase 4 — Price book / product & service catalog — ✅ SHIPPED

**Status:** done. `catalog_items` + the shared line-item picker are live.

- `catalog_items` model (name, description, default unit price, taxable, kind
  service/product) workspace-scoped.
- Wire as autocomplete/defaults into quote, invoice, and job line-item editors
  (one shared line-item picker component).
- API + frontend settings page to manage the catalog; codegen + tests.
- **TEST GATE:** catalog CRUD tests + `make ci.*` green; `http.sh` catalog endpoints 2xx.
- **UI PROOF:** screenshot the catalog settings page, then a quote/invoice line-item
  editor **autofilling name+price from a catalog item**. Confirm before Phase 5.
- **Exit:** adding a line item on a quote/invoice can pull name+price from the catalog.

## Phase 5 — Field execution: time tracking + job costing + mobile view — ✅ SHIPPED

**Status:** done. Time entries, job expenses, per-job P&L, and the mobile-responsive
technician views are live.

- `time_entries` (job, technician, start/stop or duration) and `job_expenses`
  (job, amount, category, note) models.
- Job detail gains a **clock in/out** + expense entry; service computes basic
  **job profitability** (revenue from linked invoice − labor − expenses).
- Make the technician **job-detail + "My jobs"** views mobile-responsive (the field
  experience; full native app is out of scope for v1).
- API + frontend + tests + eyes.
- **TEST GATE:** time-entry + expense + profitability service tests pass; `make ci.*`
  green; `http.sh` clock-in/out + expense endpoints 2xx.
- **UI PROOF:** screenshot the **job detail** showing logged time, an expense, and the
  computed **P&L**, plus the mobile-width technician "My jobs" view. Confirm before Phase 6.
- **Exit:** a technician logs time + an expense on a job and the job shows a P&L.

## Phase 6.5 — Automation triggers for billing & field service — ✅ SHIPPED (quotes)

**Status:** the quote lifecycle transitions (`quote_sent/approved/declined/converted`)
now emit automation events (`emit_automation_event` in `QuoteService`). Extending the
same pattern to every invoice/job transition remains additive and optional.

**Original rationale (kept for context):** `emit_automation_event` fires **at transition time, going
forward** — it is not derived from stored rows, so deferring loses nothing except
events on throwaway dev/seed records. **No migration and no backfill** are needed when
this is added later. The change is purely additive and the transition chokepoints
already exist (`send_quote/approve_quote/decline_quote/convert_quote`,
`InvoiceService.send`, job status transitions), so each later needs **one** `emit`
line. Today **no** billing/field-service transition emits automation events; this phase
wires the whole domain **at once** so the event vocabulary is designed coherently
rather than bolted onto quotes alone (avoids naming/payload drift).

- Add event-type + trigger-type constants for the domain in
  `app/services/automations/events.py` and `app/schemas/automation.py`
  (`AUTOMATION_TRIGGER_TYPES`): e.g. `quote_sent`, `quote_approved`, `quote_declined`,
  `quote_converted`, `invoice_sent`, `invoice_paid`, `job_scheduled`, `job_completed`.
- Call `emit_automation_event(...)` inside each transition **within the same
  transaction** (the established pattern from `opportunity_service.py`).
- Define a stable, documented payload per event (ids + minimal context) so automation
  conditions/actions can rely on it.
- Tests: each transition emits exactly one event (idempotent, no double-fire); the
  `automation_worker` matches an active automation on each new `trigger_type`.
- **TEST GATE:** emit tests + worker-match tests pass; `make ci.*` green; `logs.sh`
  shows an event matched and an action dispatched without traceback.
- **UI PROOF:** screenshot an automation configured on a new trigger (e.g. "quote
  approved → notify operator") firing — the resulting nudge/notification visible in the
  app after the transition.
- **Exit:** a quote/invoice/job transition can drive an automation (client/operator
  notification or follow-up) with no schema change required to enable it later.

## Phase 6 — Recurring jobs + reporting polish — ✅ SHIPPED

**Status:** done. Recurring-job templates + the idempotent materializer worker and the
job P&L / AR-aging reporting surfaces are live.

- `recurring_job_templates` (rrule/frequency, default crew/technicians/line items)
  + a worker that materializes upcoming jobs (and optionally invoices) on schedule,
  reusing the in-process worker pattern (`start_all_workers`), idempotent per period.
- Reporting: job P&L summary, dispatch utilization, AR aging — extend existing
  dashboard/scorecard surfaces.
- API + frontend + worker tests + eyes.
- **TEST GATE:** recurrence worker tests (idempotent per period, no double-fire) +
  reporting tests pass; `make ci.all` green; `logs.sh` shows the worker materializing
  a job without error.
- **UI PROOF:** screenshot the recurring-template setup, the **auto-generated next
  job on `/jobs`**, and the **AR aging / job P&L report** rendered in the dashboard.
- **Exit:** a maintenance contract auto-generates its next job; AR aging renders.

---

## Cross-cutting requirements (every phase)

- **One step at a time, each proven before the next** — green tests **and** a browser
  screenshot of the working feature are both required to call a step done.
- Workspace/tenant scoping tests on every new route (no cross-workspace leakage).
- `make ci.all` green; `make ci.codegen` committed when contracts change.
- Back up production before any migration touching `contacts`/`invoices`.
- Eyes probes (`http.sh`, `logs.sh`, `mail.sh`) for runtime verification per CLAUDE.md.
- Money as `Decimal`; never float in persisted financials.

## Risks & mitigations

- **Migration divergence (resolved):** Phase 0 linearized history; `main` has a single
  Alembic head and each new migration chains off it.
- **Double-billing on import:** import Jobber invoices as historical/AR only; never
  trigger sends; Tribunal is sole biller post-cutover.
- **Single-process workers:** recurring-job worker must respect the existing
  single-`backend-api` constraint (no multi-replica double-fire) — leader-guard or
  idempotency per period.
- **Jobber API scope/rate limits:** import is read-only, cursor-paginated, cost-aware
  (client already pins schema version + modest page size).

## Open questions for the user (confirm before/within Phase 0–2)

1. **Cutover style:** hard switch on a date, or run parallel for a few weeks?
2. **History depth:** import all past jobs/invoices, or open/active records only?
3. **Field team size / device:** does mobile-responsive web suffice for v1, or is a
   native app a hard requirement (changes Phase 5 scope significantly)?
4. **Priority after Phase 0:** payments+import first (operational continuity), or
   quotes first (sales motion)? Default below assumes operational-continuity first.

*(Quote-approval channel is settled: emailed link for now; the client portal that
would add self-service approval is deferred.)*

---

## Steps

**Status roll-up (verified against `main`):** Steps 1 and 4–7 (+6.5) are **shipped**;
a **client-facing proposal page** was added on top of Phase 3. **Step 2 (Jobber
import) is the only remaining item** and is blocked on a Jobber token/export. A live
`$1` Stripe payment confirmation on production is tracked in the go-live checklist.

**Every step below follows the same loop: build → run tests → start dev servers and
screenshot the feature working in the browser → report results → wait for the user's
OK → only then start the next step.** Steps are intentionally one phase each so nothing
is batched.

1. **Phase 0 — reconcile onto `main`. ✅ SHIPPED.** Create the integration branch, land
   field-service, rebase invoices on top (re-point the invoices migration to chain
   after the field-service head for linear history), resolve frontend collisions,
   regenerate codegen. **Test:** `make ci.all` green + `http.sh` 2xx on `/readyz`,
   `/invoices`, `/jobs`. **Show:** screenshot `/invoices` and `/jobs` running together.
   Stop and confirm.
2. **Phase 1 — payment webhook. ✅ SHIPPED.** Add the signature-verified Stripe webhook calling
   `reconcile_checkout_session` idempotently. **Test:** webhook unit tests + signed
   `http.sh` replay + `logs.sh` clean. **Show:** screenshot an invoice flipping to
   **`paid`** in the `/invoices` list. Stop and confirm.
3. **Phase 2 — one-time Jobber import. ⏳ BLOCKED (needs Jobber token/export).** Extend the Jobber client (`clients`,
   `properties`, `jobs`) + idempotent `--dry-run` importer. **Test:** mapping tests +
   re-run = zero duplicates. **Show:** screenshot imported clients in `/contacts`,
   jobs on `/jobs`, invoices in `/invoices`. Stop and confirm.
4. **Phase 3 — quotes. ✅ SHIPPED (+ client proposal page).** Models/migration,
   `QuoteService` (CRUD, send, operator approve/decline, convert to job+invoice), API,
   `/quotes` UI, codegen — **plus** a public `/p/quotes/{token}` client proposal page
   (branded, print-friendly) with online approve/decline and a "View your proposal"
   link in the send email.
5. **Phase 4 — price book. ✅ SHIPPED.** `catalog_items` + shared line-item picker. **Test:** catalog
   CRUD tests + `ci.*` green. **Show:** screenshot catalog settings + a line item
   autofilling from the catalog. Stop and confirm.
6. **Phase 5 — time + costing + mobile. ✅ SHIPPED.** `time_entries`, `job_expenses`, profitability,
   mobile-responsive tech view. **Test:** service tests + `ci.*` green + `http.sh`
   clock/expense. **Show:** screenshot job detail with time, expense, P&L + mobile "My
   jobs". Stop and confirm.
6.5. **Phase 6.5 — automation triggers (quotes ✅ SHIPPED; invoice/job additive).** Add
   `quote_*`/`invoice_*`/`job_*` event + trigger types and one `emit_automation_event`
   per transition (no migration, purely additive). **Test:** emit + worker-match tests +
   `ci.*` green + `logs.sh` clean. **Show:** screenshot an automation firing on a new
   trigger (e.g. quote approved → operator notification). Stop and confirm.
7. **Phase 6 — recurring jobs + reporting. ✅ SHIPPED.** `recurring_job_templates` + idempotent
   worker + AR aging / job P&L reports. **Test:** worker idempotency tests + `ci.all`
   green + `logs.sh` clean. **Show:** screenshot the auto-generated next job + the AR
   aging / P&L report in the dashboard. Stop and confirm.

*(Deferred — not in this roadmap: client self-service portal. The `public_router` +*
*`/p/...` pattern it needs already exists, so it can be added later without rework.)*

*(Deferred — additive, no schema change: automation triggers for billing & field*
*service (Phase 6.5). The `emit_automation_event` pipeline + per-transition chokepoints*
*already exist; wiring is one `emit` line per transition whenever we choose to do it.)*
