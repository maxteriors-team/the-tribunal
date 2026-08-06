# Pipeline restructure — stop auto-filing leads, reshape the sales stages

## Goal

Operator feedback (2026-08-04), items 1–3:

> 1. When a lead comes in it should not be in opportunities yet since it will be cluttered.
>    Instead it will just go to new contacts then moved to contacted or lost.
> 2. We will only put leads in opportunities once we contacted them and if we have
>    scheduled a call with you or a demo.
> 3. Consider opportunities as your sales pipeline:
>    Qualified · Visit/Demo Scheduled · Quote · Quote Sent / Follow Up · Won · Lost

Three deliverables: **(A)** inbound leads stop auto-opening opportunity cards,
**(B)** the default pipeline becomes the six stages above, **(C)** existing
opportunities sitting in the old stages get a defined, reversible landing.

Explicitly **out of scope** (see "Deliberately not doing" below): new
auto-promotion triggers, contact-status workflow changes, Find Leads, and the
calendar bug.

---

## What already exists (verified in this checkout)

### The auto-open feature and its gate

- `backend/app/services/opportunities/lead_opportunity.py` — `open_lead_opportunity()`
  creates one deduped **open** card per contact in the default pipeline's
  **first stage** (`get_default_pipeline_first_stage`, line 95).
- The per-workspace gate already exists: `auto_pipeline_enabled()` (lines 42–47)
  reads `workspace.settings["auto_pipeline"]["enabled"]`, **defaulting to `True`**.
  JSONB column — no migration needed to change a workspace's value.
- Five inbound funnels call it, each already wrapped in try/except:
  | Funnel | Call site | `source` |
  |---|---|---|
  | Public lead form | `backend/app/api/v1/lead_form.py:620` | `lead_form` |
  | Offer opt-in | `backend/app/api/v1/offers.py:542` | `offer` |
  | Inbound voice (AI tool) | `backend/app/services/ai/tool_executor.py:1430` | `inbound_call` |
  | Embed widget | `backend/app/services/embed/service.py:342` | `embed` |
  | Inbound SMS | `backend/app/services/telephony/inbound_text.py:292` | `inbound_sms` |
- **Every call site no-ops when the gate returns `False`** — so flipping the gate
  is the whole of deliverable (A). No call-site edits.
- `backend/scripts/backfills/backfill_lead_opportunities.py` honors the same gate.

### The default stages

- `backend/app/services/opportunities/default_pipeline.py:40-46` is the single
  source of truth — `DEFAULT_PIPELINE_STAGES`:
  `New(0, 0%, active) · Qualified(1, 25%) · Proposal(2, 50%) · Won(3, 100%, won) · Lost(4, 0%, lost)`.
- `opportunity_service.py:42` aliases it (`_DEFAULT_STAGES`) for
  `create_pipeline`, so one edit covers both provisioning paths.
- Consumers of `ensure_default_pipeline`: `app/api/v1/workspaces.py:103`,
  `app/services/workspaces/provisioning.py:122`, `app/db/seed.py:82,139`,
  `backfill_default_pipelines.py:112`.
- `get_default_pipeline_first_stage()` returns the **lowest-order** stage. Used by
  auto-open **and** by ad-library promotion (`app/services/outbound/promotion.py:184`,
  `source="ad_library"`).

### What reads stage *names* (the landmines)

- **`backend/app/services/campaigns/reply_handler.py:314`** —
  `stage_name = "Booked" if category == BOOKED else "Qualified"`, then
  `_get_or_create_stage` **creates the stage if missing** at `order=2` (BOOKED) /
  `order=1`. After the restructure `"Booked"` no longer exists, so the first
  booked SMS reply would silently graft a **stray 6th stage colliding with Quote
  at order 2**. This must be remapped — it is the only real breakage.
- `backend/app/services/outbound/growth_workflow.py:457` — the word "Qualified"
  inside LLM prompt copy. Cosmetic; `Qualified` survives the rename anyway.
- **Frontend hardcodes nothing.** `opportunities-board.tsx:303` maps over stages
  from the API; `manage-stages-dialog.tsx` already lets operators rename,
  reorder, retype, and add stages. `STAGE_ACCENT` keys off `stage_type`
  (`active|won|lost`), which is unchanged.
- `backend/tests/services/opportunities/test_default_pipeline.py:52-53` derives
  its assertions from `DEFAULT_PIPELINE_STAGES` — name-agnostic, keeps passing.

### Blast radius of archiving open cards

