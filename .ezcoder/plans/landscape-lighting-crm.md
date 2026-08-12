# Landscape Lighting CRM: First Persistence Slice

## Objective

Implement the first production vertical slice on top of the existing uncommitted landscape-lighting prototype: CRM project identity plus workspace-scoped server persistence/autosave. This slice will make drawings belong to named customer projects, survive browser/device changes, detect concurrent edits instead of overwriting them, and remain recoverable locally when the network fails.

The existing drawing, tabs, canvas, navigation, styling, and IndexedDB work will be preserved. Fixture specification, protected binary assets, revisions, electrical planning, quote snapshots, proposal delivery, project ZIP files, and install handoff remain follow-up slices after this persistence foundation is proven.

## Inspected Baseline

- `frontend/src/app/landscape-lighting/page.tsx` currently opens `LightDesigner` directly with only a workspace ID/name. There is no project list, project URL, contact ownership, or server record.
- `frontend/src/components/estimator/light-designer.tsx` already owns the multi-sheet landscape state and writes a `LandscapeDraft` after a 600 ms debounce.
- `frontend/src/lib/estimator/landscape-draft.ts` persists `version`, `activeShotId`, `shots`, and `updatedAt` in IndexedDB under the workspace ID. It is honest browser-local storage but cannot support another device or teammate.
- `frontend/src/components/estimator/editor-store.ts` already protects the drawing's undo/redo behavior and stays unchanged.
- The current draft embeds uploaded image data URLs. This slice persists the validated existing draft shape so the canvas does not need a risky storage refactor at the same time. A later asset slice will move images/PDFs to protected binary rows and rewrite draft references.
- `backend/app/api/v1/quotes.py` and the current landscape route/nav are gated by `billing:read`/`billing:write`. The project API will use those same capabilities so this slice does not widen access to pricing/proposals.
- Existing frontend primitives include `PageState`, Radix-backed dialogs, standard buttons/inputs, React Query, workspace/auth providers, shared query keys/options, and generated OpenAPI types.

## Included in This Slice

1. Workspace-scoped lighting project records with a required contact, optional opportunity/service location/assignee, project name/status, complete current draft JSON, integer version, creator/updater, and timestamps.
2. A project dashboard at `/landscape-lighting` with loading/error/empty states, create dialog, contact search/selection, project rows, archive filtering, and links to stable project URLs.
3. A project editor at `/landscape-lighting/[projectId]` that loads the saved draft into the existing `LightDesigner`, exposes project/contact identity, and shows truthful save state.
4. Debounced server autosave with one mutation in flight, coalesced edits, optimistic version checks, local pending-draft backup, offline retry, and no false claim of team sync.
5. HTTP 409 conflict handling with two non-destructive outcomes: load the latest server project or preserve local work by creating a separate project copy.
6. One-time recovery of the existing workspace-keyed IndexedDB prototype into a newly created CRM project; the legacy record is removed only after the server create succeeds.
7. Migration, backend route/service tests, OpenAPI regeneration, frontend integration tests, and the required migration/backend/codegen/frontend verification commands.

## Explicitly Deferred

- Project assets/PDF uploads and removal of data URLs from document JSON.
- Immutable revision history and checkpoint restore.
- Fixture-library metadata, editable schedule, BOM/inventory, wiring, electrical calculations, proposal zones, PDF/CSV export, quote generation, and pre-construction persistence.
- Real-time cursors or automatic field-level merging. This slice prevents silent overwrite and keeps both versions recoverable.
- Any real proposal send/delivery action.

## Data Model

Add `LightingProject` in `backend/app/models/lighting_project.py` and register it in `backend/app/models/__init__.py`. The new `lighting_projects` table contains:

- UUID `id` and UUID `workspace_id` with an indexed cascading workspace foreign key.
- Required `contact_id`; optional `service_location_id`, `opportunity_id`, and `assigned_user_id`. The service validates every reference belongs to the same workspace and that a service location belongs to the selected contact.
- `name` with a bounded nonblank length and `status` limited to `active` or `archived`. Archive is reversible and there is no hard-delete endpoint in this slice.
- JSONB `document`, storing the current version-1 `LandscapeDraft` shape.
- Positive integer `version`, beginning at 1 and incrementing on every accepted edit.
- `created_by_id`, `updated_by_id`, `created_at`, and `updated_at`.
- Workspace indexes for `(workspace_id, status, updated_at)`, contact, opportunity, and assignee.

Generate one reversible Alembic migration from the repository's current head. The migration creates only this table and indexes, so migration proof stays proportional to the slice.

## Draft Contract and Bounds

Add `backend/app/schemas/lighting_project.py` with typed create/update/detail/list schemas and a bounded `LandscapeDraftDocument`:

