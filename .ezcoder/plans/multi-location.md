# Multi-Location (Business Units) — one workspace, many branches

## Goal

Let one workspace ("the business") run **multiple physical locations/branches** with a
**shared customer database and shared logins**, plus the ability to **filter and roll up**
jobs, appointments, and staff by location. This is ServiceTitan's "Business Unit" model,
built lean — no settings swamp.

Chosen over "workspace-per-location" (Path A) because the user wants *one* CRM with shared
customers, not separate books.

## Key finding from research (naming — read first)

`ServiceLocation` (`backend/app/models/field_service.py`) **already exists** but means a
**customer's job site** (their address), NOT a business branch. To avoid collision, the new
entity is **`BusinessLocation`** (table `business_locations`, API `/business-locations`,
UI label **"Locations"**). Every plan reference to "location" below = the business branch.

## Architecture at a glance

- New workspace-owned entity `BusinessLocation` (name, address, timezone, business hours,
  active flag, optional phone number). Mirrors the existing `Crew`/`Technician` CRUD shape in
  `field_service.py` exactly (router + `ServiceErrorRoute` + service + schemas).
- Everything operational gets an **optional** `business_location_id` FK (nullable =
  "unassigned / all locations"), added incrementally so each stage ships alone and no existing
  row/behavior breaks.
- Filtering is additive: new optional `business_location_id` query params on list endpoints and
  a frontend location dropdown. Default (no filter) = today's behavior.
- The final stage extends the RBAC we just built with **location-scoped memberships** (a manager
  pinned to one branch) — optional and last because it's the riskiest.

## Staged delivery (each stage is independently shippable + verifiable)

### Stage 1 — Foundation: the BusinessLocation entity (no behavior change elsewhere)
Adds the entity, CRUD API, and a Settings management screen. Nothing else references it yet, so
it is pure addition.

- **Model** `backend/app/models/field_service.py`: add `BusinessLocation(Base)` — `id` (uuid pk),
  `workspace_id` (FK CASCADE, indexed), `name` (String 200, not null), `is_active`
  (bool, default true, server_default), timezone (`String(64)`, default `"UTC"`),
  `business_hours` (`JSONB`, default dict), plain-text address fields
  (`address_line1/line2/city/state/postal_code`, `country` String(2) default "US"),
  `phone` (String(50), nullable), `created_at`/`updated_at`. Unique constraint
  `(workspace_id, name)`; index `(workspace_id, is_active)`. Address is business (not customer)
  data → plain text, unlike `ServiceLocation`.
- **Relationship**: add `business_locations` relationship to `Workspace`
  (`backend/app/models/workspace.py`) + the `TYPE_CHECKING` import.
- **`backend/app/models/__init__.py`**: export `BusinessLocation`.
- **Migration** `make migrate.new m="add business_locations"`: create table. Chain from current
  head (`alembic heads`). Down-migration drops the table.
- **Schemas** `backend/app/schemas/field_service.py`: `BusinessLocationCreate`,
  `BusinessLocationUpdate`, `BusinessLocationResponse`, `BusinessLocationListResponse`
  (mirror the `Crew*` schemas).
- **Service** `backend/app/services/field_service/`: add `BusinessLocationService` with
  `list/create/get/update/delete` mirroring `CrewService` (use `select_workspace_owned` /
  `assert_workspace_owned`; raise domain NotFound/Conflict). Export from the package `__init__`.
- **Capability** `backend/app/core/permissions.py`: add `LOCATIONS_MANAGE = "locations:manage"`;
  grant to admin (auto) + manager. Reads use existing membership (any member) so the filter
  dropdown works for everyone. Add dep alias `CanManageLocations` in `backend/app/api/deps.py`.
- **Router** `backend/app/api/v1/field_service.py`: add `business_locations_router` with
  list (member read) + create/update/delete (gated `CanManageLocations`) + get. Register in
  `backend/app/api/v1/router.py` under `/workspaces/{workspace_id}/business-locations`.
- **Codegen**: `make codegen`; commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
- **Frontend**: `frontend/src/lib/api/locations.ts` client; `queryKeys.locations` in
  `frontend/src/lib/query-keys.ts`; a Settings screen to list/add/edit/deactivate locations
  (follow an existing settings sub-page pattern). Add `"locations:manage"` to
  `frontend/src/lib/permissions.ts` matrix (mirror backend) + test.
- **Tests**: service unit tests; RBAC test (manager can create, member cannot, member can read);
  frontend permission mirror test.

### Stage 2 — Assign staff to a location
Tags the field roster so later filtering/scoping has data to work with. Nullable FK = existing
staff stay "unassigned" until an admin sets them.

- Migration: add nullable `business_location_id` FK (`ON DELETE SET NULL`, indexed) to
  `technicians` (and `crews` if crews are location-owned — decide during impl; default: technicians
  only to keep it minimal). Update the models + response schemas.
- API: accept/return `business_location_id` on technician create/update; validate it is
  workspace-owned (`assert_workspace_owned`).
- Frontend: location picker on the technician add/edit form.
- Tests: assigning a tech to a location; cross-workspace location id rejected.

### Stage 3 — Stamp jobs + appointments with location, and filter the dashboard
The payoff: schedule/calendar/dashboards filter by branch, reporting can group by branch.

- Migration: add nullable `business_location_id` FK (`SET NULL`, indexed) to `field_service_jobs`
  and `appointments`. Update models + schemas.
- Service+API: add optional `business_location_id` filter to `JobService.list`
  (`backend/app/services/jobs/job_service.py`) and the `GET .../jobs` endpoint
  (`backend/app/api/v1/jobs.py`); accept it on job create. Same optional filter on the
  appointments list endpoint. Default absent = unchanged behavior.
