# Lead-source automation: `lead_created` trigger for ls_n2dSPTZe

## Goal
When a **new** lead is created through lead source `ls_n2dSPTZe` (the permholidaylights
Facebook funnel), automatically:
1. Tag the lead **`FB Perm Lighting Lead`**.
2. Text the lead's phone (normalized to E.164):
   > Hi {first_name}, it's Max with Maxteriors — got your permanent roofline lighting estimate. Happy to answer any questions or get your free design consultation booked. When's a good time to reach you?

Fallback trigger: also match leads whose submission `source_detail` = `permholidaylights instant quote`.
`{first_name}` falls back to `there` when blank. Do **not** require `fbclid`/`utm_source`.

## What the codebase already gives us (verified)
- **Automation engine** (`app/workers/automation_worker.py`) supports multi-action automations
  (`add_tag` + `send_sms` together) and two trigger families: **polling** (against contacts) and
  **event** (drained from `automation_events`, emitted via `emit_automation_event`).
- **Actions auto-execute**: automations call the approval gate with `agent_id=None`, and
  `ApprovalGateService.check_and_execute_or_queue` returns `("auto", None)` for `agent_id is None`
  (approval_gate_service.py:236). No human approval needed → SMS/tag run when the worker drains.
- **Tag action** (`_action_apply_tag`) and **SMS action** (`_action_send_sms`) already exist;
  `_render_template` substitutes `{first_name}` etc.
- **Ingestion**: `app/api/v1/lead_form.py::submit_lead` (`POST /api/v1/p/leads/{public_key}`)
  creates the contact, exposes `is_new_lead`, and has `lead_source` + `body.source_detail` in scope.
- **Phone**: `LeadSubmitRequest.validate_phone` already normalizes the *public-form* path to E.164,
  and `TelnyxSMSService.send_message` re-normalizes but **raises** on bad input. Other creation
  paths may store raw numbers, so we normalize defensively in the SMS action with
  `normalize_phone_safe` (returns `None`, never raises). Helper lives in `app/utils/phone.py`.

## What's missing (must build)
- No `lead_created` trigger type.
- Event matching is by `event_type` only — no per-lead-source / `source_detail` filtering.
- SMS action doesn't E.164-normalize before send, and has no `{first_name}` fallback.
- Nothing emits an automation event when a lead is captured.
- The automation record itself doesn't exist for `ls_n2dSPTZe`.

## Design decisions
- **Event-based trigger** `lead_created` (not polling): emitted transactionally from `submit_lead`,
  drained by the worker — mirrors every other event trigger, crash-safe, cheap.
- **Gate emission on `is_new_lead`**: literally matches "any *new* lead created", prevents
  re-texting existing customers, and auto-dedupes rapid re-submissions (2nd+ submits find the
  existing contact → no event). Documented so it can be broadened later if desired.
- **Config filtering with OR semantics**: an automation's `trigger_config` may set
  `lead_source_public_key`, `lead_source_id`, and/or `source_detail`. A `lead_created` event matches
  if **any** configured selector matches the event payload. No selectors configured ⇒ matches every
  lead (workspace-wide), preserving a general "any new lead" trigger.
- **`fallbacks` in action config**: `_render_template` gains an optional `fallbacks` map so blank
  tokens resolve to a default (`{"first_name": "there"}`). Backward-compatible; opt-in per action.
- **Create the automation via an idempotent ops script** (not a migration): the workspace id lives
  in the DB; the operator runs the script against their env. Upsert keyed on
  (workspace, `lead_created`, `trigger_config.lead_source_public_key`).

## Event payload (`lead_created`)
```json
{
  "lead_source_id": "<uuid str>",
  "lead_source_public_key": "ls_n2dSPTZe",
  "source_detail": "<body.source_detail or null>",
  "is_new_lead": true
}
```

## Automation record (created by the ops script)
- `name`: "FB Perm Lighting Lead — auto text"
- `trigger_type`: `lead_created`
- `trigger_config`: `{ lead_source_public_key: "ls_n2dSPTZe", lead_source_id: "<resolved>", source_detail: "permholidaylights instant quote" }`
- `actions`:
  1. `{ "type": "add_tag", "config": { "tag": "FB Perm Lighting Lead" } }`
  2. `{ "type": "send_sms", "config": { "message": "<the SMS copy>", "fallbacks": { "first_name": "there" } } }`
- `is_active`: true

Action order = tag first, then SMS, so an unsendable/invalid phone still gets tagged.

## Files to change
1. `backend/app/services/automations/events.py`
   - `EVENT_LEAD_CREATED = "lead_created"`; add to `AUTOMATION_EVENT_TRIGGERS`.
   - Pure helper `lead_created_event_matches(trigger_config, payload) -> bool` (OR semantics;
     empty selectors ⇒ True; `source_detail` compared case-insensitively, trimmed).
