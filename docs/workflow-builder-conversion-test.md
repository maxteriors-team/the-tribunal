# Conversion test: can `unsold_quote_worker` become an automation row?

**Date:** September 2026
**Method:** Attempt to express `backend/app/workers/unsold_quote_worker.py` (798 lines) as a
row in `automations` using only what the engine supports today. Record every break.
**Verdict:** **No — but the failures cluster on one root cause, not nine.**

---

## What the worker actually does

Stripped to its behaviour:

| Aspect | Value |
|---|---|
| **Subject entity** | **Quote** (not Contact) |
| **Anchor** | `quote.issue_date`, falling back to `sent_at` |
| **Ladder** | 30 / 60 / 90 days from anchor — configurable offsets, `max_touches` |
| **Channels** | touch 1 SMS · touch 2 email · touch 3 **human call task** |
| **Copy** | high-value template if `quote_total >= threshold`, else routine |
| **Ledger** | `QuoteFollowupTouch` per `(quote, sequence_key, offset_days)` + outcome |
| **Suppression** | 6 conditions, re-checked **twice** — before render *and* before dispatch |

The six stop reasons:
1. `quote.status in {approved, declined}` — settled outcome
2. `quote.status not in REVIVABLE_STATUSES` — never presented
3. `post_estimate_window_open(quote.sent_at)` — **another sequence owns this quote**
4. `contact_opted_out` — opt-out manager
5. `contact_replied` — inbound message since last touch (or within 14d before first touch)
6. `appointment_booked` — any `SCHEDULED` appointment for the contact

---

## The attempt

```jsonc
{
  "name": "Unsold quote revival (30/60/90)",
  "trigger_type": "quote_sent",              // ⚠️ BREAK 3 — wrong anchor
  "trigger_config": {},
  "actions": [
    { "id": "w30",  "type": "wait",   "config": { "days": 30 } },
    { "id": "g30",  "type": "branch", "config": { "conditions": [ /* ⚠️ BREAK 1+2 */ ],
                                                  "else_goto": "__end__" } },
    {               "type": "send_sms", "config": { /* ⚠️ BREAK 6 — one template only */ } },

    { "id": "w60",  "type": "wait",   "config": { "days": 30 } },
    { "id": "g60",  "type": "branch", "config": { "else_goto": "__end__" } },
    {               "type": "send_email", "config": {} },

    { "id": "w90",  "type": "wait",   "config": { "days": 30 } },
    { "id": "g90",  "type": "branch", "config": { "else_goto": "__end__" } },
    {               "type": "make_call", "config": {} }   // ⚠️ BREAK 4 — AI call, not a task
  ]
}
```

This row is *syntactically valid* and the engine would run it. It would also be **wrong**,
in ways that would text customers who already bought.

---

## What broke, ranked

### 🔴 BREAK 1 — The engine is contact-shaped; this workflow is quote-shaped `FATAL`

`branch` resolves through `contact_matches_rules(db, workspace_id, contact_id, rules)`,
which builds `SELECT contacts.id WHERE contacts.id = :id` and applies contact filters.

**A branch step can only ask questions about the contact.** At day 30 the workflow cannot
ask *"is **this** quote still unsold?"* — the question the entire sequence exists to answer.

`context` JSONB carries the trigger payload across the wait, so `quote_id` and `quote_total`
are available for **rendering**. They are not available for **branching**. Read is not
predicate.

> **Credit where due:** the dedupe layer already handles multi-quote contacts correctly.
> Event executions are unique on `(automation_id, event_id)`, not `(automation_id, contact_id)`,
> so three open quotes for one contact produce three independent runs. The hard part of
> entity-scoping is *already solved* — one index short of the whole thing.

### 🔴 BREAK 2 — No re-evaluation of the triggering record's live state `FATAL`

Of the six suppression conditions, **only one** (`contact_opted_out`) is expressible today:

| Stop reason | Expressible? | Why not |
|---|---|---|
| quote approved / declined | ❌ | quote field, not contact field |
| quote not revivable | ❌ | quote field |
| post-estimate window open | ❌ | cross-workflow state |
| contact opted out | ✅ | `opt_out.py` + consent filters |
| replied since last touch | ❌ | needs a cutoff that is *dynamic per run* (last touch time) |
| appointment scheduled | ❌ | related-entity existence check |

The worker also re-checks **immediately before dispatch**, after rendering. The engine
evaluates a branch once and moves on. Under load that gap is where a "your price is still
good" text lands on someone who signed an hour ago.

### 🟠 BREAK 3 — The anchor is a field on a record, not the trigger instant `MAJOR`

`issue_date` wins over `sent_at` because it is what price validity is measured against. A
**back-dated quote is already 30 days old the day it is presented.** `quote_sent` + `wait 30d`
counts from the event, so back-dated quotes get their day-30 touch on day 60.

This is the `date_field_offset` trigger from the design doc (§1.I ⭐⭐), generalized to an
arbitrary date field on an arbitrary entity.

### 🟠 BREAK 4 — `make_call` is an AI call; the day-90 touch is a human task `MAJOR`

Touch 3 creates a `HumanNudge` — briefing a person to make the call. The engine's
`make_call` dials an AI voice agent. Substituting one for the other changes what the
customer experiences.

Notably this is **also a stated product preference**: callbacks should create internal human
tasks, not route into automated calling. `create_task` / `notify_user` is missing from the
action catalog and is high-priority for reasons beyond this worker.

### 🟠 BREAK 5 — Per-touch ledger vs. one integer cursor `MODERATE`

`completed_offsets` is a **set**; `AutomationExecution.step_index` is an **integer**. Each
touch records an outcome (`sent` / `failed` / `skipped_stale` / `task_created`). The engine
records status at execution level — **there is no per-step outcome record at all.**

