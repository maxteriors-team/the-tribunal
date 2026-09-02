# Move lighting-project images out of Postgres into the private bucket

## Why

`lighting_projects` is 100 MB of a 164 MB database on a **500 MB volume**. The
weight is one JSONB column:

| measure | value |
|---|---|
| rows | 30 |
| `document` column | 82 MB |
| rows containing `data:image` | 25 of 30 |
| largest single document | 10 MB |
| growth | ~2.7 MB per project |

Postgres compression (`pglz`) is already enabled on the column and returns
**zero**: stored 82 MB, raw text 82 MB. Base64-wrapped PNG/JPEG has no
repeating structure left to compress, so compaction is not available as a fix.
`VACUUM` reclaimed 6 MB on 2026-09-01; the rest needs `VACUUM FULL`, which needs
more free space than the volume has. **Only moving the bytes out actually fixes
this.**

The schema ceiling is worse than the current average: `MAX_LANDSCAPE_SHOTS` (6) ×
`MAX_PLAN_IMAGES_PER_SHOT` (12) × `MAX_DATA_URL_CHARS` (8 MB) allows a
**single project** to exceed the entire volume.

Object storage already exists and is wired for MMS
(`app/services/messaging/media_storage.py`, bucket `crm-mms-media`). This plan
reuses it rather than adding anything.

## What is actually stored

Three fields in `LandscapeDraftDocument` hold data URLs
(`backend/app/schemas/lighting_project.py`):

| field | line | shape |
|---|---|---|
| `PlanImageSchema.data_url` | 166 | required, per plan image, ≤12 per shot |
| `AnnotationSchema.image_data_url` | 204 | optional, per annotation |
| `PhotoSchema.data_url` | 300 | required, one per shot |

All three are validated with `startswith("data:image/")`, so **the schema
currently rejects a storage key**. That validator is the write path's lock and
must change before any row can hold a key.

## Design

Store bytes in the bucket, keep a short key in the document, and mint a
short-lived signed URL at read time.

Key layout follows the existing MMS convention
(`workspaces/{workspace_id}/outbound-attachments/{uuid}{ext}`):

```
workspaces/{workspace_id}/lighting-projects/{project_id}/{image_id}{ext}
```

Workspace-first prefixing keeps tenant isolation visible in the key and matches
`MMSMediaStorage._validate_object_key`'s normalized-relative-path rule.

### The hard constraint: canvas tainting

`frontend/src/lib/estimator/export.ts:59` calls `canvas.toDataURL()` after
`drawScene()` draws the photo. Drawing a cross-origin image onto a canvas
**taints** it, and `toDataURL()` then throws a `SecurityError`. This silently
breaks design export — the feature that produces customer proposals.

Two conditions must both hold:
1. the bucket must return `Access-Control-Allow-Origin` for the app origin, and
2. the `<img>` must set `crossOrigin="anonymous"` **before** `src`.

This is the single highest-risk item in the plan and is why step 2 below is a
standalone spike: if Railway buckets cannot emit CORS headers, the fallback is
proxying image bytes through the backend (an authenticated
`GET /api/v1/workspaces/{id}/lighting-projects/{id}/images/{image_id}`), which
is same-origin and cannot taint. **Do not start step 5 before step 2 answers
this.**

#### Step 2 result (2026-09-01): CORS works — presigned URLs, no backend proxy

Probed the live bucket `crm-mms-media-p4h18szvvxu` at `https://t3.storageapi.dev`
through `railway run`, so credentials never left the Railway env:

| probe | result |
|---|---|
| `get_bucket_cors` before | no rules |
| `put_bucket_cors` | accepted **and persisted** |
| `OPTIONS` preflight w/ Origin | `200`, full `Access-Control-Allow-*` set |
| `GET` w/ allowed Origin | `200`, `ACAO: https://app.maxteriorslighting.com` |
| `GET` w/ foreign Origin | `200`, **no** `ACAO` (correctly withheld) |

So `crossOrigin="anonymous"` will load and the canvas will not taint. The
backend-proxy fallback is **not** needed. Two caveats carried forward:

- The rule takes a few seconds to propagate; an immediate re-read after `put`
  still showed no header. Not a runtime concern.
