# Field-Service Job Scheduler — assign workers to jobs, shown on their calendar

## Reframe (from user feedback)

This is **field-service dispatch**, not a generic async task queue. A *job* is a
unit of field work (a work order). You **tag technicians/crews** to it, give it a
time window, and each assigned worker **sees it on their calendar**. This builds
directly on the Technician/Crew/ServiceLocation models we just added — whose own
docstring already says *"Jobs and visits … are added by the dispatch layer in a
later migration."* The earlier generic-queue interpretation is dropped.

## What already exists (reuse, do not rebuild)

| Capability | Where | How we use it |
|---|---|---|
| `Technician` (optional `user_id` login link), `Crew`, `ServiceLocation` | `app/models/field_service.py` | Jobs are assigned to technicians; a technician's `user_id` is how "see it on **their** calendar" resolves to a signed-in user |
| Workspace-scoped CRUD + tenant-safe reference checks | `app/services/field_service.py` (`assert_workspace_owned`, `_assert_crew_in_workspace`, `_assert_user_is_member`) | Job service mirrors these helpers for contact/location/crew/technician validation |
| Calendar week-grid UI + data hooks | `frontend/src/components/calendar/calendar-page.tsx`, `frontend/src/hooks/useAppointments.ts`, `frontend/src/lib/calendar/calendar-derivations.ts` | The jobs calendar reuses this exact week-grid + query-param/derivation pattern |
| "Assigned to me" precedent | `app/models/human_nudge.py` (`assigned_to_user_id`), appointment `bookable_staff_id` | Model for resolving current user → their work |
| Model/migration conventions (UUID PK, native enum `create_type=False`, partial indexes, `external_source`/`external_id`) | `app/models/field_service.py`, `app/models/appointment.py`, our Jobber migration `b3d8f1a2c4e5` | Job table mirrors these; `external_*` keeps the door open for Jobber job sync |
| Typed FE contract from OpenAPI | `make ci.codegen` → `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` | Regenerate after adding job routes |

## Data model

### `field_service_jobs` table → `app/models/field_service.py` (extends existing module)

- `id` UUID PK (`gen_random_uuid()`), `workspace_id` UUID FK → `workspaces` `ON DELETE CASCADE`.
- `contact_id` int FK → `contacts` `ON DELETE CASCADE` (the customer).
- `service_location_id` UUID FK → `service_locations` `ON DELETE SET NULL`, nullable (the job site).
- `crew_id` UUID FK → `crews` `ON DELETE SET NULL`, nullable — optional **lane/crew** assignment (the dispatch board column).
- `title` String(200), `description` Text nullable.
- `status` native PG enum `field_service_job_status`: `unscheduled`, `scheduled`, `in_progress`, `completed`, `cancelled`.
- `scheduled_start` / `scheduled_end` timestamptz, **nullable** (a job is "queued"/unscheduled until it gets a time window).
- `external_source` / `external_id` String, nullable — provenance for a future Jobber **jobs** sync (consistent with technicians/crews); partial-unique on `(workspace_id, external_source, external_id) WHERE external_id IS NOT NULL`.
- `created_at`, `updated_at`.
- Indexes: `(workspace_id, status)`, `(workspace_id, scheduled_start)` (calendar range scans), `(workspace_id, crew_id)`.

### `field_service_job_assignments` join table (the "tag workers" mechanism)

Many-to-many Job ↔ Technician — a job can have several technicians; a technician has many jobs.

- `id` UUID PK, `job_id` UUID FK → `field_service_jobs` `ON DELETE CASCADE`, `technician_id` UUID FK → `technicians` `ON DELETE CASCADE`.
- `assigned_at` timestamptz default now.
- `UniqueConstraint(job_id, technician_id)` — tagging the same worker twice is a no-op.
- Index `(technician_id)` — the hot path for "jobs assigned to this technician" (calendar).

