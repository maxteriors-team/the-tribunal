# Workflow Builder — Feature Parity Catalog & Design

**Status:** design proposal, nothing built yet
**Date:** September 2026
**Reference for parity:** GoHighLevel Workflows (triggers, actions, settings, AI Builder)

---

## 0. The headline finding

The Tribunal is much further along than "we need a workflow builder" implies. There is
already a real workflow engine:

| Piece | File | What it does |
|---|---|---|
| Definition | `backend/app/models/automation.py` | `trigger_type` + `trigger_config` + `actions` (JSONB list), workspace-scoped |
| Event bus | `backend/app/models/automation_event.py` | Durable queue of domain events, `pending/processed/failed` |
| Run state | `backend/app/models/automation_execution.py` | **Resumable**: `step_index`, `context`, `resume_count`, `scheduled_for` |
| Step machine | `backend/app/services/automations/runner.py` | `normalize_steps`, `resolve_goto`, `branch_targets`, `wait_duration` |
| Branch logic | `backend/app/services/automations/branching.py` | Reuses `contact_filters` as the one rule language |
| State triggers | `backend/app/services/automations/conditions.py` | `backlog_below_threshold` w/ mandatory cooldown |
| Executor | `backend/app/workers/automation_worker.py` | ~1,950 lines, dispatch table + approval gate |
| AI authoring | `backend/app/services/ai/crm_assistant/_automation_tools.py` | create/update/enable/disable, name→UUID resolution, validation |
| UI | `frontend/src/components/automations/workflow-steps-editor.tsx` | Step editor |

**So the real question is not "how do we build this" — it's "what's missing, and why does
the assistant still not feel like it can just build me a workflow."**

Two answers, and the second is the important one:

1. **Catalog gaps.** 28 triggers / 9 actions today. Scoped GHL parity for a home-service
   business is ~45 triggers / ~30 actions.
2. **Structural gaps.** No versioning, no re-entry policy, no trigger filters, no
   goal events, no quiet hours, no simulation. These are what make an AI-authored
   workflow *trustworthy enough to turn on*. Catalog is the easy half.

And the strategic prize, which is buried in `backend/app/workers/`:

> There are **~12 hardcoded bespoke workers** — `unsold_quote_worker`,
> `never_booked_worker`, `noshow_reengagement_worker`, `post_estimate_followup_worker`,
> `prebooking_worker`, `review_request_worker`, `recurring_job_worker`, `reminder_worker`,
> `followup_worker`, `deal_lifecycle_worker`, `drip_campaign_worker`, `nudge_worker`.
>
> Every one of these is a workflow that was hand-written because the engine couldn't
> express it. **The goal state is that all twelve are rows in `automations`**, authored
> once, editable by Max in the UI or by asking the assistant. That is the difference
> between a CRM with automations and a CRM that is an automation platform.

---

# PART 1 — The parity catalog

GoHighLevel exposes 60+ triggers across 12+ categories and ~90 actions across 14. A large
fraction is irrelevant to an outdoor-lighting company: Courses, Communities, Certificates,
Affiliates, Ecommerce/Shopify, Memberships. **Parity should be scoped, not literal.** The
catalog below is GHL's model filtered to what a home-service CRM needs, and marked against
what The Tribunal has today.

Legend: ✅ exists · 🟡 partial · ❌ missing · ⭐ high value for Maxteriors specifically

## 1.1 Triggers

### A. Record lifecycle (contact-centric)

| Trigger | Fires when | Status |
|---|---|---|
| `contact_created` | New contact row, any source | ❌ |
| `contact_field_changed` | Named field changes to a value | ❌ — blocked on custom fields, see §5.0 |
| `contact_tagged` | Tag applied | ✅ |
| `contact_tag_removed` | Tag removed | ❌ |
| `contact_dnd_changed` | DND / consent toggled | ❌ ⭐ (compliance) |
| `contact_engagement_score` | Score crosses threshold | ❌ |
| `note_added` | Note written on contact | ❌ |
| `task_added` / `task_reminder` / `task_completed` | Task lifecycle | ❌ ⭐ (callback tasks) |

### B. Lead capture & attribution

