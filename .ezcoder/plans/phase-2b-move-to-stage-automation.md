# Phase 2b — `move_to_stage` automation action

## Goal
Let an automation move a contact's opportunity to a chosen pipeline stage
automatically, so pipeline advancement stops depending on a human dragging
cards. This is the scaling lever: labor stays flat as lead volume climbs, and
tag-gated triggers keep service lines (Landscape / Permanent / Christmas /
Previous Client) from crossing wires.

Example the design must support:
> Lead captured → auto-tagged `Landscape Lighting` (Phase 1) →
> `contact_tagged: Landscape Lighting` automation → **move the deal to
> `Estimate Scheduled`** → downstream `deal_stage_changed` follow-up fires.

## What already exists (verified in this checkout)
- **Action dispatch**: `backend/app/workers/automation_worker.py` → `_run_actions`
  (if/elif on `action_type`, lines ~471–538) + one `_action_*` coroutine per
  type. Unknown types log a warning and are skipped (safe no-op today).
- **Contact-only gate**: `_CONTACT_ACTIONS` frozenset (line ~97) — actions that
  need a contact are skipped when an event has none.
- **Approval gate**: `approval_gate_service.check_and_execute_or_queue` returns
  `("auto", None)` immediately when `agent_id is None` (automations pass
  `agent_id=None`), so a new action type is **not** blocked and needs no policy.
- **Canonical stage-change logic**: `backend/app/services/opportunities/opportunity_service.py`
  → `update_opportunity` (lines ~359–398). On a real stage change it: writes an
  `OpportunityActivity(activity_type="stage_changed", …)`, sets
  `opportunity.probability = stage.probability`, sets `stage_changed_at`, and
  calls `emit_automation_event(EVENT_DEAL_STAGE_CHANGED, …)`. Guarded by
  `stage_id and stage_id != opportunity.stage_id` (idempotent).
- **Event payloads carry the opportunity id**: `opportunity_created` and
  `deal_stage_changed` events include `payload["opportunity_id"]`
  (opportunity_service lines ~300–312 and ~386–398).
- **Model facts**: `Opportunity.primary_contact_id` (nullable), `status`
  (`open|won|lost|abandoned`), `is_active`. `OpportunityActivity.user_id` is
  **nullable** — an automation-driven activity can have `user_id=None`.
  `PipelineStage.order` has **no** unique constraint.
- **Frontend action types**: `frontend/src/types/automation.ts` →
  `AutomationActionType` union (already carries an unused `update_status`, the
  precedent for a UI-only/extra kind).
- **Builder UI**: `frontend/src/components/automations/automations-page.tsx` —
  `actionTypeConfig` (labels/icons), `ACTION_OPTIONS` (dropdown list), and a
  per-action conditional config block (see the `isTagAction` tag input).
  `buildActions()` / `handleConfigureAutomation()` serialize & hydrate the first
  action's config. Pipelines/stages are fetchable via
  `opportunitiesApi.listPipelines(workspaceId)` (returns `Pipeline[]` with
  nested `stages`).
- **No OpenAPI/codegen change**: `AutomationActionSchema.type` is a free-form
  `str` (no enum/pattern), actions are JSONB, and no public response schema
  changes. `make ci.codegen` is **not** required.

## Design decisions
1. **New action type string**: `move_to_stage`.
   Config shape: `{ "stage_id": "<uuid>", "pipeline_id": "<uuid, optional>" }`.
   `pipeline_id` is stored for builder context / opportunity disambiguation.
2. **Reuse, don't duplicate, the stage-change side effects.** Add a focused
   method to `OpportunityService` (e.g. `move_stage`) that performs exactly the
   activity-log + probability + `stage_changed_at` + `emit_automation_event`
   block, accepting `user_id: int | None = None` (None for automations) and a
   `source` label. `update_opportunity` is left intact (it requires a non-null
   `user_id`, owner enforcement, and the full `OpportunityUpdate` schema — wrong
   fit for the worker). Both paths keep one source of truth for "what moving a
   stage means."
3. **Opportunity resolution order** inside the worker action:
   a. If `payload["opportunity_id"]` is present (event triggers
      `opportunity_created` / `deal_stage_changed`) → load that opportunity
      (scoped to `automation.workspace_id`).
   b. Else if a `contact` is present → pick that contact's target opportunity:
      `primary_contact_id == contact.id`, `is_active`, `status == "open"`,
      optionally filtered by `config["pipeline_id"]`, newest first; take one.
   c. Else → log a warning and skip (e.g. `lead_created` before any deal
      exists; documented limitation, not auto-created here).
   Do **not** add `move_to_stage` to `_CONTACT_ACTIONS` — the event path can
   carry an opportunity id without a contact; the action does its own None
   checks.
