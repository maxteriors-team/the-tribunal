# Sales KPI view, quote→pipeline automation, and an automation kill switch

Covers three stacked asks:

1. A reporting view with the 5 most important sales KPIs, including **conversion** and **appointment show-up rate**.
2. Sent quotes should **automatically enter the pipeline**, with the flexibility to **remove them**.
3. **Or** a specific **tag that turns the automations off**.

---

## What already exists (do not rebuild)

Investigation turned up far more infrastructure than the asks imply. This is mostly wiring, not net-new.

| Surface | State | File |
|---|---|---|
| `/reports` + `/reports/sales` pages, nav entries, `reports:view` permission | Shipped | `frontend/src/app/reports/`, `frontend/src/components/layout/app-nav.ts:254-267` |
| Sales report: avg job value, attach rate, close rate, 3 breakdowns, date-range picker, delta-vs-previous-window | Shipped | `frontend/src/components/reports/sales-performance-report.tsx` |
| KPI display discipline: rates null-not-zero, denominators captioned, low-sample flag, points-not-percent deltas | Shipped, high quality | `frontend/src/components/reports/sales-performance-metrics.ts` |
| `show_up_rate` computation (overall / by agent / by campaign) | Shipped | `backend/app/services/appointments/appointment_service.py:35,240-311` |
| `GET /appointments/stats` | Shipped | `backend/app/api/v1/appointments.py:86` |
| `show_up_rate_30d` on dashboard, null under 5 outcomes | Shipped | `backend/app/services/dashboard/dashboard_service.py:488` |
| `PUT /appointments/{id}` accepting `status` | Shipped | `backend/app/schemas/appointment.py:28` |
| Automation event bus + `EVENT_QUOTE_SENT` emitted on first send | Shipped | `backend/app/services/automations/events.py:49`, `quote_service.py:1010` |
| `no_show` automation trigger, `noshow_reengagement_worker` | Shipped | `backend/app/workers/noshow_reengagement_worker.py` |
| Tag system with `add_tag_to_contact` | Shipped | `backend/app/services/tags/tag_service.py:62` |
| `delete_opportunity` | Shipped | `backend/app/services/opportunities/opportunity_service.py:503` |
| `Quote Sent / Follow Up` pipeline stage | Shipped (this month's restructure) | `backend/app/services/opportunities/default_pipeline.py:47` |

---

## Blocking finding: show-up rate has no in-app writer

**Nothing in the product can mark a customer as attended or absent.**

`AppointmentStatus.COMPLETED` / `NO_SHOW` are written in exactly one place: the Cal.com
`meeting_ended` webhook (`backend/app/api/webhooks/calcom_handlers.py:677-723`). There is no
button, no worker, and no bulk action anywhere else.

Production, verified against the live database today:

```
appointments: 4 total — all status='scheduled' (2 already in the past)
completed: 0    no_show: 0    contacts with noshow_count>0: 0
```

The dashboard suppresses the rate under 5 decided outcomes, so **show-up rate renders `—`
today and would keep rendering `—` after I build the KPI card.** Shipping a headline KPI
that is structurally incapable of showing a number is worse than not shipping it.

This also means three shipped features are starved by the same gap: the `no_show` automation
trigger, `noshow_reengagement_worker`, and `contacts.noshow_count` all wait on a status only
Cal.com ever sets.

**Recommendation: add an in-app attendance control.** Reject the alternative of
auto-completing appointments N hours after `scheduled_at` — that manufactures a permanent
100% show-up rate, which is exactly the invented-proof failure mode the existing report code
goes out of its way to avoid.

One correctness trap: the Cal.com path also writes `last_appointment_status`, increments
`noshow_count`, and applies the `no-show` / `showed-up` tags. An in-app path that only sets
`appointments.status` would leave manually-marked no-shows invisible to the automation trigger
and the re-engagement worker. Both paths must share one helper.

---

## The 5 KPIs

Chosen as a funnel plus the money, so the view answers "where is it leaking" not just "what did we sell":

| # | KPI | Definition | Source |
|---|---|---|---|
| 1 | **Conversion rate** | Contacts created in window that reached a won deal ÷ contacts created in window | new |
| 2 | **Appointment show-up rate** | `completed ÷ (completed + no_show)` | existing, unblocked by attendance capture |
| 3 | **Quote close rate** | `approved ÷ (approved + declined + expired)` | existing `SalesPerformanceReport.close_rate` |
| 4 | **Average job value** | Mean approved quote total | existing `avg_job_value` |
| 5 | **Revenue won** | Sum of approved quote totals | existing `revenue_approved` |

Attach rate stays in the report body (it is already rendered in the breakdown tables), demoted
from the headline row to make space.

Every KPI reuses the existing `sales-performance-metrics.ts` contract: null when the
denominator is empty, denominator captioned underneath, low-sample flagged, deltas in points.

Conversion needs a stated cohort or it is not a fact. It cohorts on **contact creation date**
and counts a won deal at any later time, matching how the quote report already cohorts on
creation and counts the decision whenever it lands. Recent windows will therefore understate
conversion; the caption must say so.

### Stale-status caveat

`_expire_overdue` only runs on quote read paths (`quote_service.py:795,876,1116,1209`) — there
is no sweeper worker. A quote past `expiry_date` stays `sent` in the database until somebody
loads a quote list. Verified live: `QUO-000003` expired 2026-08-02 and is still `sent` 3 days
later. A report that queries quotes directly would compute close rate off stale statuses.
The report service must call `_expire_overdue` (or apply the same date predicate in SQL)
before aggregating.

---

## Quote sent → pipeline

Wire into `_ensure_sent_state`'s existing `if not already_sent:` branch
(`quote_service.py:1009`) so it fires **once**, on first send, in the transaction that
commits the send.

Deliberately **not** routed through the automation engine: `emit_automation_event` defaults to
`require_active_automation=True`, so it drops the event unless the operator has already built a
matching automation. The user asked for this to happen by default, so it is a direct service
call mirroring `open_lead_opportunity`.

Behavior, in a new `backend/app/services/opportunities/quote_opportunity.py`:

- Contact has an **open** opportunity → move it to `Quote Sent / Follow Up`, set probability from the stage, log an activity, emit `EVENT_DEAL_STAGE_CHANGED`.
- Contact has **no** open opportunity → create one directly in `Quote Sent / Follow Up` (this is the "should also automatically be going into a pipeline" half of the ask).
- Already in `Quote Sent / Follow Up` or a later stage → no-op, never move a deal backwards.
- Gated by a new `auto_pipeline.on_quote_sent` flag, **default on**.

`auto_pipeline.enabled` stays a separate, default-**off** flag. It governs raw *inbound leads*
and was deliberately flipped to opt-in this month; a sent quote is a far stronger buying
signal and earns a card on its own terms.

---

## Two off-switches

The user asked for removal flexibility **or** a tag. Both get built — they solve different problems.

**Per-deal removal (retroactive).** `delete_opportunity` already exists; the migration
precedent for a softer removal is `status='abandoned'` + `is_active=false`. Expose "Remove from
pipeline" on the opportunity card, and make removal *sticky*: a removed card must not be
recreated by the next quote send, otherwise the button appears broken.

**`no-automation` tag (preventive).** A reserved contact tag that suppresses automated
outreach and automated pipeline movement for that contact. Gate it at `emit_automation_event`
— every event carries `contact_id`, so it is the one choke point that covers all 16 event
triggers at once — plus the direct quote→pipeline call, which does not pass through the bus.
Manual operator actions are never blocked; this suppresses *automation*, not the operator.

---

## Risks

- **`emit_automation_event` is a hot path.** Adding a tag lookup costs a query per emit. Needs an indexed `EXISTS` and a check that it runs only after the existing `_has_active_listener` short-circuit, so workspaces with no automations pay nothing.
- **Conversion is a new aggregate over `contacts`** (1,832 rows in prod, will grow fastest of any table). Needs an index-backed query and a real EXPLAIN before it goes on a page that loads by default.
- **Retroactive pipeline cards.** This only affects quotes sent *after* deploy. The 11 existing quotes stay where they are; no backfill unless asked.
- **Prod data is thin** (4 appointments, 11 quotes, 33 opportunities). Most KPIs will legitimately render `—` or low-sample. That is correct behavior, not a bug, and the empty states matter more than the populated ones here.
- **Codegen.** Backend schema changes require `make codegen` and committing `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit. A new required field on a shared TS type breaks existing test fixtures — this bit PR #50 last week; grep fixtures before assuming green.

---

## Verification

- Backend unit tests per service; each new behavior proven failing before the fix.
- `.ezcoder/eyes/http.sh` against `/api/v1/reports/sales-kpis`, `/appointments/{id}`, and a quote send, confirming status codes and response shape.
- Seed a local workspace with enough appointments/quotes to cross the low-sample threshold, so the populated KPI state is seen rendered and not just unit-tested.
- Screenshot desktop + narrow for the KPI row in both empty and populated states.
- `make ci.all` green before PR.

---

## Steps

1. Extract the shared attendance side-effects from `backend/app/api/webhooks/calcom_handlers.py:701-724` into a reusable helper (tag, `last_appointment_status`, `noshow_count`), and call it from both the Cal.com webhook and `AppointmentService.update_appointment` so in-app and webhook marking behave identically.
2. Add backend tests proving an in-app `PUT /appointments/{id}` to `no_show` applies the `no-show` tag, sets `last_appointment_status`, and increments `noshow_count` exactly once (idempotent on re-marking).
3. Add an "Attended / No-show" control to the appointment UI for appointments whose `scheduled_at` has passed, wired to the existing `PUT /appointments/{id}`, with optimistic update and error rollback.
4. Add a `conversion_rate` aggregate (contacts created in window that reached a won deal ÷ contacts created in window) to the sales-performance service, returning `None` when the denominator is empty, with its denominator exposed for the caption.
5. Ensure the sales report aggregates over fresh statuses by running the `_expire_overdue` sweep (or an equivalent SQL date predicate) before computing close rate.
6. Extend `SalesPerformanceReport` in `backend/app/schemas/reporting.py` with `conversion_rate`, its sample size, and the appointment show-up rate + its `completed`/`no_show` counts, then run `make codegen`.
7. Build the 5-KPI headline row in `frontend/src/components/reports/sales-performance-report.tsx` reusing `formatRate`/`describeDelta`/`describeSample`/`isLowSample`, demoting attach rate to the breakdown body, and grep existing test fixtures for newly-required generated fields before running CI.
8. Add frontend tests covering each KPI's empty (`—`), low-sample, and populated states, and confirm no KPI coerces null to zero.
9. Create `backend/app/services/opportunities/quote_opportunity.py` that moves an open opportunity to `Quote Sent / Follow Up`, creates one there when none exists, no-ops when already at or past that stage, logs an activity, and emits `EVENT_DEAL_STAGE_CHANGED`.
10. Call it from `QuoteService._ensure_sent_state` inside the existing `if not already_sent:` branch, gated on a new `auto_pipeline.on_quote_sent` setting defaulting to on, and surface that setting in the existing `/auto-pipeline` settings endpoint and UI.
11. Add backend tests for the quote→pipeline behavior: first send creates/moves, re-send is a no-op, a later-stage deal is never moved backwards, and the setting disables it.
12. Make pipeline removal sticky so a removed deal is not recreated by a subsequent quote send, and expose "Remove from pipeline" on the opportunity card with a confirm step.
13. Add a reserved `no-automation` contact tag and gate `emit_automation_event` on it, after the existing `_has_active_listener` short-circuit, using an indexed `EXISTS` query.
14. Gate the direct quote→pipeline call on the same `no-automation` tag, since it bypasses the event bus, and add tests proving a tagged contact triggers neither automations nor pipeline movement while manual operator actions still work.
15. Expose the `no-automation` tag in the contact UI with copy stating exactly what it suppresses.
16. Verify end to end with `.ezcoder/eyes/http.sh` against the KPI, appointment, and quote-send endpoints; seed enough local data to cross the low-sample threshold; capture desktop and narrow screenshots of the KPI row in empty and populated states.
17. Run `make ci.all`, confirm green, then open a PR.