- `dashboard_service.py:795-803` lists open pipeline cards filtered on
  `status == "open"` AND `is_active` → archived cards **disappear from the
  dashboard**, which is the point.
- `dashboard_service.py:667-675` counts `status IN ("open","won")` for the
  first-touch funnel → those counts **will drop**. Expected; call it out at release.
- `lead_source_roi_service.py:144-158` and `:169-174` filter `status == "won"`
  **only** → **closed-won ROI and revenue attribution are untouched.** Good.
- Auto-created cards carry `amount = NULL`, so **open pipeline *value* does not
  change** — only card counts.

### Model + migration facts

- `Opportunity.status` is a PG enum `("open","won","lost","abandoned")`
  (`models/opportunity.py:145-150`); `is_active: bool`; `stage_id` is
  **nullable** with `ondelete="SET NULL"`.
- `PipelineStage.order` has **no unique constraint** (`models/pipeline.py:80`) —
  reordering in place is safe.
- `OpportunityActivity.user_id` is **nullable** — a migration-written activity row
  is legal.
- `PipelineStage.opportunities` relationship uses `cascade="all, delete-orphan"`
  (`models/pipeline.py:101-103`) — **deleting a stage row via the ORM would delete
  its opportunities.** The migration must use Core SQL, and must not delete the
  `New` stage. This is the single most dangerous edge in this change.
- CI gate `make ci.migrations` (Makefile:171-180) runs
  `upgrade head → alembic check → downgrade -1 → upgrade head`, so the downgrade
  must genuinely work. It runs against an **empty** DB, so it proves the SQL is
  valid but **does not exercise the data transform** — that needs a pytest
  integration test (below).

---

## Design decisions

### A. Turn auto-open off — flip the default, keep the override

Change `auto_pipeline_enabled()` to default **`False`**:

```python
return bool(raw.get("enabled", False))
```

Why the code default rather than writing `{"enabled": false}` into each
workspace row: the operator is describing how the product should behave, not one
tenant's preference. A default flip covers **every existing workspace and every
future one** in a single reviewable line, and the existing per-workspace
`{"enabled": true}` override still turns it back on. A row-by-row settings write
would leave new workspaces cluttered again on day one.

The flag becomes unreachable from the UI once it is off by default, so add a
minimal settings endpoint following the exact `lead-source-capture` precedent
(`app/api/v1/settings.py:614-641`):
`GET/PUT /api/v1/workspaces/{workspace_id}/auto-pipeline`, Pydantic
`AutoPipelineSettings{enabled: bool}`, shallow merge into `workspace.settings`.
This changes the public OpenAPI surface → **`make codegen` + commit
`backend/openapi.json` and `frontend/src/lib/api/_generated.ts` in the same
commit** (per CLAUDE.md release step 1).

### B. New default stages

```python
DEFAULT_PIPELINE_STAGES = [
    {"name": "Qualified",             "order": 0, "probability": 25,  "stage_type": "active"},
    {"name": "Visit/Demo Scheduled",  "order": 1, "probability": 45,  "stage_type": "active"},
    {"name": "Quote",                 "order": 2, "probability": 60,  "stage_type": "active"},
    {"name": "Quote Sent / Follow Up","order": 3, "probability": 75,  "stage_type": "active"},
    {"name": "Won",                   "order": 4, "probability": 100, "stage_type": "won"},
    {"name": "Lost",                  "order": 5, "probability": 0,   "stage_type": "lost"},
]
```

`New` is deleted from the defaults: with auto-open off, nothing lands in a
pre-qualified column, and the operator's list has no such stage.

**Consequence to accept:** `get_default_pipeline_first_stage()` now returns
**Qualified**, so ad-library promotion (`promotion.py:184`) drops prospects
straight into Qualified. Those prospects are ICP-screened
(`ad_intelligence/prospecting.py:155` — "ICP-qualified"), so the label holds.

**Required fix** — `reply_handler.py:314,328`:
`BOOKED → "Visit/Demo Scheduled"` (order 1, probability 45), everything else →
`"Qualified"` (order 0, probability 25). Without this the first booked reply
grafts a stray stage.

### C. What happens to existing data

**Guard rail — only touch untouched defaults.** Operate only on pipelines whose
stage name set is **exactly** `{New, Qualified, Proposal, Won, Lost}`. Any
pipeline an operator customized via Manage Stages is skipped and counted in the
migration log. Never clobber operator work.