4. **Loop safety (the key risk).** A stage move emits `deal_stage_changed`,
   which is itself a trigger. Mitigations, all already supported:
   - The `move_stage` method only acts / emits when `target != current`
     (idempotent), so a re-fire against a fixed target stage is a no-op that
     emits nothing → any cycle terminates after one hop.
   - Per-`(automation, contact)` and per-`(automation, event_id)` execution
     dedupe already stops the *same* automation re-running for the same subject.
   - Keep emitting `deal_stage_changed` on real moves (downstream "when the deal
     reaches Estimate Sent, text the customer" automations depend on it).
   This behavior gets an explicit worker test.
5. **Validation**: the action validates that `stage_id` parses as a UUID and
   that the stage exists in the automation's workspace (via its pipeline);
   invalid/missing → warning + skip (mirrors `enroll_campaign`'s campaign check).

## Files to change
- `backend/app/services/opportunities/opportunity_service.py` — add `move_stage`
  (encapsulates the existing stage-change block; `user_id` optional).
- `backend/app/workers/automation_worker.py` — add `move_to_stage` branch in
  `_run_actions` + `_action_move_to_stage(...)`; update the module docstring's
  "Supported action type values" list.
- `backend/tests/workers/test_automation_worker.py` (existing suite) — add cases:
  move via event `opportunity_id`; move via contact resolution; idempotent
  no-op + no event when already in target stage; invalid/missing stage skip.
- `frontend/src/types/automation.ts` — add `"move_to_stage"` to
  `AutomationActionType`.
- `frontend/src/components/automations/automations-page.tsx` — add
  `actionTypeConfig["move_to_stage"]` (label "Move Deal Stage", icon
  `TrendingUp`), add it to `ACTION_OPTIONS`, add a stage-picker config block
  (fetch pipelines, group stages by pipeline in a `Select`, store `stage_id` +
  `pipeline_id`), extend `buildActions()` + `handleConfigureAutomation()`, and
  show the chosen stage name as a chip on the automation card. Add
  `newStageId` / `newStagePipelineId` state + a required-field guard in
  `handleCreateAutomation` (empty stage → toast, like the tag guard).

## Risks & mitigations
- **Trigger loop** → idempotency guard + execution dedupe (decision 4); covered
  by a test.
- **Ambiguous opportunity for a contact** (multiple open deals) → deterministic
  pick (newest open, optional pipeline filter); documented. Acceptable for v1.
- **`lead_created` + move_to_stage no-ops** (no deal yet) → documented; pairing
  with a create step is a later enhancement.
- **Cross-workspace safety** → resolution always filters by
  `automation.workspace_id`; stage validated within workspace.
- **Circular import** (worker importing OpportunityService) → import lazily
  inside the action method if needed (pattern already used for
  `notify_workspace_event`).

## Verification (no "should work")
- Backend: `make ci.backend` (lint + type + tests) green, including the new
  worker tests.
- Runtime probe: start the local backend, create a `contact_tagged`
  automation with a `move_to_stage` action via the API, tag a seeded contact
  that has an open opportunity, then use `.ezcoder/eyes/logs.sh --service
  backend --grep "automation|move_to_stage|stage_changed"` to confirm the move
  ran, and `.ezcoder/eyes/http.sh` on the opportunity to confirm the new
  `stage_id`/`probability`. Confirm a second poll does **not** move it again.
- Frontend: `make ci.frontend` (lint + type + tests + build) green; manually
  build a `move_to_stage` automation in the builder and confirm the stage chip
  renders and re-opens correctly.
- Deploy order (per CLAUDE.md): **backend first** via `railway up`, confirm
  `/readyz`, then let the frontend auto-deploy on push to `main`.

## Steps
1. Add `move_stage(workspace_id, opportunity_id, stage_id, *, user_id=None, source="automation")` to `OpportunityService` in `backend/app/services/opportunities/opportunity_service.py`, refactoring the existing stage-change block from `update_opportunity` into it (activity log with nullable `user_id`, probability update, `stage_changed_at`, `emit_automation_event(EVENT_DEAL_STAGE_CHANGED)`), and have `update_opportunity` call it so there's one source of truth; keep the `stage_id != current` idempotency guard.
2. Add `_action_move_to_stage(self, automation, contact, config, payload, db)` to `backend/app/workers/automation_worker.py`: resolve the opportunity (payload `opportunity_id` → else contact's newest open opportunity, optionally filtered by `config["pipeline_id"]` → else warn+skip), validate `stage_id` UUID + stage belongs to the workspace, then call `OpportunityService(db).move_stage(...)` with `user_id=None`.
3. Wire the dispatch in `_run_actions`: add an `elif action_type == "move_to_stage":` branch calling `_action_move_to_stage`, and update the module docstring's "Supported action type values" section.
4. Add worker tests to `backend/tests/workers/test_automation_worker.py`: (a) move via event `opportunity_id`, (b) move via contact resolution, (c) idempotent no-op with no emitted event when already in the target stage, (d) invalid/missing stage is skipped without raising.
5. Run `make ci.backend` and fix any lint/type/test failures.
6. Add `"move_to_stage"` to the `AutomationActionType` union in `frontend/src/types/automation.ts`.
7. In `frontend/src/components/automations/automations-page.tsx`: add `actionTypeConfig["move_to_stage"]` (label "Move Deal Stage", icon `TrendingUp`) and add `"move_to_stage"` to `ACTION_OPTIONS`.
8. In the same file, add `newStageId`/`newStagePipelineId` state, fetch pipelines via `opportunitiesApi.listPipelines(workspaceId)`, and render a stage-picker `Select` (stages grouped by pipeline) shown only when `newActionType === "move_to_stage"`.
9. Extend `buildActions()` to persist `{ stage_id, pipeline_id }` for `move_to_stage`, extend `handleConfigureAutomation()` to hydrate those from `firstAction.config`, add a required-stage guard in `handleCreateAutomation` (empty → toast), and render the selected stage name as a chip on the automation card.
10. Run `make ci.frontend` and fix any lint/type/test/build failures.
11. Verify locally with the eyes probes (logs + http) per the Verification section, including confirming a second poll does not re-move the deal.
12. Commit backend + frontend together; deploy backend first via `railway up` and confirm `/readyz`, then push `main` for the frontend auto-deploy.