- The bucket does **not** send `Vary: Origin`. Presigned URLs are unique per
  signature and are not served through a shared cache, so this is inert here —
  but do not put these objects behind a CDN without revisiting it.

`scripts/ops/set_bucket_cors.py` applies the rule from `CORS_ORIGINS` so it is
reproducible and travels with a domain change.

#### Where the resolved URL travels

The document keeps the **stable** `lighting-image:{key}` in `data_url` /
`image_data_url`, and the signed URL is delivered in a sibling read-only field
(`resolved_url` / `resolved_image_url`). This is the round-trip fix: the editor
PATCHes the whole document back, so if the signed URL replaced the key in place
the client would send an expiring URL back as the stored value and the server
would have to reverse-map it. Sibling fields also keep the write path narrow —
it only ever accepts `data:image/` or an existing key, never an arbitrary
`https://` URL, so there is no stored-URL injection surface. The write path
strips `resolved_*` before persisting, so no expiring URL is written to JSONB.

### Compatibility

`document` is validated wholesale by `LandscapeDraftDocument.model_validate` in
three places (`lighting_projects.py:85`, `:300`, and
`jobs/job_service.py:388`), so a partially-migrated document must stay valid.
The image fields therefore accept **either** a data URL or a storage key for the
whole transition, and only after the backfill is proven do we consider
tightening. Never a flag day.

## Order of operations (non-negotiable)

**Code that can read a storage key must be live in production before a single
key is written to the database.** Confirmed failure mode if this is inverted:

- `get_project` → `_detail` → `LandscapeDraftDocument.model_validate` raises on
  a value that is not a `data:image/` URL.
- `backend/app/api/v1/lighting_projects.py` has no local exception handling, so
  it falls through to the global `@app.exception_handler(Exception)` at
  `backend/app/main.py:877` — a **hard 500** with a generic envelope.
- `jobs/job_service.py:388` catches `ValueError` and returns **404 Installation
  plan not found**.

So a backfill run against today's production would take the light designer down
for all 25 migrated projects and silently hide their installation plans. The
gate in steps 9–12 exists to make that impossible.

Note the corollary: **once keys are written, the deploy is forward-only.**
Rolling the backend back to a pre-key release reintroduces the same 500. If a
rollback is ever needed after the backfill, restore the pre-`--apply` encrypted
dump rather than redeploying old code.

## Risks

- **Canvas tainting breaks proposal export** — mitigated by the step 2 spike;
  hard-stop gate before any frontend work.
- **Backfill before deploy = 500s** — mitigated by the explicit gate at steps
  9–12; see "Order of operations" above.
- **Volume is 68% full** — the backfill *writes* new JSONB before old bytes are
  freed, so a single-pass rewrite of all 25 rows transiently grows the table.
  Step 14 therefore batches and vacuums between batches.
- **`job_service.py:388` reads the same document** for installation plans. It
  must keep working for both shapes.
- **Deleting bucket objects on project delete** is out of scope here and would
  orphan bytes; note it as follow-up rather than half-doing it.
- **Offline/local drafts**: `image-resize.ts` produces data URLs client-side.
  Upload happens on save, so a draft in progress still holds a data URL — which
  is exactly why the dual-shape schema is required.

## Verification

- Backfill script runs `--dry-run` first (mirrors `scripts/ops/backfill_quo.py`)
  and reports per-row byte counts with no writes.
- Encrypted production backup before `--apply`
  (`make db.backup.prod`, verify `PGDMP` header).
- After backfill: `pg_total_relation_size('lighting_projects')` well under
  20 MB, `select count(*) ... like '%data:image%'` returns 0.
- Open a migrated project in the designer, confirm the plan photo renders,
  then **export a design JPEG** — this is the canvas-tainting proof.
- Open an installation plan for a job whose project was migrated.
- `make ci.all` exits 0 **before** the release, not after.

## Out of scope

- Deleting bucket objects when a project is deleted (follow-up).
- Re-encoding existing images to WebP.
- Raising the volume size — this plan aims to make that unnecessary.

## Steps

Steps 1–8 are build work, 9–12 are the release gate that must complete before
any database write, and 13–16 are the migration itself.