Relationships: `Job.assignments` / `Job.technicians` (association), `Technician.job_assignments`. Crew assignment stays a scalar `crew_id` on the job (a lane); individual worker tagging is the join table.

## Service layer → `app/services/jobs/job_service.py`

`JobService(db)` — workspace-scoped, mirroring `field_service.py`:

- `list(workspace_id, *, status=None, crew_id=None, technician_id=None, date_from=None, date_to=None)` — calendar/board queries; `date_*` filters on `scheduled_start`.
- `get(job_id, workspace_id)` — tenant-safe 404 via `assert_workspace_owned`.
- `create(workspace_id, data)` — validates contact (and location/crew if given) are in-workspace; status defaults to `unscheduled` (or `scheduled` if a time window is supplied). Optional `technician_ids` tags workers in the same call.
- `update(job_id, workspace_id, data)` — partial; recomputes status when a time window is set/cleared.
- `schedule(job_id, workspace_id, start, end)` — sets the window, flips `unscheduled → scheduled`.
- `assign_technicians(job_id, workspace_id, technician_ids)` / `unassign_technician(...)` — validate each technician is in-workspace (reuse `_assert_*`), upsert/delete join rows idempotently.
- `list_for_user(workspace_id, user_id, *, date_from, date_to)` — **"my calendar"**: resolve `user_id` → their `Technician` row(s) in the workspace → jobs assigned to those technicians (or to the `crew_id` they belong to) within the date range. Returns the same job response shape.

New `app/services/jobs/__init__.py` exports `JobService`.

## Schemas → `app/schemas/job.py`

`JobCreate` (contact_id, optional service_location_id/crew_id/title/description/scheduled_start/scheduled_end/technician_ids), `JobUpdate` (partial), `JobScheduleRequest` (start, end), `JobAssignRequest` (technician_ids), `TechnicianSummary` (id, name, color), `JobResponse` (all columns + `technicians: list[TechnicianSummary]` + derived `status`), `JobListResponse` (items, total). `model_config = {"from_attributes": True}` per repo convention.

## API → `app/api/v1/jobs.py`, mounted in `app/api/v1/router.py`

Prefix `/workspaces/{workspace_id}/jobs` (workspace-membership gated via `get_workspace`, mirroring `appointments.py`):

- `GET ""` — list/filter jobs (status, crew, technician, date range) → board + calendar.
- `POST ""` — create (optionally pre-assigned + scheduled).
- `GET "/{job_id}"`, `PATCH "/{job_id}"`, `DELETE "/{job_id}"`.
- `POST "/{job_id}/schedule"` — set time window.
- `POST "/{job_id}/assignments"` — tag technicians; `DELETE "/{job_id}/assignments/{technician_id}"` — untag.
- `GET "/calendar/mine"` — jobs assigned to **the current user** in `[date_from, date_to]` → "they see it on their calendar." Resolves `current_user` → technician in this workspace.

## Migration

New revision chained off current head `b3d8f1a2c4e5` (our Jobber migration). Create the `field_service_job_status` enum (`create_type=False` + `.create(checkfirst=True)`), `field_service_jobs`, `field_service_job_assignments`, and indexes. Reversible `downgrade` drops tables then enum. Mirror `dlq01a1b2c3d4` / our Jobber migration exactly. **Flag at commit:** if the Jobber migration lands separately, re-point `down_revision` to the real head.

## Frontend → assigned jobs on the calendar

The point of the feature is the worker seeing jobs on a calendar, so the FE is in scope (phased):