| Trigger | Fires when | Status |
|---|---|---|
| `lead_created` | Public form ingestion | ✅ |
| `lead_qualified` | Qualification signals met | ✅ |
| `form_submitted` | A *specific named* form | 🟡 (only generic `lead_created`) |
| `facebook_lead_form_submitted` | Meta lead ad | ❌ ⭐ (running $200/day) |
| `google_lead_form_submitted` | Google Ads lead form | ❌ ⭐ |
| `inbound_webhook` | External POST to a per-workflow URL | ❌ ⭐ (integration escape hatch) |
| `page_view` / `trigger_link_clicked` | Tracked URL or link hit | ❌ |
| `prospect_generated` | Prospect record created | 🟡 (`lead_prospect` model exists) |

### C. Conversation & engagement

| Trigger | Fires when | Status |
|---|---|---|
| `customer_replied` | Inbound on any channel | ❌ ⭐⭐ **most important gap** |
| `missed_call` | Inbound call unanswered | ✅ |
| `call_details` | Call logged, filterable by outcome/duration | ❌ ⭐ |
| `transcript_generated` | Call/voicemail transcript ready | ❌ ⭐ (you already do transcript analysis) |
| `email_event` | delivered / opened / clicked / bounced / spam / unsub | ❌ — **cheap**: Resend webhooks already land in `app/api/webhooks/resend.py`, just needs event emission |
| `sms_error` | Carrier error on outbound | ❌ ⭐ (deliverability alerting) |
| `number_validation` | Landline/mobile/invalid result | ❌ |
| `conversation_ai_event` | AI agent hit a defined outcome | 🟡 (agents exist, no trigger) |

### D. Appointments

| Trigger | Fires when | Status |
|---|---|---|
| `appointment_booked` | Booked | ✅ |
| `booking_created` | Polling equivalent | ✅ |
| `appointment_status_changed` | confirmed / rescheduled / cancelled / showed / **completed** | 🟡 (`no_show` only) |
| `appointment_reminder_offset` | N hours before `event_start` | ❌ ⭐ (hardcoded in `reminder_worker`) |

### E. Pipeline & opportunity

| Trigger | Fires when | Status |
|---|---|---|
| `opportunity_created` | New opp | ✅ |
| `deal_stage_changed` | Stage moved | ✅ |
| `opportunity_status_changed` | Open → Won/Lost/Abandoned | 🟡 |
| `opportunity_field_changed` | Value/owner/custom field changed | ❌ |
| `stale_opportunity` | No activity for N days in stage X | ❌ ⭐⭐ (hardcoded in `unsold_quote_worker`) |

### F. Money

| Trigger | Fires when | Status |
|---|---|---|
| `quote_sent` / `quote_approved` / `quote_declined` / `quote_converted` | Estimate lifecycle | ✅ |
| `invoice_sent` / `invoice_paid` | Invoice lifecycle | ✅ |
| `invoice_overdue` | Past due by N days | ❌ ⭐ |
| `payment_received` | Payment captured (incl. deposit) | 🟡 |
| `payment_failed` / `refund_issued` | Failure / refund | ❌ ⭐ (50% deposits, GreenSky) |
| `financing_status_changed` | GreenSky approved/declined/expired | ❌ ⭐⭐ (per financing project) |
| `document_signed` | Contract e-signed | ❌ ⭐ |
| `subscription_event` | Recurring plan created/paused/cancelled | ❌ (matters if maintenance plans ship) |

### G. Job / field service

| Trigger | Fires when | Status |
|---|---|---|
| `job_scheduled` / `job_completed` | Job lifecycle | ✅ |
| `job_started` / `job_cancelled` / `job_rescheduled` | Rest of lifecycle | ❌ |
| `crew_assigned` | Assignment changed | ❌ |
| `recurring_job_due` | Maintenance interval reached | 🟡 (`recurring_job_worker` hardcoded) |

### H. Reputation

| Trigger | Fires when | Status |
|---|---|---|
| `review_received` | New review, filterable by rating | ✅ |
| `review_request_response` | Response to a request | ✅ |
| `review_not_left` | Requested, N days, no review | ❌ |

### I. Time & state (no contact required)