**Stage rows (matched pipelines) — rename in place, never delete.** Renaming
keeps `stage_id` stable, so opportunities follow their column with **zero row
rewrites**:

| Old row | Action | New state |
|---|---|---|
| `Qualified` | reorder | order 0, prob 25 |
| `Proposal` | **rename** | `Quote`, order 2, prob 60 |
| `Won` | reorder | order 4, prob 100, type `won` |
| `Lost` | reorder | order 5, prob 0, type `lost` |
| `New` | **rename + park** | `Unqualified (archived)`, order 6 — off the end of the board |
| — | **insert** | `Visit/Demo Scheduled` order 1, prob 45 |
| — | **insert** | `Quote Sent / Follow Up` order 3, prob 75 |

`New` is renamed, **not deleted** — the `delete-orphan` cascade makes deletion a
data-loss trap, and keeping the row is what makes the downgrade exact.

**Opportunities sitting in `New`** split two ways:

1. **Auto-created and never touched → archived.** Predicate:
   `source IN ('lead_form','offer','embed','inbound_sms','inbound_call')`
   AND `amount IS NULL` AND `assigned_user_id IS NULL`
   AND no row in `opportunity_line_items` AND no row in `opportunity_activities`.
   Action: `status = 'abandoned'`, `is_active = false`; `stage_id` unchanged
   (still points at the parked stage). **Nothing is deleted** — the row survives,
   and the person still exists in Contacts, which is exactly where the operator
   says they belong.
2. **Everything else in `New` → `Qualified`.** Manual, `ad_library`, `campaign`,
   or anything a human touched is a real deal. Set `stage_id` to the Qualified
   row, `probability = 25`, `stage_changed_at = now()`, and insert an
   `OpportunityActivity(activity_type='stage_changed', user_id=NULL,
   old_value='New', new_value='Qualified', description='Pipeline restructure …')`
   so the trail is honest.

Opportunities in `Qualified`/`Proposal`/`Won`/`Lost` need **no** row changes —
their stage row was renamed/reordered under them.

**Reversibility.** `upgrade()` first creates a scratch table
`pipeline_restructure_backup` recording, per changed row:
`kind ('stage'|'opportunity')`, `row_id`, and the prior
`stage_id / status / is_active / probability / name / order / created_by_migration`.
`downgrade()` replays it exactly — restore opportunity fields, restore stage
names/orders/probabilities, delete the two inserted stages (Core `DELETE`, not
ORM, so no cascade), delete the migration-written activity rows, then drop the
scratch table. Because CI runs `downgrade -1` on an empty DB, correctness of the
data path is proven by the integration test, not by CI alone.

**Vehicle: an Alembic migration, not a script.** Two backfill scripts already
exist (`backfill_default_pipelines.py`, `backfill_lead_opportunities.py`) and are
the softer option, but a script leaves every environment in a different state
until someone remembers to run it, and gives no downgrade path. The migration
converges dev/CI/prod in one shot and its reverse is CI-exercised. Cost: it runs
automatically in Railway pre-deploy (`alembic upgrade head`), so the release MUST
be preceded by `make db.backup.prod` — this touches customer pipeline data and
falls squarely under CLAUDE.md release step 3.

---

## Deliberately not doing (and why)

- **No new auto-promotion triggers.** The operator's model ("only once we
  contacted them and scheduled a call/demo") is already partly served:
  `reply_handler._upsert_opportunity` (line 234) opens/advances a card on
  `INTERESTED / QUESTION / OBJECTION / BOOKED / HUMAN_NEEDED` replies. Wiring
  "appointment booked → Visit/Demo Scheduled" and "contact qualified
  (`services/ai/qualification.py:429`) → Qualified" is the natural next step but
  is a separate change with its own blast radius. **After this lands, the
  pipeline fills from: manual creation, campaign replies, and ad-library
  promotion only.**
- **No contact-status workflow change.** Suggestion #1's "new → contacted → lost"
  already exists on `Contact.status` (`models/contact.py:89-91`:
  `new, contacted, qualified, converted, lost`). Nothing to build.
- **No stage-name migration for custom pipelines** — skipped by design.

---

## Risks

