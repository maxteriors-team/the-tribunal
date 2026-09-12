# Move a deal between pipelines

## Problem

The board has no "move" — only "add". Operators move someone by adding a second
card, which is what texted an already-quoted customer a welcome message
(fixed separately in `1e99743`, by teaching the trigger to ignore filed cards).
The underlying gap is still open: `JIM TORTOMOSE` has two cards because moving
him required making one.

## What the code actually supports today

`PUT /api/v1/workspaces/{ws}/opportunities/{id}` already accepts `stage_id` and
routes it through `OpportunityService.move_stage` — the documented stage-change
chokepoint (activity log, probability, `stage_changed_at`, `deal_stage_changed`).

So "move between pipelines" does not need a new endpoint. It needs the
chokepoint to stop being wrong in two ways.

### Defect 1 — `pipeline_id` is never synced (correctness)

`move_stage` sets `stage_id` and `probability` but leaves `pipeline_id`
untouched. Point a deal at a stage in another pipeline today and it renders
under the *old* pipeline with a stage that does not belong to it. This is
exactly why there is no move control: the operation was never safe to expose.

### Defect 2 — the stage lookup is not workspace-scoped (tenancy)

`opportunity_service.py:471`
```python
stage_query = select(PipelineStage).where(PipelineStage.id == stage_id)
```

No workspace predicate. `opportunity_service.py:317` (create) has the same
shape, though there the parent pipeline *is* validated, so only the stage is
loose.

Reachability — traced, not assumed:

| Hop | Control |
| --- | --- |
| `PUT .../opportunities/{id}` | `CanWritePipelineOwn` — caller is a writing member of **this** workspace |
| `update_opportunity` | `get_or_404(Opportunity, …, workspace_id=…)` — the deal is scoped ✅ |
| `move_stage` | stage loaded **by id alone** ❌ |

An authenticated member of workspace A holding a stage UUID from workspace B
can attach their own deal to B's stage. What they get: B's stage *name* copied
into their activity log, B's `probability` onto their deal, and a corrupted
card. Not a read of B's data, and stage ids are v4 UUIDs so there is nothing to
enumerate — **Medium**, downgraded for the guessing precondition. The fix is one
predicate, so the precondition is not a reason to leave it.

## Change

**Backend — fix the chokepoint; the feature falls out of it.**

1. `move_stage`: resolve the stage through its pipeline, scoped to the
   workspace. Unknown *or* foreign stage → the existing `NotFoundError`
   (fail closed, and it does not tell the caller which of the two it was).
2. `move_stage`: when `stage.pipeline_id != opportunity.pipeline_id`, set it and
   log a `pipeline_changed` activity alongside the existing `stage_changed`, so
   the deal's history says where it went. Fourth activity type, matching the
   three that exist.
3. `create_opportunity`: same scoping predicate, and reject a stage that is not
   in the pipeline being created into.
4. No new endpoint, no new schema field. `OpportunityUpdate.stage_id` is enough.

Board drag-and-drop is unaffected — same pipeline in, same pipeline out.

**Frontend — the control the operator was missing.**

The contact sidebar Pipeline card is where this belongs: it is where the
operator looks at the cards, and where the screenshot shows the damage. Each
card gets a move control that lists every pipeline's stages and calls
`opportunitiesApi.update(id, { stage_id })`. The cards are currently a bare
`<Link>` to `/opportunities`; the link stays, the control sits beside it.

## Proof

- Regression test: a stage id from another workspace is refused. Fails against
  today's code — that is the point of it.
- Test: moving to a stage in another pipeline moves `pipeline_id` with it and
  writes both activities.
- Test: moving within a pipeline is unchanged (no `pipeline_changed` noise).
- Existing `move_stage` / board / automation tests must stay green — this is a
  chokepoint every automation path already runs through.
- `make ci.backend`, `make ci.frontend`, `make codegen/check`.

## Not in scope

Bulk move, moving a card from the board itself, and merging the duplicate cards
Jim already has. Each is a separate change; none is needed to close the gap.