| Trigger | Fires when | Status |
|---|---|---|
| `scheduler` | Cron — "every Monday 9am", "Sept 1 annually" | ❌ ⭐⭐ **the seasonal gap** |
| `date_field_offset` | N days before/after any date field | ❌ ⭐⭐ (install anniversary, warranty expiry) — partly blocked on custom fields, see §5.0 |
| `birthday_reminder` | Contact birthday ± offset | ❌ |
| `backlog_below_threshold` | Capacity gauge low | ✅ (nice — GHL has no equivalent) |
| `custom_trigger` | Named internal event, fired by another workflow | ❌ ⭐ (composition) |

> **Why ⭐⭐ on `scheduler` and `date_field_offset`:** Christmas lighting must be *sold*
> Sept–Oct because Maxteriors owns the lights and inventory must be locked early. "On
> Sept 1, enroll everyone who bought Christmas lighting last year" and "365 days after
> install, offer a tune-up" are the two highest-revenue workflows in the business and
> **neither is expressible today**. Everything else in this catalog is secondary to these.

## 1.2 Actions

### A. Communication
`send_sms` ✅ · `send_email` ✅ · `make_call` ✅ · `send_voicemail_drop` ❌ ·
`send_internal_notification` ❌ ⭐ (push/email/Slack to a user) · `send_review_request` 🟡
(worker exists, not an action) · `send_manual_action` ❌ (queue a human task in an
automated flow) · `hand_off_to_ai_agent` 🟡

### B. Record mutation
`apply_tag` ✅ · `remove_tag` ❌ · `update_contact_field` ❌ ⭐ · `add_note` ❌ ·
`create_task` ❌ ⭐⭐ (this is the "call me" callback task from the product brief) ·
`assign_to_user` ❌ ⭐ · `remove_assigned_user` ❌ · `set_dnd` ❌ ⭐ (compliance) ·
`create_contact` ❌ · `find_contact` ❌

### C. Pipeline & money
`move_to_stage` ✅ · `create_opportunity` ❌ · `update_opportunity` ❌ ·
`remove_opportunity` ❌ · `send_estimate` ❌ ⭐ · `send_invoice` ❌ ⭐ ·
`charge_deposit` ❌ ⭐ (50% deposit rule) · `send_document_for_signature` ❌

### D. Scheduling
`generate_booking_link` ❌ ⭐ (one-time link, protects the calendar) ·
`update_appointment_status` ❌ · `schedule_job` ❌

### E. Control flow — **the structural half**
`wait` (duration) ✅ · `branch` (2-way) ✅ · `goto` ✅ (via `then_goto`/`else_goto`) ·
`wait_until_datetime` ❌ · `wait_for_event` ❌ ⭐⭐ · `goal_event` ❌ ⭐⭐ ·
`if_else_multi` (N-way) ❌ ⭐ · `split_test` ❌ · `drip_mode` ❌ ⭐ ·
`remove_from_workflow` ❌ · `goto_workflow` ❌ ⭐ (composition) ·
`fire_custom_trigger` ❌ · `end_workflow` ✅ (`GOTO_END`)

### F. Data & integration
`outbound_webhook` ❌ ⭐ · `http_request` ❌ · `ai_prompt_step` ❌ ⭐⭐ (see §3.6) ·
`math_operation` ❌ · `format_text` ❌ · `google_sheets` ❌ ·
`add_to_meta_custom_audience` ❌ ⭐ (closes the ad loop) · `meta_conversions_api` ❌ ⭐⭐
(server-side conversion — directly improves the $200/day Meta spend)

## 1.3 Workflow-level settings — **all ❌ today**

GHL's settings panel is small but every item exists because someone got burned. All six
are missing from `Automation`:

| Setting | What it prevents |
|---|---|
| **Allow re-entry** | Today: polling triggers are unique per `(automation, contact)` *forever* (`uq_automation_execution_contact`). Re-entry is hardcoded to "never". A customer who buys twice never gets the second onboarding. |
| **Stop on response** | Continuing to blast a lead who already replied. The single most embarrassing automation failure. |
| **Quiet hours / time window + timezone** | 3am SMS. Also a TCPA exposure. |
| **Sender identity** (from name/email/number) | Replies landing on a number nobody watches. |
| **Mark conversation as read** | Automated sends cluttering the human inbox. |
| **Allow multiple opportunities** | Duplicate opps per contact. |

---