- Preserve the existing frontend keys `version`, `activeShotId`, `shots`, and `updatedAt` at the API boundary to avoid a canvas-wide conversion in this focused slice.
- Permit at most the existing six shots; require unique shot IDs; require `activeShotId` to reference an included shot; validate positive image dimensions and a supported draft version.
- Preserve each shot's current `photo` and `design` objects, but reject malformed lists/objects and cap the complete serialized document size. The cap will be aligned with the repository request-size limit and covered by tests.
- On create/save, the server replaces `updatedAt` with its current UTC timestamp so the response never presents a browser clock as authoritative.
- A newly created project may accept an initial document. Otherwise it receives an empty version-1 landscape draft.

The API response includes project identity, contact display name, server `version`, updater display name, and authoritative timestamps. The document's internal `version: 1` remains its schema version and is distinct from the project's concurrency `version`.

## Service and API

Create `backend/app/services/lighting_projects.py` and `backend/app/api/v1/lighting_projects.py`, then register the router in `backend/app/api/v1/router.py` under `/api/v1/workspaces/{workspace_id}/lighting-projects`:

- `GET /`: paginated summaries with search, status, contact, opportunity, and assignee filters.
- `POST /`: create a named project linked to a contact, optionally seeded with the recovered/current document.
- `GET /{project_id}`: fetch a same-workspace project and its complete document.
- `PATCH /{project_id}`: update name/status/document using required `expected_version`.
- No hard delete, quote, asset, revision, export, or send endpoint is added in this slice.

Read/list/get use `CanReadBilling`; create/update/archive use `CanWriteBilling`, matching the current nav, Price Book, and quote builder. Service queries include `workspace_id` in every lookup, and tests prove cross-workspace project/contact/location/opportunity IDs cannot be read or attached.

The update service runs in a transaction, locks the project row, compares `expected_version`, validates the complete replacement document, increments `version`, and records the updater. A stale write raises HTTP 409 with the current project version, updater name, and update timestamp; the request never overwrites the row.

## Frontend Integration

### API and Query Layer

Add `frontend/src/lib/api/lighting-projects.ts` using generated OpenAPI request/response types. Extend `frontend/src/lib/query-keys.ts` with list/detail keys and use existing query presets from `frontend/src/lib/query-options.ts`. Mutations invalidate only the affected list/detail keys.

### Project Dashboard

Replace the direct editor in `frontend/src/app/landscape-lighting/page.tsx` with a focused project dashboard component under `frontend/src/components/landscape-lighting/`:

- Reuse the CRM page rail, typography, buttons, dialogs, form controls, Lucide icons, and `PageState` states.
- Render a compact data table/list with project name, contact, status, updated time, updater, and `Open project`.
- Provide one `New lighting project` dialog with project name and a required searchable contact selection. Opportunity/location/assignee remain API-supported but are not forced into this first dialog.
- Surface the existing workspace-local draft as `Recover browser draft`. Recovery uses the same create dialog/contact selection, sends the legacy document as the initial server document, navigates to the new project, and deletes the old workspace record only after a 201 response.
- Support active/archived filtering and an archived read-only label without adding destructive delete behavior.

### Project Editor and Existing Designer

Add `frontend/src/app/landscape-lighting/[projectId]/page.tsx` and `frontend/src/components/landscape-lighting/lighting-project-editor.tsx`:

- Load the project before mounting `LightDesigner`; show page-level loading, not-found/access-denied, and retry states.
- Add a restrained project bar with back link, editable project name, contact identity, authoritative last-updated metadata, and autosave status. It shares the existing content rail and does not obscure the drafting controls.
- Extend `LightDesignerProps` with a narrow optional server-project adapter: initial `LandscapeDraft`, `onLandscapeDraftChange`, persistence status, and a reset key. Existing seasonal/sales-wizard call sites remain behaviorally unchanged.
- Disable the current workspace-keyed restore/save effect when the server-project adapter is present. The designer still emits the exact draft it currently saves locally after the existing 600 ms debounce.
- On server reload/conflict resolution, remount/reset the landscape editor from the authoritative draft without mutating seasonal editor behavior.

## Autosave and Conflict State Machine

Extend `frontend/src/lib/estimator/landscape-draft.ts` with project-keyed pending records while preserving the legacy workspace record reader:

- A pending record stores project ID, base server version, draft, dirty flag, and local timestamp. Its UI copy is `Saved on this device; sync pending`, never `Saved to Tribunal`.
- Every emitted draft first updates IndexedDB, then enters an 800 ms server debounce.
- Only one PATCH runs at a time. Changes arriving during a request replace one queued latest draft; they do not start parallel saves.
- Success adopts the returned server version. The local pending record clears only if no newer draft was queued.
- A network/5xx failure keeps the record dirty, shows pending/error with retry, and retries after online recovery or explicit action with bounded delay.
- A 409 stops automatic retry and opens a conflict dialog. `Load Tribunal version` discards only the local pending copy after fetching the current server document. `Save my work as a copy` creates a new project with the local document and navigates there. No force-overwrite action exists.
- On project load, a dirty local record is retried only when its base version equals the fetched server version. A stale base enters the same conflict dialog before mounting local state.
- Use an `aria-live` status for save transitions without moving focus. The dialog has a real title/description, contained focus, Escape behavior, and focus return.

