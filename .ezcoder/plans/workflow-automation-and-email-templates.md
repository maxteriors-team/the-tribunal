# Workflow Automation (GoHighLevel-style) + Transactional HTML Email Templates

Status: awaiting approval · Written against `feat/landscape-lighting-handoff` (142 modified files already in tree)

## What exists today

| Piece | File | State |
|---|---|---|
| Automation model | `backend/app/models/automation.py` | `actions` = flat JSONB `[{type, config}]` |
| Execution model | `backend/app/models/automation_execution.py` | Has `status`, `scheduled_for`, and an unused index `ix_automation_executions_status_scheduled_for` |
| Engine | `backend/app/workers/automation_worker.py` (1365 lines) | 3 trigger families, 10 action types, sequential dispatch |
| Triggers | `services/automations/events.py`, `conditions.py` | 24 trigger ids, event bus + polling + workspace-condition |
| Kill switch | `services/automations/opt_out.py` | `no-automation` tag, gated at `emit_automation_event` |
| Email | `backend/app/services/email.py` | 6 functions, each hand-rolling its own inline-CSS HTML |

## Findings that shape the design

1. **`wait` is a dead end — this is a live bug, not a missing feature.**
   `_run_actions` (worker line ~652) sets `execution.status = "scheduled"` + `scheduled_for`, then `return`s. **Nothing ever queries that status back.** Verified: the only reads of `AutomationExecution` are the two dedupe lookups and the polling exclusion sub-query. So any automation containing a `wait` step silently executes its steps up to the wait and then stops forever. Multi-step drips — the centre of GHL's product — cannot work at all today.

2. **Resume needs persisted state.** The event `payload` (which supplies `{rating}`, `{stage}` template tokens) is passed as an in-memory argument. After a wait spans poll cycles that dict is gone, so resumed steps would render blank tokens. Resume requires persisting both a step cursor *and* the payload.

3. **Polling triggers bypass the `no-automation` kill switch.** `_get_trigger_contacts` builds `base_filters` from workspace + not-already-executed only. The tag is enforced in `emit_automation_event`, which polling triggers never touch. A customer tagged `no-automation` still gets texted by `never_booked` / `no_show` / `contact_tagged` automations.

4. **Automation email has no unsubscribe footer.** `send_campaign_email` renders a compliant footer via `_campaign_html`; `send_automation_email` calls `_text_to_html` with no footer, no workspace context, no suppression check. A multi-step nurture drip is marketing email in substance, so this is a CAN-SPAM exposure on the exact path this work expands.

5. **Email HTML matches nothing.** All 6 builders use generic greys (`#1a1a1a`, `#f8f9fa`, `#eee`). The product brand is amber `#ffb90a` on near-black `#0a0a0a` (`frontend/src/app/globals.css`). There is no shared layout, no stored templates, no preview.

6. **Polling triggers fire once per contact, ever.** The `already_executed` sub-query has no time bound, so re-entry is impossible — GHL exposes this as a per-workflow toggle.

## Design decisions

**Steps stay a flat JSONB list; branching uses goto, not nesting.**
Nested branch bodies would make the resume cursor a path rather than an integer. Instead every step gains an optional stable `id`, and a `branch` step carries `{conditions, then_goto, else_goto}` naming a target step `id` (or `null` = fall through / end). The cursor stays a plain int, so resume after a wait is a single integer lookup. Existing rows — a list of `{type, config}` with no ids — keep running byte-identically, so no data migration of `actions` is needed.

**Branch conditions reuse `contact_filters.py` rather than a new evaluator.**
That module builds SQL (`Select` / `ColumnElement`), not in-memory predicates, so the worker will evaluate a branch by running the existing filter rules scoped to a single contact (`WHERE id = :contact_id AND <rules>`) and checking for a row. One PK-indexed query per branch step, and — the real payoff — workflow branches, the contacts list, and segments all speak one rule language, so the frontend reuses the existing filter builder UI. `_COLUMN_MAP` already exposes `sms_consent_status`, which makes consent-aware branching possible for free.

**Loop safety is mandatory.** Goto allows cycles. Two bounds: max 50 steps per execution per cycle, and max 200 total resumes per execution, after which the execution is marked `failed` with an explicit error. An unbounded workflow loop that sends SMS is the one failure mode this feature must never have.

**One send chokepoint.** All workflow sends route through a single `workflow_send_allowed()` gate checking `no-automation`, `GlobalOptOut`, and quiet hours — fixing finding 3 for polling triggers at the same time.

## Compliance controls built into the feature

Inline gate, not a full audit — these ship *with* the code, per `compliance-guard`:

- Unsubscribe footer becomes **structural** in the shared email layout, so a template physically cannot render without one (fixes finding 4).
- The single `workflow_send_allowed()` gate covers all three trigger families (fixes finding 3).
- Quiet-hours enforcement reuses the existing `Campaign.quiet_hours_*` convention for workflow SMS (TCPA 8am–9pm local).
- A regression test asserts every workflow email send path emits an unsubscribe link.

Not legal advice; `COMPLIANCE.md` is not created by this work — these are engineering controls on the path being expanded.

## Phases

**Phase 1 — Resumable multi-step engine** (the load-bearing fix; everything else builds on it)
Migration adds `step_index`, `context` JSONB, `resume_count` to `automation_executions`. Worker gains `_resume_scheduled_executions()` as step 0 of the poll cycle, `_run_actions` becomes cursor-driven with loop bounds, `wait` gains `minutes`/`hours`/`days`.