# PART 2 — Structural gaps (ranked by risk)

### G1. No versioning — editing a live workflow corrupts in-flight runs ⚠️ **correctness bug**

`AutomationExecution.step_index` is an integer cursor into `automations.actions`. If Max
edits a workflow while contacts are parked in a `wait`, those cursors now point at
*different steps*. `runner.step_at()` guards out-of-range, but not "index 3 used to be
'send follow-up SMS' and is now 'move to Closed Lost'."

**Fix:** `automation_versions` table. Executions pin `version_id`. Draft → publish.
In-flight runs finish on the version they started on. This is a prerequisite for AI
authoring — you cannot let an LLM edit a live workflow without it.

### G2. Single trigger per workflow
`trigger_type` is one string. "When a quote is declined **or** goes stale 14 days" needs
two workflows today. Needs `automation_triggers` as a child table.

### G3. No trigger-level filters
Every trigger fires for every matching record, then you branch. GHL filters at the trigger
(`Contact Tag = "christmas-2025"`), which is cheaper and far more readable. The rule
language already exists (`contact_filters`) — just needs to be attached to the trigger.

### G4. Branching is jump-based, not structural
`then_goto`/`else_goto` into a flat array is a GOTO. It works (and `resolve_goto` handles
dangling targets safely), but it does not render as a tree, cannot express N-way splits,
and is hostile to both a canvas UI and an LLM. Needs a nested/graph representation with
the flat form kept as the compiled artifact.

### G5. No goal events / wait-for-event
Everything is duration-based. Cannot express "wait up to 3 days for them to book, but the
moment they book, jump to the confirmation branch." This is the single most useful control
primitive GHL has and it is entirely absent.

### G6. Polling latency
Worker cycles on a timer. Speed-to-lead is a step function — the industry number is that
roughly a third to half of sales go to whoever responds first, and the curve is steepest in
the first five minutes. `lead_created` should be push, not poll.

### G7. No observability
No execution history UI, no per-step counters, no "why didn't this fire." GHL users debug
via Execution Logs constantly. Without this, an AI-authored workflow is unfalsifiable.

### G8. No test/simulation mode
Cannot dry-run. This is the hard blocker on trusting AI output (see §4.6).

---

# PART 3 — Engine design

## 3.1 Schema

```
automations                  (unchanged: id, workspace_id, name, description, is_active)
  ├── settings         JSONB  NEW  — re-entry, stop_on_response, quiet_hours, sender, tz
  └── current_version_id      NEW  → automation_versions.id

automation_versions          NEW
  id, automation_id, version_number,
  status            'draft' | 'published' | 'archived'
  graph             JSONB   -- the authored tree (source of truth, what the UI edits)
  compiled_steps    JSONB   -- flat list w/ ids + gotos (what the runner executes)
  settings_snapshot JSONB
  created_by_user_id, created_by  'human' | 'assistant'
  authoring_prompt  TEXT    -- the NL request, when assistant-authored
  published_at, created_at

automation_triggers          NEW  (replaces trigger_type/trigger_config)
  id, automation_version_id, trigger_type, config JSONB,
  filter_rules JSONB, filter_logic  -- reuses contact_filters language

automation_executions        EXTEND
  + version_id            → automation_versions.id     -- G1 fix
  + waiting_for           JSONB  -- goal/wait-for-event spec
  + goal_satisfied_at
  + entered_at, exited_at, exit_reason

automation_step_runs         NEW  -- observability (G7)
  id, execution_id, step_id, step_type, status, started_at,
  finished_at, error, output JSONB
```

Keep `compiled_steps` in the *exact current shape* so `runner.normalize_steps` and the
worker's dispatch table need no changes. The graph is new; the executable artifact is not.
This is what makes the migration incremental rather than a rewrite.

## 3.2 Graph → compiled steps

Author in a tree, execute a flat list. The compiler is deterministic and pure — which
means it is unit-testable and, critically, it is the thing that turns fuzzy LLM output into
something guaranteed-executable.

