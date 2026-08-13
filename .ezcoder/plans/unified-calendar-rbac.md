# One calendar + role-based calendar visibility

## Goal

1. One calendar surface showing **everything** (jobs + appointments), instead of today's two.
2. Users tagged on an entry see **only** their entries; dispatch-and-above see the whole board.
3. Keep "approved quote → scheduled, assigned job" a one-dialog flow.

## What exists today (verified in this checkout)

**The quote → job flow already works end to end.**
`ConvertQuoteDialog` (`frontend/src/components/quotes/convert-quote-dialog.tsx`) posts a schedule window + crew + technician ids;
`QuoteService.convert_quote` (`backend/app/services/quotes/quote_service.py:2927`) atomically creates the job pre-scheduled and pre-assigned, plus the invoice.
Assigned workers read it back via `GET /jobs/calendar/mine` → `JobService.list_for_user`, which resolves login → `Technician` row(s) and matches jobs tagged to them **or** routed to their crew.

**Two calendars, not one.**

| Surface | Shows | Views |
|---|---|---|
| `/calendar` (`calendar-page.tsx`) | appointments only | month + week |
| `/jobs` (`jobs-calendar.tsx`) | jobs only + unscheduled queue | week |

Both are separate `operationsNavItems` entries in `frontend/src/components/layout/app-nav.ts:384-398`.

**Calendar reads are not access-controlled.**

- `GET /jobs` (`backend/app/api/v1/jobs.py:79`) is gated on `WorkspaceAccess` — *any* member. A field technician can read every job in the workspace.
- `GET /appointments` (`backend/app/api/v1/appointments.py:25`) is likewise membership-only.
- The "My jobs" switch on the jobs board is **client-side only** — it swaps which endpoint is called, it enforces nothing.

**Appointments have no link to a login.** `Appointment.bookable_staff_id` → `BookableStaff`, and `BookableStaff` has **no `user_id`** (`backend/app/models/bookable_staff.py:62-99`). Jobs solved this with `Technician.user_id`; appointments never did. Without that column, "show me the appointments I'm tagged on" is unanswerable.

## Privilege boundary

Reuse the existing capability matrix (`backend/app/core/permissions.py`) — no new roles.

| Tier | Roles | Calendar view |
|---|---|---|
| ADMIN / MANAGER (`jobs:write`) | owner, admin, manager, dispatcher | **Unfiltered** — every job + appointment |
| TECH / LEAD / FIELD / SALES | member, lead_technician, technician, sales_rep | **Only entries they're tagged on** |

`jobs:write` is already the exact owner/admin/manager/dispatcher set and already gates every dispatch mutation, so the read boundary lands on the same line as the write boundary.

## Implementation

### 1. Backend — enforce scoping server-side (the security fix)

- `GET /jobs`: resolve caller capability; without `jobs:write`, route the query through the existing `list_for_user` visibility predicate (own technician rows OR their crews) instead of the workspace-wide list. Filters (`status`, `date_from/to`, `business_location_id`) still apply on top.
- `GET /appointments`: same shape — without `jobs:write`, restrict to appointments whose `bookable_staff.user_id` is the caller. No linked staff row → empty list, never an error (mirrors `list_for_user`).
- `GET /jobs/{id}` and `GET /appointments/{id}`: apply the same predicate so a deep link can't bypass the list filter.

### 2. Migration — link bookable staff to a login

- Add `bookable_staff.user_id` (nullable FK → `users.id`, `ON DELETE SET NULL`, indexed), mirroring `technicians.user_id`.
- Additive and nullable: existing rows keep working, existing behaviour for privileged users is unchanged.
- Surface the link in the existing **Settings → Team → member** dialog next to the job-roster toggle, so one screen controls both "can be dispatched" and "can be booked".

### 3. Frontend — merge into one calendar

- `/calendar` becomes the single surface: month + week, rendering **both** appointment chips and job chips, visually distinguished, each opening its existing detail dialog (`AppointmentDetailsDialog` / `JobDetailDialog`).
- Move the **Unscheduled** dispatch queue into the `/calendar` sidebar (jobs with no start date), gated on `jobs:write`.
- Header actions: **New appointment** + **New job**, the latter gated on `jobs:write`.
- Retire `/jobs`: redirect to `/calendar`, preserving the `?job=<id>` deep link the convert flow relies on. Remove the duplicate nav entry; keep `/calendar` in `FIELD_OPERATIONAL_PREFIXES` so field tiers keep access.
- Drop the "My jobs" toggle for restricted users — their view *is* scoped now. Keep it for privileged users as a personal filter.

### 4. Codegen + verification

- `make codegen`, commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit.
- Backend tests: a technician sees only tagged/crew jobs and linked appointments; a dispatcher sees all; deep-link fetch of an untagged entry is refused; unlinked staff → empty, not 500.
- Frontend tests: merged month/week renders both entry types; unscheduled queue and New-job hidden without `jobs:write`.
- Probes: `.ezcoder/eyes/http.sh` against `/api/v1/workspaces/{id}/jobs` and `/appointments` as both tiers; `make ci.all`.

## Steps

1. Add a shared visibility helper in `backend/app/services/jobs/job_service.py` that returns the caller's technician-and-crew predicate, reusing the logic already in `list_for_user`.
2. Scope `GET /jobs` (`backend/app/api/v1/jobs.py:79`) to that predicate whenever the caller lacks `jobs:write`, keeping existing filters applied on top.
3. Scope `GET /jobs/{job_id}` with the same predicate so a deep link cannot bypass the list filter.
4. Write the Alembic migration adding `bookable_staff.user_id` (nullable FK to `users.id`, `ON DELETE SET NULL`, indexed) via `make migrate.new m="link bookable staff to user"`, then `make migrate`.
5. Add `user_id` to the `BookableStaff` model and to its create/update/response schemas in `backend/app/schemas/`.
6. Scope `GET /appointments` and `GET /appointments/{id}` to appointments whose `bookable_staff.user_id` is the caller when the caller lacks `jobs:write`; unlinked callers get an empty list, never an error.
7. Add backend tests: technician sees only tagged/crew jobs and linked appointments, dispatcher sees all, untagged deep link refused, unlinked staff returns empty.
8. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together.
9. Build the merged calendar in `frontend/src/components/calendar/`: render job chips alongside appointment chips in both month and week views, each opening its existing detail dialog.
10. Move the Unscheduled dispatch queue into the `/calendar` sidebar and add the New-job header action, both gated on `jobs:write`.
11. Hide the "My jobs" toggle for callers without `jobs:write` (their view is already scoped); keep it as a personal filter for privileged users.
12. Redirect `/jobs` to `/calendar` preserving `?job=<id>`, remove the duplicate nav entry in `frontend/src/components/layout/app-nav.ts`, and keep `/calendar` in `FIELD_OPERATIONAL_PREFIXES`.
13. Add the bookable-staff login link to the Settings → Team member dialog beside the existing job-roster toggle.
14. Update frontend tests for the merged calendar and the capability gating.
15. Verify with `.ezcoder/eyes/http.sh` against jobs and appointments as both tiers, then run `make ci.all`.

## Risks

- **Behaviour change, intended:** technicians who today see the entire board will stop seeing other people's work. This is the point of the request, but it is visible on day one.
- **Migration touches a live table** — additive/nullable, but `bookable_staff` is production data; back up per the release process.
- **Anyone booked but not linked** (`bookable_staff.user_id IS NULL`) shows no appointments on their own calendar until linked in Team settings — same failure mode the job roster already has.
