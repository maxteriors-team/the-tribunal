# Tag-driven stages & events — shared Opportunities board

## Goal
Let the operator run a **shared** Opportunities board whose **stages they can name/customize**, while tag-based automations ("events") drive service-line-specific follow-up (Landscape vs Permanent vs Christmas vs Previous Client).

User's answers: **shared board** (one pipeline) + **I draft the stage names**.

## What already exists (verified this session)
- **Phase 1 shipped-but-unpushed** (`98c90db`, `a62cae9`, `86d411c`, tests): lead-form auto-tagging by source + `contact_tagged` trigger with a tag picker. So "a specific event per tag" is already buildable in the UI — each service-line tag = its own automation = its own event.
- **One shared board already in prod**: pipeline "Sales Pipeline" (workspace `ba0e0e99…`), **17 live opportunities**. Stages: `New`(13 cards) → `Qualified`(1) → `Proposal`(0) → `Won`(0) → `Lost`(3).
- **Stage CRUD backend**: `POST /pipelines/{id}/stages` (create) and `PUT /pipelines/{id}/stages/{stage_id}` (update: name/order/probability/stage_type) exist. Service: `OpportunityService.create_pipeline_stage` / `update_pipeline_stage`.
- **Frontend API client** already exposes `opportunitiesApi.createStage` / `updateStage` (and an **orphaned** `deleteStage`).
- **Board UI**: `frontend/src/components/opportunities/opportunities-board.tsx` renders stages as drag-drop columns (`StageColumn`), but has **no UI to add/rename/reorder/delete stages**.

## Gaps
1. **No stage-management UI** — operator can't customize the shared board's stages.
2. **No delete-stage backend endpoint** — `opportunitiesApi.deleteStage` calls `DELETE …/stages/{id}` but no such route exists (would 405). Delete also needs a safeguard for the 17 live cards.
3. **No `move_to_stage` automation action** (optional) — tag automations can't advance a card into a stage. Worker actions today: send_sms/send_email/make_call/enroll_campaign/apply_tag/wait.

## Scope of THIS plan (Phase 2a — frontend-only, no backend deploy)
Build a **"Manage stages"** dialog on the Opportunities board that reuses the existing create/update endpoints:
- **Add stage** — appends with `order = max(order)+1`, default `stage_type="active"`, `probability=0`.
- **Rename stage** — inline text, PUT `name`.
- **Reorder** — up/down buttons that swap `order` with the neighbor via PUT (matches existing `order:int` model; no bulk endpoint needed).
- **Edit type/probability** — small select for `stage_type` (active/won/lost) + probability input (optional, keep minimal).
- **Delete deferred** — hide delete for now (endpoint missing + live-card safety). Called out as Phase 2c below.
- Invalidate `queryKeys.opportunities.pipelines(workspaceId)` after each mutation so the board re-renders.

This directly delivers "add custom stages" on the shared board, non-destructively (operator drives every change; renames preserve cards).

## Drafted shared-board stage names (starting point the operator can edit)
Service-agnostic sales/service flow for a lighting business, mapped onto the existing stages so **no card is orphaned**:
1. **New Lead** (rename `New`)
2. **Contacted** (rename `Qualified`)
3. **Estimate Scheduled** (NEW — site visit booked)
4. **Estimate Sent** (rename `Proposal`)
5. **Won** (keep)
6. **Lost** (keep)

Renames + one additive stage = zero destructive changes to the 17 live opportunities. The operator applies these via the new UI (or I seed them with a one-off prod script on request).

## Out of scope here (offer as follow-ups)
- **Phase 2b — `move_to_stage` automation action** (backend `automation_worker.py` new `_action_move_to_stage` reading `config.stage_id`/`stage_name` + resolving/creating the contact's opportunity; frontend builder action-config stage picker). Automation actions are freeform JSON, so **no schema/codegen change**, but it needs a backend deploy. Enables "Landscape Lighting tag → move card to Estimate Scheduled."
- **Phase 2c — delete-stage endpoint** (backend route + service, with a guard: block or reassign cards when the stage is occupied) so the UI can safely offer delete.

## Risks & mitigations
- **Production board with 17 live cards** — Phase 2a only renames/adds/reorders via operator action; no auto-mutation, no deletes. Safe.
- **Reorder race** — swap-with-neighbor uses two PUTs; invalidate after both settle. Acceptable for a low-frequency admin action.
- **Match existing patterns** — reuse `useMutation` + `getApiErrorMessage` + toast + `queryKeys.opportunities.pipelines` exactly as `PipelineBoard` already does.

## Verification
- `cd frontend && npx tsc --noEmit` and `npx eslint` on changed files.
- `npm run build` green.
- Manual: open board → Manage stages → add "Estimate Scheduled", rename New→New Lead, reorder; confirm board reflects changes and existing cards stay put. (Auth/workspace-gated; no verified headless visual probe in this checkout — rely on build + reused primitives, escalate if runtime visual proof needed.)
- No backend change in 2a → **frontend push auto-deploys**; no `railway up`, no codegen.

## Steps
1. Add a `CreatePipelineStageRequest`-shaped helper in `opportunities-board.tsx` scope and a `useQueryClient`-backed set of mutations (create/update stage) that invalidate `queryKeys.opportunities.pipelines(workspaceId)`.
2. Build a `ManageStagesDialog` component (new file `frontend/src/components/opportunities/manage-stages-dialog.tsx`) that lists the pipeline's stages sorted by `order` with: rename input, stage_type select, up/down reorder buttons, and an "Add stage" row; wire it to `opportunitiesApi.createStage` / `updateStage`.
3. Implement reorder as a neighbor-swap: PUT the two affected stages' `order` values, then invalidate the pipelines query.
4. Add a "Manage stages" button to the `PipelineBoard` header (next to "Add Opportunity") that opens the dialog, passing `workspaceId` and `pipeline`.
5. Reuse `getApiErrorMessage` + `toast` for success/error feedback on every mutation, matching the existing `moveMutation` pattern.
6. Run `npx tsc --noEmit`, `npx eslint` on the two changed files, and `npm run build`; fix any issues.
7. Commit as `feat(opportunities): manage pipeline stages from the board` (frontend-only).
8. On the operator's go: push `main` (frontend auto-deploys); then either they apply the drafted stage names via the new UI, or I seed them with a one-off prod script.