```
Graph (authored)                    Compiled (executed)
─────────────────                   ───────────────────
trigger: quote_sent                 [
  → wait 3 days                       {id:"s1", type:"wait",   config:{days:3}},
  → if: quote_approved                {id:"s2", type:"branch", config:{
      yes → send_sms "thanks"                    conditions:[...],
      no  → send_sms "still good?"               then_goto:"s3", else_goto:"s4"}},
          → wait 4 days               {id:"s3", type:"send_sms", config:{...}},
          → move_to_stage "Cold"      {id:"s4", type:"send_sms", config:{...}},
                                      {id:"s5", type:"wait",   config:{days:4}},
                                      {id:"s6", type:"move_to_stage", config:{...}}
                                    ]
```

Compiler responsibilities:
1. Assign stable step ids (stable across recompiles — diffing depends on it)
2. Linearize branches, wire `then_goto`/`else_goto`
3. Terminate leaf branches with `GOTO_END` rather than letting them fall through
4. Reject cycles that lack a `wait` (the `MAX_RESUMES` budget is a backstop, not a design)
5. Resolve names → UUIDs (already implemented in `_automation_tools.py`)

## 3.3 Goal events (G5)

A goal is a **subscription registered when the run enters a waiting state**, not a polled
condition:

```json
{ "type": "wait",
  "config": {
    "days": 3,
    "goals": [
      {"event": "appointment_booked", "goto": "confirmed"},
      {"event": "customer_replied",   "goto": "human_takeover"}
    ],
    "on_timeout_goto": "followup_2"
  }}
```

On entering the wait, write rows to `automation_goal_subscriptions (execution_id,
event_type, goto_step_id)`. The existing event drain already touches every
`AutomationEvent` — it checks subscriptions in the same pass and yanks the execution to the
target step. Almost free, given the event bus already exists.

`stop_on_response` is then just an implicit workspace-default goal on `customer_replied`
that routes to `__end__`. One mechanism, two features.

## 3.4 Re-entry (fixes the hardcoded G1 behaviour)

Replace the "unique forever" partial index with a policy on `settings`:

- `once_ever` — current behaviour, keep as an option
- `once_per_trigger_event` — current event-trigger behaviour
- `always`
- `cooldown_days: N` — the useful default. "Ask for a review, but never twice in 90 days."

Migration: existing rows get `once_ever` so nothing changes behaviour on deploy.

## 3.5 Quiet hours

Enforced at **send time in the worker**, not at schedule time — a message scheduled at 4pm
for a 3-day wait must still respect quiet hours when it actually fires. Deferred sends roll
to the next valid window rather than dropping. Workspace default, overridable per workflow,
with an `ignore_quiet_hours` escape for genuinely urgent internal notifications.

## 3.6 The `ai_prompt` step

Worth calling out because it is where The Tribunal can *exceed* parity rather than match it.
A step that runs an LLM call mid-workflow with the contact + conversation in context, and
writes its output into `execution.context` for later steps to interpolate:

```json
{"type": "ai_prompt",
 "config": {
   "prompt": "Summarize this lead's stated needs in one sentence for the crew.",
   "output_key": "lead_summary",
   "max_tokens": 150 }}
```

Then `{lead_summary}` is available to every downstream `send_sms` / `create_task`. Combined
with the brand-voice SOP (`docs/brand-voice-va-guide.md`) as a system prompt, this gives
on-brand generated copy inside automations — which is the thing GHL's `AI Prompt` action
conspicuously does *not* do well.

---

# PART 4 — AI-assisted authoring

## 4.1 The actual problem

`create_automation` already exists as an assistant tool. So why doesn't it feel like the
assistant can build workflows? Because a single JSON-emitting tool call gives you output
that is **plausible but unverifiable**. The LLM writes something that looks like a
workflow; Max has no way to know whether it will text 400 people at 2am. So he doesn't turn
it on. So the feature doesn't exist in practice.

**The fix is not a better prompt. It is a pipeline where the LLM is responsible only for
the fuzzy part, and deterministic code is responsible for everything that can hurt you.**

## 4.2 Pipeline