- Frontend: a **location filter dropdown** on the jobs board / calendar (`frontend/src/app/jobs`,
  `frontend/src/app/calendar`) that passes `business_location_id`; "All locations" default.
  Persist selection lightly (URL param or local state).
- Tests: list filtered by location returns only that branch's jobs; no filter returns all.

### Stage 4 — Location-scoped roles (optional, last, riskiest)
Extends the capability RBAC: a manager can be pinned to one branch and only see/manage that
branch's data.

- Migration: add nullable `business_location_id` to `workspace_memberships`
  (null = all locations, today's behavior).
- Enforcement: in the workspace-owned query helpers / list services, when the caller's membership
  is location-scoped, constrain results to that `business_location_id`. Gate writes so a
  location-scoped manager cannot touch other branches. Extend `require_capability` path or add a
  companion dependency that reads the membership's location scope.
- Frontend: show the scoped location; hide the filter when scoped.
- Tests: scoped manager sees only their branch; unscoped admin sees all; scoped manager 403 on
  another branch's job.

## Risks & mitigations

- **Naming collision with `ServiceLocation`** → use `BusinessLocation` / `business_locations`
  everywhere; UI label "Locations". Called out at top of file.
- **Prod has live CRM data** → every FK is nullable and additive; back up prod before Stage 2–4
  migrations that touch `technicians`/`appointments`/`field_service_jobs`/`workspace_memberships`
  (`make db.backup.prod`, per CLAUDE.md). Test each migration up→down→up locally first.
- **Codegen drift** → run `make codegen` and commit both artifacts in the same commit as the
  backend contract change.
- **Scope creep in Stage 4** → ship Stages 1–3 first; they deliver working multi-location
  (create branches, assign staff, filter dashboards) without touching auth. Stage 4 only if
  location-scoped managers are actually wanted.
- **Single-process workers unaffected** → this feature adds no poll loops.

## Verification per stage
- Backend: `make ci.backend` (lint/type/tests) + `.ezcoder/eyes/http.sh` against the new/changed
  endpoints with a real bearer token to confirm 2xx/403 shapes and no cross-workspace leakage.
- Migrations: `make ci.migrations` (up→check→down→up).
- Frontend: `make ci.frontend`.
- Full gate before any push: `make ci.all` must exit 0.
- Do NOT deploy as part of these steps — stop after local proof and report; deployment is a
  separate, explicit action (backend `railway up`, frontend auto-deploys).

## Steps
1. Stage 1 — Model: add `BusinessLocation` to `backend/app/models/field_service.py`, wire the
   `business_locations` relationship + `TYPE_CHECKING` import into
   `backend/app/models/workspace.py`, and export it from `backend/app/models/__init__.py`.
2. Stage 1 — Migration: run `make migrate.new m="add business_locations"`, hand-write the
   create/drop for `business_locations` chained from the current alembic head, then `make migrate`.
3. Stage 1 — Schemas: add `BusinessLocationCreate/Update/Response/ListResponse` to
   `backend/app/schemas/field_service.py` mirroring the `Crew*` schemas.
4. Stage 1 — Service: add `BusinessLocationService` (list/create/get/update/delete) under
   `backend/app/services/field_service/` and export it from the package `__init__`.
5. Stage 1 — Permissions: add `LOCATIONS_MANAGE` capability + grant (admin auto, manager) in
   `backend/app/core/permissions.py`; add `CanManageLocations` alias in `backend/app/api/deps.py`.
6. Stage 1 — Router: add `business_locations_router` (member read; `CanManageLocations` write) in
   `backend/app/api/v1/field_service.py` and register it at
   `/workspaces/{workspace_id}/business-locations` in `backend/app/api/v1/router.py`.
7. Stage 1 — Backend tests: service unit tests + RBAC tests (manager creates, member reads only)
   in `backend/tests/`.
8. Stage 1 — Codegen: run `make codegen`; commit `backend/openapi.json` and
   `frontend/src/lib/api/_generated.ts`.
9. Stage 1 — Frontend: add `frontend/src/lib/api/locations.ts`, a `queryKeys.locations` entry in
   `frontend/src/lib/query-keys.ts`, the `"locations:manage"` capability in
   `frontend/src/lib/permissions.ts` (+ test), and a Settings screen to list/add/edit/deactivate
   locations.
10. Stage 1 — Prove: `make ci.all` exits 0; hit the new endpoints with `.ezcoder/eyes/http.sh`
    (manager 2xx create, member 403 create, member 200 read); commit. Stop and report — do not deploy.
11. Stage 2 — Migration + models: add nullable `business_location_id` (SET NULL, indexed) to
    `technicians`; update the technician model and schemas.
12. Stage 2 — API + frontend: accept/validate/return `business_location_id` on technician
    create/update (`assert_workspace_owned`); add a location picker to the technician form; tests;
    `make ci.all`; commit.
13. Stage 3 — Migration + models: add nullable `business_location_id` (SET NULL, indexed) to
    `field_service_jobs` and `appointments`; update models + schemas.
14. Stage 3 — Service + API: add optional `business_location_id` filter to `JobService.list` and
    `GET .../jobs` (and accept on create), and to the appointments list endpoint.
15. Stage 3 — Frontend: add an "All locations" filter dropdown to the jobs board and calendar that
    passes `business_location_id`; tests; codegen if contracts changed; `make ci.all`; commit.
16. Stage 4 (optional) — Location-scoped memberships: migration adding nullable
    `business_location_id` to `workspace_memberships`; enforce scoping in the workspace-owned
    list/write paths; frontend scope display; RBAC tests; `make ci.all`; commit.
