# Office-authored job handoff

## Goal

Give dispatchers one place to prepare a field-ready job brief: title, durable job notes, existing site/customer/scope/visit details, and private reference photos. Assigned technicians can read the brief and photos from their calendar, while technician field uploads remain in CompanyCam.

Work is isolated on `batch/technician-job-handoff` in `/Users/maxsherrod/the-tribunal-technician-handoff`; the original dirty checkout will not receive implementation changes.

## Success criteria

- Office users can stage JPEG, PNG, or WebP photos while creating a job, then add or remove job-uploaded photos from the job detail dialog.
- A direct job no longer needs a source quote before its handoff-photo panel works.
- Office users can correct the job title and edit a 5,000-character job-notes field after creation.
- Assigned technicians see the title, notes, customer phone, existing service-site/access details, price-free scope, visit instructions, and all handoff photos.
- Technicians have no photo-upload, photo-delete, or job-detail edit controls; the API also rejects those writes.
- Unassigned users and other workspaces cannot list or download a job's photos by guessing IDs.
- Existing quote handoff images remain intact and visible on converted jobs.
- No new dependency, public file URL, or unauthenticated storage surface is introduced.

## Existing behavior to preserve

- `Job.description` already stores the general job brief and is included in technician-safe `JobResponse`; the new UI will treat it as **Job notes**, not introduce a competing notes column.
- `JobResponse` already embeds narrow customer, service-location/access, and price-free scope projections. Visit instructions already live on `JobVisit` and remain editable through the existing visits panel.
- Converted jobs currently read handoff images from `quote_handoff_images`. Quote authoring and those records stay unchanged.
- Technicians remain limited by `JobService.assigned_job_predicate`; job photo reads must use that same chokepoint.
- CompanyCam remains the technician field-photo workflow. This change does not proxy CompanyCam uploads or broaden CompanyCam/contact permissions.

## Data design

Add `backend/app/models/job_handoff_image.py` and an additive Alembic migration creating `job_handoff_images` with:

- UUID primary key;
- required workspace and job foreign keys with explicit cascade deletion;
- sanitized filename, canonical MIME type, byte count, and `BYTEA` content;
- nullable uploader foreign key using `ON DELETE SET NULL`;
- creation timestamp;
- workspace/job lookup indexes.

The existing quote-image table is not altered or copied. Job photo reads merge new job-owned rows with source-quote rows in memory; the bounded collection is tiny and metadata queries never load `BYTEA`.

The server keeps one combined ten-image limit across job-owned and source-quote images. Concurrent writes lock in one order—source quote first when present, then job—before counting. Quote uploads will also include linked job images in their count, preventing either route from racing past the shared cap.

This is an expand-only production migration: old application code ignores the new table. Deploy the migration before code. Production rollback reverts the application while leaving the table and photos intact; Alembic downgrade exists only for throwaway migration CI and would drop the new table, so it must not run against production. Take and retain the encrypted production backup before release, then verify the migration against a local/prod-shaped copy.

## Backend changes

- Register `JobHandoffImage` in `backend/app/models/__init__.py`.
- Add a shared handoff-upload boundary helper under `backend/app/api/` and use it from quote and job routes. It will read at most 10 MB plus one byte, reject empty/oversized files, derive JPEG/PNG/WebP type from magic bytes, require the declared type to match, and sanitize filenames.
- Extend `HandoffImageResponse` in `backend/app/schemas/handoff_image.py` with a non-sensitive `source` discriminator (`quote` or `job`) so the UI can distinguish immutable quote-origin photos from deletable job uploads.
- Extend `backend/app/api/v1/jobs.py` with office-only upload/delete routes and visibility-scoped list/download routes. Every lookup includes workspace, job, and image ownership; failures return the same 404 shape used by job visibility.
- Return source-quote and job-uploaded metadata newest-first. Download responses retain `X-Content-Type-Options: nosniff`, private caching, and safe inline content disposition.
- Update quote upload counting in `backend/app/api/v1/quotes.py` to include any linked job uploads without changing quote read/delete semantics.
- Log IDs and byte counts only—never image bytes, notes, customer data, or original unsanitized names.

## Frontend changes

- Extend `frontend/src/lib/api/handoff-images.ts` with job upload/delete calls and the generated `source` field.
- Update `frontend/src/components/jobs/handoff-images.tsx` to support quote-edit, job-edit, and technician-read modes. Job mode always queries by job ID, including direct jobs; only job-origin images expose delete controls there.
- Add staged image selection to `frontend/src/components/jobs/new-job-dialog.tsx`, using the same count/type/size limits. Create the job once, upload selected photos, and report partial upload failures explicitly without retrying or duplicating the job.
- Add a compact dispatcher-only title and Job notes editor in `frontend/src/components/jobs/job-detail-dialog.tsx`, backed by the existing job PATCH mutation. Keep `frontend/src/components/jobs/job-brief.tsx` read-only for technicians and avoid displaying the same notes twice to dispatchers.
- Preserve keyboard labels, visible focus, button states, mobile dialog scrolling, and text alternatives based on sanitized filenames.

## Verification

- Extend `backend/tests/integration/test_job_handoff_images.py` for direct-job upload/list/download/delete, source merging, the combined cap, bad signatures, spoofed MIME types, size limits, office-only writes, assigned-technician reads, unassigned denial, and cross-workspace denial.
- Add/extend frontend tests for direct-job empty state, office upload/delete controls, quote-origin non-delete behavior, technician read-only rendering, title/notes updates, staged create uploads, and explicit partial-failure messaging.
- Regenerate and commit `backend/openapi.json` plus `frontend/src/lib/api/_generated.ts` together.
- Run targeted backend and frontend tests first, then `make ci.backend`, `make ci.frontend`, `make ci.codegen`, and `make ci.migrations`.
- With the local backend available, use `.ezcoder/eyes/http.sh` to verify office 201/204 behavior, technician 200 reads, technician 403 writes, unassigned 404 reads, response metadata, and image download headers. Inspect redacted logs for tracebacks and accidental sensitive logging.

## Steps

1. Add the additive `job_handoff_images` model, registration, migration, and database constraints/indexes.
2. Extract shared handoff-image upload validation and migrate the existing quote upload route to it without behavior drift.
3. Add workspace-scoped, role-gated job photo upload/list/download/delete routes and combined quote/job limit locking.
4. Add backend integration coverage for valid uploads, limits, source merging, tenant isolation, assignment visibility, and write denial.
5. Extend the frontend handoff-image API and component for editable office job mode and read-only technician mode.
6. Add staged office photo uploads to job creation with duplicate-safe partial-failure handling.
7. Add dispatcher title/job-notes editing while preserving the technician's unified read-only brief.
8. Add frontend tests for job photos, staged uploads, mutation visibility, and job-detail editing.
9. Regenerate OpenAPI artifacts and run targeted tests, backend/frontend CI, codegen drift, migration reversibility, and local HTTP/log probes.