```
  NL request
      │
  ┌───▼─────────────────────────┐
  │ 1. CLARIFY (≤3 questions)   │  LLM   — only when genuinely underspecified
  ├─────────────────────────────┤
  │ 2. GROUND                   │  code  — inject real pipelines, stages, tags,
  │                             │          agents, campaigns, custom fields
  ├─────────────────────────────┤
  │ 3. RETRIEVE RECIPES         │  code  — k-NN over the recipe library
  ├─────────────────────────────┤
  │ 4. GENERATE IR              │  LLM   — typed graph, *names not UUIDs*
  ├─────────────────────────────┤
  │ 5. COMPILE                  │  code  — resolve, linearize, inject safety
  ├─────────────────────────────┤
  │ 6. LINT                     │  code  — hard gate, see §4.5
  ├─────────────────────────────┤
  │ 7. SIMULATE                 │  code  — dry-run on real history, see §4.6
  ├─────────────────────────────┤
  │ 8. PREVIEW + CONFIRM        │  human — plain-English summary + counts
  ├─────────────────────────────┤
  │ 9. SAVE AS DRAFT            │  code  — is_active=False (already the behaviour)
  └─────────────────────────────┘
```

Steps 2, 5, 6, 7 are deterministic. The LLM only does 1 and 4.

**Model tiering** follows the convention already in `config.py`: the balanced assistant tier
(`openai_assistant_model`) for step 4 generation, the cheap tier
(`openai_assistant_summary_model`) for step 8's plain-English summary. Prompts belong in
the existing `PromptVersion` registry so workflow-authoring prompts get the same
versioning, rollback, and `BanditDecision` A/B machinery as every other prompt in the
product — authoring quality then improves the same way agent quality does, by measurement
rather than by vibes.

## 4.3 The IR the LLM emits

Never let the LLM emit UUIDs or the storage format. It emits a small, typed, *named*
language — which means every reference is checkable and every error is a clean
"stage 'Quoted' not found in pipeline 'Sales'; did you mean 'Quote Sent'?"

```json
{
  "name": "Christmas re-book — last year's customers",
  "trigger": {
    "type": "scheduler",
    "cron": "0 9 1 9 *",
    "audience": {"filter_rules": [{"field":"tag","op":"in","value":["christmas-2025"]}]}
  },
  "settings": {
    "re_entry": {"mode": "cooldown_days", "days": 300},
    "stop_on_response": true,
    "quiet_hours": {"start": "20:00", "end": "09:00", "tz": "America/Detroit"}
  },
  "steps": [
    {"type": "send_sms", "template": "Christmas install spots open up..."},
    {"type": "wait", "days": 4,
     "goals": [{"event": "customer_replied", "goto": "end"}]},
    {"type": "if", "condition": {"field": "tag", "op": "not_in", "value": ["replied-2026"]},
     "then": [{"type": "send_email", "template": "..."}],
     "else": []}
  ]
}
```

## 4.4 The recipe library — the highest-leverage piece

Do not have the LLM free-generate. Retrieve from a curated library of Maxteriors-shaped
workflows and let it adapt. Every recipe is a real, working, linted workflow:

**Speed-to-lead** · **Quote follow-up ladder** · **Unsold quote revival (evening demo
angle)** · **Review request after job complete** · **Christmas lighting seasonal sell**
· **Install anniversary / tune-up** · **No-show recovery** · **Missed call text-back** ·
**Deposit chase** · **Financing status follow-up (GreenSky)** · **Backlog-triggered
reactivation** · **Neighbor / jobsite-radius outreach** · **Referral partner nudge** ·
**Warranty expiry**

Two things fall out of this for free:
- Every recipe is also a **template Max can install in one click**, with no AI involved.
- **The 12 hardcoded workers become the first 12 recipes.** Write them as workflow
  definitions, verify they produce identical behaviour, delete the workers. That is the
  migration path and the acceptance test simultaneously.

All generated copy must pass the brand-voice rules — plain words, short sentences,
specifics over adjectives, never dodge price, signed "— Max" — and **must not contain any
of the banned follow-up filler phrases**. Every follow-up step opens with new information
(a lead time, a season, an unchanged price, a calendar opening, a nearby completed job) or
it does not get generated at all. Enforce this as a lint rule, not a prompt suggestion.

## 4.5 The linter — hard gate

Compiled workflows are rejected, not warned, on:

| Rule | Why |
|---|---|
| Dangling goto target | `resolve_goto` fails safe to END, but silently |
| Unreachable steps | Author error, always |
| Cycle without a `wait` | Runaway |
| `send_sms` with no consent check on a cold-audience trigger | TCPA |
| >N sends per contact per day/week | Blast protection |
| Audience size > threshold without `drip_mode` | Carrier throttling, rep burial |
| Missing quiet-hours when workflow can send | 3am SMS |
| Template references an undefined `{token}` | Blank interpolation in a live message |
| Banned filler phrase in any template | Brand voice |
| No terminal path (every branch must reach END) | Contacts parked forever |

Warnings (proceed with confirmation): very long waits, no goal on a >7-day wait, >20 steps.

## 4.6 Simulation — what makes it trustworthy

Before Max ever sees a confirm button:

1. Take the last 90 days of real records matching the trigger + filters.
2. Replay the workflow with **all side-effect actions stubbed**.
3. Report: *"Over the last 90 days this would have fired 47 times. It would have sent 47
   texts and 31 emails, created 12 callback tasks, and moved 8 deals to Closed Lost. Here
   are the 3 contacts it would have touched most, and the exact messages they'd have
   received. 4 contacts would have hit it twice — your re-entry setting is 'cooldown 90
   days', so the second one was suppressed."*

This is the whole ballgame. A number and three real example messages is the difference
between "I guess I'll turn it on and watch" and "yes, publish it." Nothing else in this
document matters as much.

## 4.7 Editing

Match GHL's model — it's good and it's well-validated by usage:
- **Scoped natural-language edits**: "make that 48 hours", "change the first two texts",
  applying only to the named scope.
- **Point-and-edit**: select steps on the canvas, describe the change, AI touches only
  those. Essential past ~10 steps.
- **Session memory** for follow-ups.
- **Undo/redo** over AI changes.

Every edit re-runs compile → lint → simulate. Edits land on a **draft version**; publishing
is always explicit.

## 4.8 Guardrails

- Assistant-authored workflows save **inactive**. (Already true — keep it.)
- Publishing requires human confirmation, always. No exceptions, no "auto-approve" setting.
- The existing **approval gate** (`approval_worker.py`, `pending_action.py`) applies to
  first N executions of any AI-authored workflow — human-in-the-loop on real sends before
  it runs free.
- Full audit trail: `authoring_prompt`, `created_by='assistant'`, model + version, on every
  `automation_version`.
- Kill switch: workspace-level pause-all-automations.
- **Rate ceiling that is not overridable by the assistant.** The LLM can propose any
  workflow; it cannot raise the sends-per-contact-per-day cap.

---

# PART 5 — Build order

## 5.0 Four platform constraints that shape the plan

These come out of the codebase, not from GHL, and each one bends the sequencing.

### C1. There is no custom-fields table ⚠️ **prerequisite, not a nice-to-have**

Structured data lives in JSONB, not a first-class custom-field registry. GHL's trigger
model leans on custom fields *heavily* — `Contact Changed`, `Custom Date Reminder`,
`update_contact_field`, and most useful If/Else conditions all read them.

Consequence: **`contact_field_changed`, `update_contact_field`, and the general form of
`date_field_offset` cannot be built properly until custom fields exist.** A custom-field
registry (name, type, entity, options) is a Phase-1 prerequisite, not Phase 3 work.

Partial workaround worth taking early: `date_field_offset` against *known system dates*
(install date, quote sent date, job completed date, warranty expiry) needs no custom-field
work and covers the two ⭐⭐ seasonal use cases. Ship that first, generalize later.

### C2. Workers are in-process and poll-based — no Celery/RQ

`start_all_workers()` runs async loops inside the API process with Redis heartbeats.
Implications for this design:

- **Restart = pause.** Deploys stall in-flight waits. Acceptable now; it becomes a real
  problem once `scheduler` (cron) exists, because a missed 9am window is a missed
  seasonal send. The cron trigger needs a **catch-up-on-boot** pass that fires anything
  whose window elapsed while the process was down — with a staleness cap so a long outage
  doesn't dump a week of sends at once.
- **Drip mode needs durable batch state**, not an in-memory counter, for the same reason.
- Scales vertically only. Fine at current volume; note it before the simulator starts
  replaying 90 days of history on the same process serving requests — run simulations on
  a bounded worker with its own concurrency limit.

### C3. Encryption + workspace scoping constrain the simulator