## UI and Accessibility Contract

- This is an application workspace, not a redesign. Preserve the current Maxteriors/Tribunal tokens and amber drawing accent; do not add a second design system.
- Keep one shared content rail across page header, project bar, and editor. Use uniform input/button geometry and existing responsive breakpoints.
- Use native table/form semantics and the existing dialog primitive. All controls have visible labels, keyboard focus, loading/disabled feedback, and adjacent errors.
- Pointer clicks must not leave sticky focus styling. No emoji UI, mixed icon family, hover lift, `transition: all`, soft semantic tint-on-tint status treatments, or unsupported accessibility/compliance claims.
- Desktop and tablet keep project identity plus save state visible. Narrow layouts stack identity/status above the existing bounded canvas without horizontal page overflow.
- Update the landscape section of `frontend/DESIGN.md` to document server-vs-local save wording, project identity, conflict recovery, and responsive composition.

## Tests and Proof

### Backend

Add focused tests in `backend/tests/test_lighting_projects.py` for:

- create/list/get/update/archive and required contact ownership;
- workspace isolation for project and all linked CRM IDs;
- `billing:read`/`billing:write` capability enforcement;
- empty and populated draft validation, shot/reference/size bounds, and server-authored timestamp;
- accepted version increment and stale version HTTP 409 without document mutation;
- list filtering/pagination and archived behavior.

Run the migration against the local test database, then run `make ci.migrations`, `make ci.backend`, and `make ci.codegen`. After starting or reusing the local backend, use `.ezcoder/eyes/http.sh` to exercise create, get, accepted PATCH, stale PATCH, and unauthorized/cross-workspace behavior; inspect response shape/status and backend logs.

### Frontend

Add or update tests for:

- project dashboard loading/empty/error/list/create/archive filters;
- legacy browser-draft recovery and delete-only-after-success;
- project load into the existing landscape editor;
- autosave debounce, one-in-flight coalescing, successful version adoption, network-pending state, online retry, stale local record detection, and 409 conflict outcomes;
- no server adapter regression in existing `LightDesigner` landscape/seasonal tests;
- navigation and visual-page route fixtures.

Run the exact required verifier `make ci.frontend` and require exit code 0. Capture representative authenticated desktop and narrow screenshots of the project list and editor save/conflict states if the local app can be run; otherwise report screenshot verification as unavailable rather than claiming it passed.

## Files

Create:

- `backend/app/models/lighting_project.py`
- `backend/app/schemas/lighting_project.py`
- `backend/app/services/lighting_projects.py`
- `backend/app/api/v1/lighting_projects.py`
- `backend/alembic/versions/<generated>_add_lighting_projects.py`
- `backend/tests/test_lighting_projects.py`
- `frontend/src/lib/api/lighting-projects.ts`
- `frontend/src/components/landscape-lighting/lighting-projects-page.tsx`
- `frontend/src/components/landscape-lighting/lighting-project-editor.tsx`
- `frontend/src/components/landscape-lighting/use-lighting-project-autosave.ts`
- focused frontend test files beside these components/hooks
- `frontend/src/app/landscape-lighting/[projectId]/page.tsx`

Modify:

- `backend/app/models/__init__.py`
- `backend/app/api/v1/router.py`
- `backend/openapi.json`
- `frontend/src/lib/api/_generated.ts`
- `frontend/src/lib/query-keys.ts`
- `frontend/src/lib/estimator/landscape-draft.ts`
- `frontend/src/components/estimator/light-designer.tsx`
- `frontend/src/components/estimator/light-designer.test.tsx`
- `frontend/src/app/landscape-lighting/page.tsx`
- `frontend/src/components/estimator/estimator.css`
- `frontend/src/components/layout/app-nav.test.ts` if route expectations change
- `frontend/e2e/visual/pages.ts`
- `frontend/DESIGN.md`

## Steps

1. Add the bounded landscape draft/project schemas, `LightingProject` model registration, current-head Alembic migration, and quote/CRM-safe indexes without touching unrelated uncommitted work.
2. Implement the workspace-scoped service and billing-gated list/create/get/versioned-patch API, including CRM reference validation, row locking, 409 metadata, server timestamps, and archive behavior; add backend tests.
3. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, then add the typed frontend API client and query keys.
4. Extend IndexedDB from workspace-only drafts to project pending drafts while preserving one-time legacy recovery, and implement the tested one-in-flight autosave/conflict state machine.
5. Build the project dashboard/create-recover flow and dynamic editor route, then connect the existing `LightDesigner` through the narrow server-project adapter and truthful save/conflict UI.
6. Update the existing landscape design documentation, styles, route fixtures, and regression tests; run migrations, backend checks, codegen checks, the HTTP probes, and exact `make ci.frontend`, fixing all failures before reporting measured results.