| Risk | Mitigation |
|---|---|
| ORM `delete-orphan` cascade wipes opportunities if a stage is deleted | Migration uses Core SQL only; `New` is renamed, never deleted; downgrade deletes only the two stages it created, which have no opportunities |
| Migration clobbers an operator's custom pipeline | Exact-name-set predicate; non-matching pipelines skipped and logged |
| `reply_handler` grafts a stray "Booked" stage | Remap to `Visit/Demo Scheduled` in the same commit |
| Auto-open default flip silently disables a workspace that wanted it | Explicit `{"enabled": true}` still wins; new settings endpoint makes it reachable |
| Dashboard open-deal counts drop after archiving | Expected and intended; ROI/closed-won untouched (verified: ROI filters `status == "won"`) |
| CI's empty DB does not exercise the data transform | Dedicated pytest integration test seeding the old shape, asserting upgrade **and** downgrade |
| Prod data loss | `make db.backup.prod` before deploy; nothing is `DELETE`d from `opportunities` |

## Verification

- `backend/tests/services/opportunities/test_default_pipeline.py` — name-agnostic, must still pass unchanged.
- Update `backend/tests/services/opportunities/test_lead_opportunity.py`:
  `test_auto_pipeline_enabled_defaults_on` → asserts **off**; `test_new_lead_lands_in_first_stage`
  must set `{"enabled": True}` explicitly; add a test that the default (no setting) creates **no** card.
- New `backend/tests/migrations/test_pipeline_restructure.py` (integration): seed a workspace with
  the old five stages + one auto-created untouched card + one human-touched card + one custom
  pipeline; run the migration's upgrade and downgrade functions; assert the transform, the
  skip of the custom pipeline, and byte-exact restoration on downgrade.
- New `backend/tests/api/test_auto_pipeline_settings.py` for the GET/PUT endpoint.
- Gates: `make ci.backend`, `make ci.migrations`, `make codegen` then `make ci.codegen`, `make ci.frontend`.
- Eyes: `.ezcoder/eyes/http.sh http://localhost:8000/api/v1/workspaces/<ws>/opportunities/pipelines`
  → confirm six stages in order; POST the public lead-form endpoint → confirm a contact is created
  and **no** opportunity; `.ezcoder/eyes/logs.sh --service backend --grep "auto_pipeline|pipeline_restructure"`.

## Steps

1. Flip the default in `backend/app/services/opportunities/lead_opportunity.py` — `auto_pipeline_enabled()` returns `raw.get("enabled", False)`; update the module docstring (lines 9–12) which currently says "default ON".
2. Replace `DEFAULT_PIPELINE_STAGES` in `backend/app/services/opportunities/default_pipeline.py` with the six new stages, and update the module docstring's description of the entry stage.
3. Remap stage names in `backend/app/services/campaigns/reply_handler.py` `_get_or_create_stage` (lines 314, 328): `BOOKED → "Visit/Demo Scheduled"` (order 1, probability 45), otherwise `"Qualified"` (order 0, probability 25).
4. Add `AutoPipelineSettings` schema plus `GET`/`PUT /api/v1/workspaces/{workspace_id}/auto-pipeline` in `backend/app/api/v1/settings.py`, following the `lead-source-capture` handlers at lines 614–641.
5. Generate the migration with `cd backend && make migrate.new m="pipeline restructure"` so `down_revision` is stamped from the real head.
6. Implement `upgrade()`: create the `pipeline_restructure_backup` scratch table, select pipelines whose stage name set is exactly `{New, Qualified, Proposal, Won, Lost}`, record prior state, rename/reorder stages, insert `Visit/Demo Scheduled` and `Quote Sent / Follow Up`, park `New` as `Unqualified (archived)` at order 6 — all via Core SQL, never the ORM.
7. Implement the opportunity split in the same `upgrade()`: archive auto-created untouched cards (`status='abandoned'`, `is_active=false`), move every other `New` card to `Qualified` with `probability=25` and a `stage_changed` `OpportunityActivity` row.
8. Implement `downgrade()`: replay `pipeline_restructure_backup` to restore opportunity and stage state, `DELETE` the two inserted stages and the migration-written activity rows via Core SQL, then drop the scratch table.
9. Update `backend/tests/services/opportunities/test_lead_opportunity.py` for the inverted default and add a no-setting-creates-no-card case.
10. Add `backend/tests/migrations/test_pipeline_restructure.py` covering upgrade, downgrade restoration, and the custom-pipeline skip.
11. Add `backend/tests/api/test_auto_pipeline_settings.py` for the new GET/PUT endpoint.
12. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit as the endpoint change.
13. Run `make migrate` locally, then probe with `.ezcoder/eyes/http.sh` — pipelines endpoint returns the six stages in order, and a public lead-form POST creates a contact with no opportunity.
14. Run `make ci.all` and fix everything it reports.
