# Job handoff image attachments

## Objective

Add a visible image attachment area to the existing quote closeout flow and show the same images in the assigned technician's job details. This stays narrowly focused on manual handoff images; structured scope and first-class CompanyCam links remain separate known gaps.

## Product behavior

- A quote editor with `quotes:write` can attach and remove handoff images before scheduling.
- The closeout dialog saves images immediately on the quote, so cancelling or retrying conversion does not lose them.
- Images follow the converted job through its existing `source_quote_id`; conversion does not copy bytes or perform a second write.
- An assigned technician can list, preview, and open images from the read-only job details surface.
- A technician cannot upload, delete, enumerate another quote's images, or read images through the quote routes.
- Supported formats are JPEG, PNG, and WebP; SVG and claimed-type/header mismatches are rejected.
- The panel states the server-enforced image count and per-image size limits and reports partial upload failures plainly.

## Data design

Add a dedicated `QuoteHandoffImage` model and `quote_handoff_images` table. This keeps handoff images separate from ordinary contact files and avoids changing or reclassifying any existing attachment row.

Create one additive Alembic migration under `backend/alembic/versions/` with:

- UUID primary key plus required `workspace_id` and `quote_id`;
- foreign keys to `workspaces.id` and `quotes.id`, both with `ON DELETE CASCADE`;
- filename, canonical content type, byte count, bytes, uploader, and creation timestamp columns;
- indexes supporting workspace-and-quote listing;
- checks restricting rows to allowed image MIME types, positive bounded sizes, and matching `octet_length(data)`.

Deleting a removable quote deletes its dedicated handoff images in the same database operation; they never become ordinary contact attachments. Converted quotes already cannot be deleted through the service lifecycle rules. The downgrade drops the new table, so it affects no pre-existing records but would remove images created after this feature; production rollback therefore follows the repository backup/forward-fix process.

## Backend API

Extend `backend/app/api/v1/quotes.py` with quote-scoped handoff image list, upload, download, and delete routes. Reuse `ScopedQuote` so sales representatives receive the same owner scope as quote detail/deposit/conversion. Uploads derive `workspace_id` and `quote_id` from the authorized quote rather than trusting multipart fields.

Upload validation will:

- read at most the configured limit plus one byte;
- reject empty and oversized files;
- detect JPEG/PNG/WebP from magic bytes and require the declared MIME type to match;
- sanitize the filename using the existing attachment helper;
- serialize concurrent uploads by locking the quote before counting, enforcing the per-quote count cap;
- store the detected canonical MIME type, never the client-provided value.

Downloads return `X-Content-Type-Options: nosniff`, a sanitized inline disposition, and the stored canonical image MIME type.

Extend `backend/app/api/v1/jobs.py` with read-only list/download routes. Both call `JobService.get(..., visible_to_user_id=...)` using the existing calendar scope before querying image metadata or bytes. They expose only images whose `quote_id` matches the authorized job's `source_quote_id`; jobs without a source quote return an empty list.

Add purpose-specific metadata responses under `backend/app/schemas/`; bytes remain download-only. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` because authenticated route contracts change.

## Frontend

Add `frontend/src/lib/api/handoff-images.ts` for quote management routes and job read routes, with same-origin authenticated image URLs.

Add handoff-image query keys beneath both quote and job resources in `frontend/src/lib/query-keys.ts`.

Add a shared `frontend/src/components/jobs/handoff-images.tsx` panel that:

- renders an accessible image grid with lazy-loaded previews;
- shows an explicit empty state;
- offers a multiple-image picker only in quote-edit mode;
- validates type, size, and remaining capacity before upload;
- uploads sequentially, invalidates both quote/job image caches, and exposes delete controls only in edit mode.

Render editable mode in `frontend/src/components/quotes/convert-quote-dialog.tsx`, before crew routing, with copy explaining that images are shared with the field team. Render read-only job mode in the Details tab of `frontend/src/components/jobs/job-detail-dialog.tsx` for both dispatcher and technician views.

## Authorization and failure boundaries

- Quote routes require `quotes:read` or `quotes:write` plus the existing sales-owner predicate.
- Job routes require `jobs:read` plus existing assignment scoping for field users.
- Every image query includes `workspace_id` and its parent identifier.
- Upload metadata is server-derived; filenames, MIME claims, file bytes, route IDs, and generated client output are treated as untrusted.
- Uploads are independent writes. If one file in a batch fails, already accepted files remain visible and the UI reports the failure rather than pretending the batch rolled back.
- No production or existing records are modified during development; migration and runtime checks use the local database and isolated workflow data.

## Tests and verification

Backend tests will cover valid image storage, magic-byte/MIME mismatch rejection, empty/oversized/count-limit rejection, filename/header controls, quote-owner denial, workspace isolation, assigned-technician visibility, and unassigned-technician denial. Existing quote permission tests remain unchanged except where a new route assertion is additive.

Frontend tests will cover the editable empty area, client-side file rejection, upload/list/delete behavior, read-only technician rendering, and absence of mutation controls in job mode.

Verification after implementation:

- targeted backend API tests plus quote/job RBAC tests;
- targeted frontend component tests;
- Ruff, mypy, ESLint, and TypeScript checks for changed areas;
- OpenAPI/codegen drift check;
- migration upgrade/check/downgrade/upgrade via the repository migration CI target;
- isolated end-to-end workflow: sales uploads a real minimal PNG, another sales user is denied, conversion assigns a technician, the technician lists/downloads and sees the preview, and an unassigned technician is denied;
- HTTP probe response/status inspection, browser screenshot, and backend log scan;
- stop local servers and restore `frontend/next-env.d.ts` if Next.js rewrites it.

## Risks

- PostgreSQL stores the bytes, matching current attachment infrastructure; count and size caps bound each quote's growth but this is not object-storage scale.
- Creating a dedicated table is additive and does not rewrite or lock existing attachment rows; production rollout still follows the repository backup and migration process.
- A schema downgrade drops handoff images created after release, so production rollback requires a fresh backup or a forward fix rather than an unprotected downgrade.
- CompanyCam and structured scope are intentionally not inferred from notes or folded into this feature.

## Steps

1. Add the dedicated handoff-image model, schema, and reversible migration together, including database checks and quote-delete cascade behavior.
2. Add quote-scoped image endpoints with regressions for validation, count limits, sales ownership, workspace isolation, downloads, deletion, and cascade cleanup.
3. Add assignment-scoped job list/download endpoints with regressions for assigned visibility and unassigned denial.
4. Add the typed frontend handoff-image API and centralized quote/job query keys.
5. Build the shared editable/read-only image panel together with upload, delete, validation, rendering, and mutation-control tests.
6. Integrate the panel into quote closeout and job details, extending both dialog suites around the handoff behavior.
7. Regenerate OpenAPI artifacts and run targeted backend/frontend static and behavior checks.
8. Run migration upgrade/check/downgrade/upgrade against the isolated local database.
9. Exercise the isolated sales-to-technician workflow with HTTP, browser, screenshot, and log evidence.
10. Re-read generated/mutated files, restore incidental Next.js output, and report remaining CompanyCam/scope gaps separately.