1. `frontend/src/hooks/useJobs.ts` — React Query hooks (`useJobs`, `useMyJobsCalendar`, `useCreateJob`, `useAssignTechnicians`, `useScheduleJob`) keyed via `lib/query-keys.ts`, calling the generated client.
2. `frontend/src/lib/jobs/job-derivations.ts` — `jobsForDay`, week-range params, status colors — mirroring `calendar-derivations.ts`.
3. `frontend/src/components/jobs/jobs-calendar.tsx` — reuse the `calendar-page.tsx` week-grid; render jobs in day columns with assigned-technician avatars (color chips) and a status badge; a **"My jobs"** toggle that switches the query to `GET /calendar/mine`.
4. Route `frontend/src/app/jobs/page.tsx` + nav entry in `frontend/src/components/layout/app-nav.ts`.
5. Assign-workers UI: a multi-select of workspace technicians on the job dialog ("tag workers").
6. Run `make ci.codegen`; commit `openapi.json` + `_generated.ts`.

## Non-goals (stay focused)

- **No recurring jobs / RRULE** — single time window per job; recurrence is a later layer.
- **No Cal.com sync for jobs** — jobs are internal dispatch; appointments keep their Cal.com path. (`external_*` columns leave room for Jobber job sync later, not built now.)
- **No drag-and-drop reschedule** in v1 — schedule via dialog/endpoint; DnD is a follow-up.
- **No worker mobile app / push** — assigned worker sees jobs in the existing web calendar surface.
- **No generic async task runner** — explicitly dropped per feedback.

## Risks & mitigations

- **"Their calendar" needs a user↔technician link** — only technicians with `user_id` set see jobs as "mine". The `/calendar/mine` endpoint returns empty (not an error) when the current user has no technician record; the assign UI should surface technician login-link status. Flag this UX dependency.
- **Cross-tenant assignment** — every technician/contact/crew/location reference is validated in-workspace via existing `assert_workspace_owned` / `_assert_*` helpers.
- **Status drift** — status is derived/maintained in one place (`JobService`) on create/update/schedule, not set ad hoc by callers.
- **FE scope is the larger half** — backend is independently shippable and testable; the calendar UI can land as a second commit. Offer to split.

## Verification

- `uv run pytest tests/services/jobs tests/api/test_jobs_api.py` — service CRUD, assign/unassign idempotency, `list_for_user` resolution, cross-workspace 404s, calendar date-range filters (offline-mockable style like `test_lead_sources_api.py`).
- `uv run alembic upgrade head` → `downgrade -1` → `upgrade head`; `\d field_service_jobs` / `\d field_service_job_assignments` confirm columns, enum, indexes.
- `make ci.backend` parity (ruff check + format, mypy strict, coverage).
- `make ci.codegen` — `openapi.json` + `_generated.ts` regenerate cleanly.
- Eyes: `.ezcoder/eyes/http.sh` POST a job, assign a technician, `GET /calendar/mine` as that technician's user → confirm 2xx + the job appears; `GET /readyz` stays 200.
- FE: `npm run lint` + a screenshot of the jobs calendar showing an assigned job in its day column.

## Steps

1. Add `Job` + `JobAssignment` models to `app/models/field_service.py` (enum, FKs, association relationships, indexes, `external_*`); register in `app/models/__init__.py`.
2. Alembic migration off head `b3d8f1a2c4e5`: enum + both tables + indexes; reversible downgrade.
3. `app/schemas/job.py` — create/update/schedule/assign/response/list schemas.
4. `app/services/jobs/job_service.py` + `__init__.py` — workspace-scoped CRUD, schedule, assign/unassign, `list_for_user`.
5. `app/api/v1/jobs.py` + mount in `app/api/v1/router.py`.
6. Backend tests: `tests/services/jobs/test_job_service.py`, `tests/api/test_jobs_api.py`.
7. Migration up/down/up on local Postgres; verify schema via psql; `http.sh` smoke (create → assign → `/calendar/mine`).
8. `make ci.codegen`; commit `openapi.json` + `_generated.ts`.
9. FE hooks (`useJobs.ts`), derivations (`job-derivations.ts`), `jobs-calendar.tsx`, route + nav, assign-workers multi-select.
10. `make ci.frontend` parity; screenshot the jobs calendar.
11. Full `make ci.backend` + `make ci.frontend`; fix findings.