1. Confirm production bucket configuration: verify `MMS_STORAGE_BUCKET` and its
   sibling credentials are set on the Railway `the-tribunal-api` service, and
   that `settings.mms_storage_enabled` is true in production.
2. Spike Railway bucket CORS: upload a test object, fetch it from the app origin
   with `crossOrigin="anonymous"`, draw it to a canvas, and call `toDataURL()`.
   Record whether it throws. If CORS is unavailable, adopt the backend-proxy
   variant for all subsequent steps and note it in this file before continuing.
3. Add a `LightingImageRef` discriminator to `backend/app/schemas/lighting_project.py`:
   relax the three validators (lines 176, 208, 304) to accept either a
   `data:image/` URL or a `lighting-image:{key}` reference, keeping the existing
   length ceiling for data URLs. Add unit tests for both shapes and for rejection
   of anything else.
4. Add `store_lighting_image()` and `resolve_lighting_image_url()` to a new
   `backend/app/services/lighting_projects/images.py`, reusing `MMSMediaStorage`
   and modeling them on `store_outbound_image` in
   `backend/app/services/messaging/outbound_media.py`. Bound size and verify the
   file signature exactly as `decode_outbound_image_data_url` does.
5. Resolve stored keys to signed URLs on read in
   `LightingProjectService._detail` and in the installation-plan path at
   `backend/app/services/jobs/job_service.py:388`, leaving data URLs untouched.
   Add tests covering a document containing both shapes.
6. Convert data URLs to stored objects on write in
   `LightingProjectService.create_project` and `update_project` so new saves stop
   embedding bytes. Add tests proving a data-URL save persists a key, not bytes.
7. Update the frontend to consume resolved URLs: set `crossOrigin="anonymous"`
   before `src` wherever plan images, annotation images, and shot photos are
   loaded, and correct the stale "this deployment has no object storage" comment
   in `frontend/src/lib/estimator/image-resize.ts`.
8. Write `scripts/ops/migrate_lighting_images.py` with `--dry-run` (default) and
   `--apply`, plus a `--limit` so rows can be migrated in batches. Follow the
   argument and safety conventions of `scripts/ops/backfill_quo.py`; commit per
   row rather than per run.
9. RELEASE GATE — production must be able to read keys before any are written.
   `make ci.all` must exit 0. If public API contracts changed, run `make codegen`
   and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in
   the same commit first, then re-run.
10. Open a PR against `main` (protected; direct pushes rejected). Required:
    4 status checks (`Scan for secrets`, `Verify migration reversibility`,
    `Analyze (javascript-typescript)`, `Analyze (python)`), linear history, and
    all review conversations resolved — CodeQL auto-comments count. Merge with
    `gh pr merge <n> --rebase --delete-branch`.
11. Deploy the backend from merged `main`, not from the branch:
    `git fetch && git reset --hard origin/main`, then `make deploy.backend` from
    the repo root. A rebase merge rewrites SHAs, so deploy the rewritten one.
12. Verify live before touching data: `curl -s .../version` must report the
    deployed SHA (not `"unknown"`, no `-dirty`), that SHA must be an ancestor of
    `origin/main` (`git branch -r --contains <sha>`), and
    `make smoke.backend` must pass. Then open one **unmigrated** project in the
    designer and export a design JPEG, proving the new read path is backward
    compatible with data URLs. **Do not proceed until this passes.**
13. Run `scripts/ops/migrate_lighting_images.py --dry-run` against production and
    review the reported byte counts and row list.
14. Take a fresh encrypted production backup (`make db.backup.prod`) and verify
    its `PGDMP` header. Then run `--apply` **in batches** — `--limit 5` at a
    time, on a 68%-full volume — and run `VACUUM (VERBOSE) lighting_projects`
    after each batch, recording the reclaimed size. Stop and reassess if
    `pg_total_relation_size` grows rather than shrinks across a batch boundary.
15. Verify end to end in production: open a migrated project, export a design
    JPEG, open an installation plan for a migrated project's job, and confirm
    `select count(*) from lighting_projects where document::text like '%data:image%'`
    returns 0.
16. Record the final `pg_total_relation_size('lighting_projects')` and the
    Railway volume usage, confirming the volume no longer trends toward its cap.