**Phase 2 — Branching + workflow settings**
`branch` step type backed by `contact_filters`. `Automation` gains `settings` JSONB: `allow_reentry`, `reentry_cooldown_days`, `quiet_hours`, `stop_on_reply`.

**Phase 3 — HTML email template system**
`EmailTemplate` model + brand-matched table-based layout renderer + preview endpoint + `send_email` action accepting `template_id`. Existing 6 builders in `email.py` refactored onto the shared layout.

**Phase 4 — New actions + frontend**
Actions: `webhook`, `notify_user`, `remove_tag`, `update_contact_field`, `create_opportunity`, `add_note`. Frontend step builder (branch editor, wait editor, template picker) + execution history view.

## Risks

- **Worker is 1365 lines and central.** Phase 1 rewrites its hottest path. Mitigation: cursor logic extracted into a pure, separately-tested module (`services/automations/runner.py`) so the branching/looping rules are unit-testable without a database — matching the existing split used by `conditions.py` and `events.py`.
- **Re-entry changes dedupe semantics.** The partial unique index `uq_automation_execution_contact` enforces one row per (automation, contact). `allow_reentry` requires relaxing it to include a run discriminator; migration must be reversible (`make ci.migrations` gates this).
- **Email rendering must survive Outlook** — tables + inline CSS only, no flex/grid.
- **Dirty tree**: 142 modified files already present. All new logic lands in new modules where possible to stay reviewable.

## Verification

- `backend/tests/services/automations/test_runner.py` — pure cursor/branch/loop-bound tests
- `backend/tests/workers/test_automation_resume.py` — wait → resume across cycles, payload survives
- `backend/tests/services/test_email_templates.py` — render + unsubscribe-footer regression
- `.ezcoder/eyes/http.sh` against the new template preview + automation endpoints
- `.ezcoder/eyes/mail.sh clear` → trigger → `latest` to confirm brand styling and footer
- `make ci.codegen` (commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together), then `make ci.all`

## Steps

1. Add `step_index`, `context` JSONB, and `resume_count` columns to `backend/app/models/automation_execution.py`, and generate the reversible migration with `make migrate.new m="automation execution resume state"`.
2. Create `backend/app/services/automations/runner.py` with pure, DB-free cursor logic: step-id resolution, goto targets, and the 50-steps-per-cycle / 200-resume bounds.
3. Add `backend/tests/services/automations/test_runner.py` covering forward execution, goto jumps, cycle detection, and both loop bounds.
4. Refactor `_run_actions` in `backend/app/workers/automation_worker.py` to be cursor-driven, persisting `step_index` and `context` on every wait.
5. Add `_resume_scheduled_executions()` to the worker as step 0 of `_process_items`, querying `status == "scheduled" AND scheduled_for <= now` via the existing index.
6. Extend the `wait` action to accept `minutes`, `hours`, and `days`, keeping `hours` as the backward-compatible default.
7. Add `backend/tests/workers/test_automation_resume.py` proving a wait resumes on a later cycle with event payload tokens intact.
8. Create `backend/app/services/automations/send_gate.py` exposing `workflow_send_allowed()` checking `no-automation`, `GlobalOptOut`, and quiet hours.
9. Route `_action_send_sms` and `_action_send_email` through `workflow_send_allowed()`, and add the `no-automation` filter to `_get_trigger_contacts` base filters.
10. Add the `branch` step type to the runner, evaluating conditions through `apply_contact_filters` scoped to a single contact id.
11. Add a `settings` JSONB column to `backend/app/models/automation.py` with `allow_reentry`, `reentry_cooldown_days`, `quiet_hours`, and `stop_on_reply`, plus its migration.
12. Relax the `uq_automation_execution_contact` partial unique index to admit re-entry runs, with a reversible migration.
13. Implement re-entry and `stop_on_reply` handling in the worker's polling path and event drain.
14. Create `backend/app/models/email_template.py` (`EmailTemplate`: workspace, name, subject, body, category, is_active) and its migration.
15. Create `backend/app/services/email_layout.py` — a table-based, inline-CSS layout using the `globals.css` brand tokens, with a structurally non-removable unsubscribe/footer slot.
16. Refactor the 6 HTML builders in `backend/app/services/email.py` onto the shared layout, and add the unsubscribe footer to `send_automation_email`.
17. Add `backend/tests/services/test_email_templates.py` covering rendering, token substitution, HTML escaping, and the unsubscribe-footer regression.
18. Add `backend/app/api/v1/email_templates.py` with CRUD plus a preview endpoint, register it in `backend/app/api/v1/router.py`, and add schemas in `backend/app/schemas/email_template.py`.
19. Extend the `send_email` action to accept `template_id`, falling back to the existing inline subject/body config.
20. Add the new action types (`webhook`, `notify_user`, `remove_tag`, `update_contact_field`, `create_opportunity`, `add_note`) to `AUTOMATION_ACTION_TYPES` in `backend/app/schemas/automation.py` and implement each handler in the worker.
21. Run `make codegen`, then commit `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together in one commit.
22. Update `frontend/src/types/automation.ts` with the new action types, step `id`, branch config, and workflow settings.
23. Build the step builder UI in `frontend/src/components/automations/` — branch editor reusing the existing contact-filter components, wait editor, and email-template picker.
24. Add an execution-history view showing run status, current step, and errors, backed by a new executions list endpoint.
25. Add `frontend/src/components/email-templates/` with a template editor and live preview iframe.
26. Verify at runtime with `.ezcoder/eyes/http.sh` on the new endpoints and `.ezcoder/eyes/mail.sh` on a triggered send, confirming brand styling and the unsubscribe footer.
27. Run `make ci.all` and fix any failures.