2. `backend/app/schemas/automation.py`
   - Add `"lead_created"` to `AUTOMATION_TRIGGER_TYPES` (feeds the create/update `pattern`).
3. `backend/app/workers/automation_worker.py`
   - Import `normalize_phone_safe`, `EVENT_LEAD_CREATED`, `lead_created_event_matches`.
   - `_process_event`: skip automations whose `lead_created` config doesn't match the payload.
   - `_action_send_sms`: normalize recipient via `normalize_phone_safe`; warn + skip if invalid;
     pass `fallbacks=config.get("fallbacks")` to the renderer.
   - `_render_template`: add optional `fallbacks` param; also thread it from `_action_send_email`.
4. `backend/app/api/v1/lead_form.py`
   - After `await db.flush()`, when `is_new_lead`, `emit_automation_event(..., event_type=EVENT_LEAD_CREATED, contact_id=contact.id, payload=...)` inside a defensive try/except (never break capture).
5. `scripts/ops/setup_lead_automation.py` (new)
   - Resolve `LeadSource` by `public_key`; upsert the automation above; idempotent; `--dry-run`.
     Uses the `backend/scripts/_harness.py` bootstrap pattern + `AsyncSessionLocal`.
6. `frontend/src/types/automation.ts`
   - Add `"lead_created"` to the `AutomationTriggerType` union.
7. `frontend/src/components/automations/automations-page.tsx`
   - Add `lead_created` entry to `triggerTypeConfig` and a "Leads" group in `TRIGGER_OPTIONS`.
8. Codegen: regenerate `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`
   (schema `pattern` changes) and commit both in the same commit.

## Tests
- `backend/tests/services/automations/test_lead_created_matching.py` (unit): OR semantics —
  match by public_key, by source_id, by source_detail (case-insensitive); mismatch ⇒ False;
  no-selectors ⇒ True.
- Extend `backend/tests/workers/test_automation_event_triggers.py` (unit):
  `_render_template` applies `fallbacks` (`{first_name}`→`there` when blank; real name wins);
  `_action_send_sms` skips on unnormalizable phone and normalizes a raw US number before send
  (assert the value passed to a mocked provider is `+1XXXXXXXXXX`).
- Extend `backend/tests/workers/test_automation_events_integration.py` (integration):
  lead_created event with matching `trigger_config` → tag applied; mismatched config → **not** applied.
- `backend/tests/api/` (integration): drive `submit_lead` (real DB, configured lead source with an
  allowed test origin + a `lead_created` automation), then drain the worker and assert the tag lands
  and no event is emitted for a deduped returning submission.

## Verification
- `.ezcoder/eyes/http.sh` POST to `/api/v1/p/leads/<public_key>` on local backend → 200; then
  `.ezcoder/eyes/logs.sh --service backend --grep "automation|lead_created"` to see the drain, and
  `.ezcoder/eyes/mail.sh`/logs to confirm the SMS attempt.
- `make ci.codegen` (no drift after commit), `make ci.backend`, `make ci.frontend`.

## Risks / notes
- If lead source `ls_n2dSPTZe`'s own post-capture `action` is already `auto_text`, leads would get
  two texts. The ops script prints a warning if the source's `action` is `auto_text`/`auto_call`;
  recommend setting it to `collect` so the automation owns messaging.
- ~60s worker poll delay before the SMS sends (acceptable for a "when's a good time" text).
- No DB migration (automations table already supports the JSON config/actions).

## Steps
1. Add `EVENT_LEAD_CREATED`, extend `AUTOMATION_EVENT_TRIGGERS`, and add the pure
   `lead_created_event_matches` helper in `backend/app/services/automations/events.py`.
2. Add `"lead_created"` to `AUTOMATION_TRIGGER_TYPES` in `backend/app/schemas/automation.py`.
3. In `backend/app/workers/automation_worker.py`: add `fallbacks` to `_render_template`; normalize
   phone + pass fallbacks in `_action_send_sms` (and thread fallbacks in `_action_send_email`);
   filter `lead_created` automations by config in `_process_event`; add the new imports.
4. Emit `lead_created` for new leads in `backend/app/api/v1/lead_form.py::submit_lead`
   (after flush, gated on `is_new_lead`, defensively wrapped).
5. Add frontend trigger type + UI config: `frontend/src/types/automation.ts` and
   `frontend/src/components/automations/automations-page.tsx`.
6. Create `scripts/ops/setup_lead_automation.py` (idempotent upsert, `--dry-run`, double-text warning).
7. Add unit tests (matching + render fallbacks + SMS normalization) and integration tests
   (event config filtering + `submit_lead` emit/dedupe).
8. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`.
9. Run `make ci.backend`, `make ci.frontend`, `make ci.codegen`; fix any failures.
10. Verify locally with `.ezcoder/eyes/http.sh` (lead POST) + `.ezcoder/eyes/logs.sh` (worker drain)
    and, where possible, the SMS attempt.