PII is Fernet-encrypted at rest (`EncryptedString`) with phone numbers separately hashed
for lookup (`LookupHash`). Workspace isolation is an ORM-level SQLAlchemy listener via the
`WorkspaceScoped` mixin — **not** Postgres RLS.

Consequences:
- The simulation engine **must read through the ORM**, never raw SQL, or it gets ciphertext
  and silently escapes tenant scoping.
- Every new table (`automation_versions`, `automation_triggers`, `automation_step_runs`,
  `automation_goal_subscriptions`) must carry `WorkspaceScoped`. Since isolation is ORM-only,
  a missing mixin is a cross-tenant data leak, not just a bug.

### C4. Two safety rails already exist — use them, don't rebuild

- **`send_sms()` accepts an `idempotency_key` and dedupes on it.** Re-entry, retries, and
  goal-event yanks all become safe to implement, because the worst case of a double-fire is
  a no-op rather than a duplicate text. Every generated send step should carry a key derived
  from `(execution_id, step_id)`.
- **The approval gate is already wired** (`approval_worker.py`, `pending_action.py`) with
  operator approval over an SMS link and workflow resume. §4.8's human-in-the-loop guardrail
  for AI-authored workflows is *configuration of an existing mechanism*, not new
  infrastructure. This is the single cheapest safety win in the whole plan.

---

Sequenced so each phase ships something usable and nothing is wasted.

### Phase 0 — Prerequisite
0. **Custom-field registry** (name, type, entity, options) — unblocks a third of the
   catalog and every non-trivial If/Else condition

### Phase 1 — Structural foundation (unblocks everything)
1. `automation_versions` + pin `execution.version_id` ⚠️ *fixes a live correctness bug*
2. `automation_triggers` child table — multiple triggers + trigger filters
3. `settings` JSONB: re-entry policy, stop-on-response, quiet hours, sender
4. `automation_step_runs` + execution history UI

### Phase 2 — Control flow parity
5. Graph → compiled-steps compiler
6. Goal events + wait-for-event (`automation_goal_subscriptions`)
7. N-way if/else
8. `drip_mode`
9. `goto_workflow` + `fire_custom_trigger` (composition)

### Phase 3 — Catalog fill (priority order for Maxteriors)
10. `scheduler` (cron, w/ catch-up-on-boot per C2) + `date_field_offset` over system dates
    ⭐⭐ — unlocks seasonal & anniversary
11. `customer_replied` ⭐⭐ — unlocks stop-on-response
12. `create_task`, `assign_to_user`, `send_internal_notification` ⭐⭐ — callback tasks
13. `stale_opportunity` ⭐ — retires `unsold_quote_worker`
14. `remove_tag`, `update_contact_field`, `add_note`
15. `inbound_webhook` + `outbound_webhook` — integration escape hatch
16. `appointment_status_changed` (full lifecycle), `invoice_overdue`, `payment_failed`
17. `email_event` — near-free, Resend webhooks already handled (C1 note)
18. `meta_conversions_api` ⭐ — closes the loop on ad spend
19. `ai_prompt` step

### Phase 4 — AI authoring
20. IR schema + typed generation
21. Compiler + linter
22. Recipe library (**start by porting the 12 hardcoded workers**)
23. Simulation engine (ORM-only reads, bounded worker — per C3/C2)
24. Preview/confirm UX
25. Scoped edits + point-and-edit + undo
26. Route first N executions of AI-authored workflows through the existing approval gate (C4)

### Phase 5 — Retire the bespoke workers
27. Port each worker to a recipe, verify identical behaviour against production history
    using the simulator, delete the worker.

---

## Appendix — what to deliberately skip

Not worth building for a home-service CRM, despite GHL having them: Courses (Category/
Lesson/Product Started+Completed, Certificates), Communities (group & channel access,
leaderboards), Affiliates (creation, campaigns, payouts), Ecommerce (Shopify, abandoned
cart, order fulfilment, coupons), Memberships, IVR actions (unless inbound call routing
becomes a product), Video tracking, Social comment triggers (FB/IG/TikTok comment
automations).

That's roughly 35 of GHL's 60+ triggers. Cutting them is not a parity gap — it's the
reason The Tribunal's builder can be simpler, faster to author, and easier for an LLM to
target correctly.