So "which touches actually went out, and what happened to each" is unanswerable. This
confirms `automation_step_runs` (design doc §3.1) is required, not optional.

### 🟠 BREAK 6 — Conditional content without conditional branching `MODERATE`

`resolve_template_id` picks high-value vs routine copy from `quote_total`. Expressing that
today means a `branch` plus duplicate send steps at every touch — **9 steps become 15**, and
every copy edit has to be made twice. Needs either conditional config or template selectors.

### 🟡 BREAK 7 — Cross-workflow mutual exclusion `MODERATE`

`post_estimate_window_is_open` is one sequence **deferring to another**. There is no concept
of workflow precedence, shared suppression windows, or global frequency capping. Confirms
frequency capping is a real gap, not a theoretical one — the codebase already needed it
badly enough to hardcode it.

### 🟢 BREAK 8 — Send infrastructure `RESOLVED — mostly fine, one real gap`

**Checked, because if the engine's send path skipped compliance it would be a live problem
in automations running today, independent of this project. It does not.**

`_action_send_sms` routes through `OutboundDeliveryService.deliver()`
(`app/services/outbound/delivery.py`), which constructs its own `OutboundComplianceService`
and `OptOutManager` and gates every send. The automation path passes quiet-hours bounds,
workspace timezone, an idempotency key via `derive_outbound_key("automation_sms", …)`, and
an optional consent requirement.

| Concern | Worker | Automation step |
|---|---|---|
| Compliance gate | ✅ | ✅ via `OutboundDeliveryService` |
| Opt-out | ✅ | ✅ |
| SMS consent | ✅ | ✅ (`require_consent`) |
| Quiet hours | ✅ | ✅ (defaults 21:00–08:00, workspace tz) |
| Idempotency | ✅ | ✅ |
| **Number-pool reservation** | ✅ `NumberPoolManager` | ❌ **not reserved** |

**The one gap:** `_resolve_from_number` picks a sender by conversation stickiness, then by
capability — it never reserves through `NumberPoolManager`. The worker does.

This is a **deliverability risk, not a compliance one**: at volume, automations can
over-send from a single number and hit carrier throttling, with no pool-level rate limit.
Worth fixing before automations carry the volume these workers do — but it does not
block the port, and nothing illegal is happening today.

> Correcting my earlier framing: quiet hours are **not** entirely missing at the engine
> level. They exist per-`send_sms`-step with sane defaults. What is missing is a
> *workflow-level* quiet-hours setting, so an operator sets it once instead of on every
> send step and cannot forget one.

### 🟡 BREAK 9 — Config validators must become linter rules `MINOR`

`QuoteRevivalSettings` enforces: offsets ≥ 15 days (so it can't collide with the
post-estimate cadence), ≤ 365, and *call touches may not carry a template*. As a workflow,
those become **linter rules** — confirming design doc §4.5 needs domain rules, not just
structural validation.

---

## What worked

Worth stating plainly, because the spine is sound:

- ✅ **Event dedupe on `event_id`** correctly supports per-quote runs
- ✅ **`context` JSONB survives waits** — token rendering after a 30-day pause was clearly
  designed for exactly this
- ✅ **Branch re-reads state after the wait** rather than using pre-wait attributes — right
  instinct, wrong entity scope
- ✅ **`MAX_WAIT` = 365 days** exactly matches `REVIVAL_MAX_OFFSET_DAYS`
- ✅ **`resume_count` / `MAX_RESUMES=200`** bounds runaway loops

---

## The finding

Nine breaks, but **three fatal ones share a single root cause: everything is contact-shaped.**

> The timing and resumption machinery is genuinely good. The entity model is the blocker.

One architectural change fixes BREAK 1, 2, 3, and 5 together:

**Entity-scoped executions.**
1. `AutomationExecution` gains `subject_type` + `subject_id` (quote / job / opportunity /
   invoice / contact), with `contact_id` kept as a denormalized convenience.
2. Branch conditions gain a **subject scope** — evaluate filter rules against the triggering
   entity, not only the contact. The `contact_filters` reuse argument in `branching.py` is
   correct and should be repeated per entity, not abandoned.
3. Triggers gain `date_field_offset` semantics against a named date field on the subject.
4. `automation_step_runs` records per-step outcome.

**Revised recommendation:** this is a prerequisite, and it belongs in Phase 1 ahead of
catalog work. Building 17 more triggers on a contact-shaped execution model means
rebuilding them.

## Scorecard

| # | Break | Severity | Fixed by entity-scoping? |
|---|---|---|---|
| 1 | Contact-shaped branch conditions | 🔴 fatal | ✅ |
| 2 | No live re-evaluation of subject state | 🔴 fatal | ✅ |
| 3 | Anchor is a record field, not trigger time | 🟠 major | ✅ |
| 4 | `make_call` ≠ human call task | 🟠 major | ❌ needs `create_task` |
| 5 | Integer cursor vs per-touch ledger | 🟠 moderate | ✅ (`automation_step_runs`) |
| 6 | Conditional content selection | 🟠 moderate | ❌ needs template selectors |
| 7 | Cross-workflow mutual exclusion | 🟡 moderate | ❌ needs frequency capping |
| 8 | Send infrastructure | 🟢 resolved | n/a — number-pool gap only |
| 9 | Config validators → linter rules | 🟡 minor | ❌ linter work |

**Four of nine fall to one change.** The rest are ordinary catalog work already scoped in
the design doc.

## Recommended next step

Build entity-scoped executions as a spike against **this exact worker** as the acceptance
test — not against a toy workflow. If the 30/60/90 ladder with all six suppression
conditions can be expressed and shadow-run against production history to match the current
worker's decisions, the model is proven for the other eleven. If it cannot, better to know
at 200 lines than at 5,000.
