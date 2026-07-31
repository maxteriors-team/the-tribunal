# Post-estimate follow-up re-audit (first 14 days)

**Date:** 2026-07-30
**Supersedes:** `docs/post-estimate-followup-audit-2026-07-29.md` (the pre-build audit)

## Headline

**Coverage already exists. Do not build a second worker.** The first-14-days
cadence shipped in commit `d973342f` and is complete against the original
specification on paper — every requirement has code behind it.

But it did not run. An end-to-end test drive found that **the day-1 touch never
fired for any quote**, because the worker's fetch was a fixed `LIMIT` over an
ascending `sent_at` ordering: the newest quotes sort last and were never
reached, and workspaces with the feature switched off consumed the entire budget
before the enabled ones were considered. The feature was, in practice, dead on
arrival for the touches that matter most.

Three defects are fixed here: the cross-sequence collision rail (§A), an
undecryptable contact stalling every tick (§B), and the fetch starvation (§C).
All three are covered by tests confirmed to fail against the pre-fix code.

## 1. What each existing worker actually targets

| Worker | Trigger / anchor | Cadence | Covers a `sent` quote? |
|---|---|---|---|
| `followup_worker.py` | `Conversation.next_followup_at` due, `followup_enabled`, `ai_enabled`, last message outbound, under `followup_max_count` | Polls 60s; each send reschedules `+followup_delay_hours` | **No.** Conversation-scoped and SMS-only. It never imports `Quote`, so nothing about it starts when an estimate is presented. |
| `never_booked_worker.py` | Contacts who replied at least once, carry no appointment lifecycle tag, and went quiet past `agent.never_booked_delay_days` | Hourly; effectively one SMS per contact/agent, gated by a `never-booked-reengaged` tag | **No.** Anchored to contact engagement state; a quote can be sent to someone who never replied, and a replier with a live quote is explicitly out of its audience. |
| `noshow_reengagement_worker.py` | Contacts flagged as appointment no-shows | Hourly; day-3 and day-7 SMS touches | **No.** Anchored to no-show contact state, not quote presentation. |
| `reminder_worker.py` | Future appointments in `scheduled` status | Polls 60s; configured minute offsets inside a 25-hour lookahead | **No.** Runs *before* a booked appointment; irrelevant when the estimate has not converted. |
| `post_estimate_followup_worker.py` | **`Quote.sent_at`, status `sent`** | Polls 300s; configurable touches at offsets 0–14, default day 1 SMS / day 3 call / day 7 email / day 14 SMS | **Yes — this is the answer to question 2.** |
| `unsold_quote_worker.py` | `coalesce(Quote.issue_date, Quote.sent_at)`, status `sent`/`expired` | Hourly; default 30/60/90 ladder | Long-range revival only (the separate task). |

## 2. Does a quote entering `sent` get a multi-touch 14-day cadence?

Yes. `PostEstimateFollowupWorker` already delivers every requirement from the
brief: `sent_at`-anchored offsets, mixed SMS/email/human-call channels, human
call tasks written as `HumanNudge` rows, `high_value_threshold` promoting SMS to
a call, `MessageTemplate` reuse, the `OutboundComplianceService` quiet-hours and
`OptOutManager` layers, a `quote_followup_touches` ledger for exactly-once
delivery, and stop conditions for approved, declined, inbound reply, opt-out,
and booked appointment — re-checked immediately before dispatch. Configuration
lives in `workspace.settings["post_estimate_followup"]`, is served by
`GET/PUT /api/v1/settings/workspaces/{id}/post-estimate-followup`, and is edited
in the **Quote Follow-Up** settings tab. Building anything new here would be a
duplicate.

## 3. Defects found (all fixed in this change)

### A. The two quote sequences can double-message — the collision rail is measured in the wrong space

The two sequences are kept apart only by a **config-space** rule:
`REVIVAL_MIN_OFFSET_DAYS = POST_ESTIMATE_MAX_OFFSET_DAYS + 1`, so a revival
touch cannot be configured below day 15. But the two workers measure their
offsets **from different anchors**:

- post-estimate → `Quote.sent_at` (when the customer received it)
- revival → `coalesce(Quote.issue_date, Quote.sent_at)` (the date printed on the document)

`issue_date` is operator-supplied and freely predates `sent_at`. When
`issue_date <= sent_at - 15 days`, the revival ladder is already "due" the moment
the quote is sent, and both sequences message the same customer about the same
quote in the same week. Real paths that produce this today:

1. An estimate written on-site and dated that day, sent after the usual round of
   drafting/approval — 15 days of lag is enough.
2. `app/services/prebooking/reservation_service.py` creates the quote with
   `issue_date=reservation.held_at.date()` and then immediately calls
   `mark_sent()`. A hold placed a month before conversion lands the revival
   ladder squarely inside days 0–14.
3. Any back-dated quote entered through `POST /quotes` with a historical
   `issue_date`.

Existing tests only assert the config-space rule
(`test_offsets_cannot_enter_the_post_estimate_window`), so this was invisible.

**Fix:** move the rail into time space. The post-estimate window is now a single
shared predicate, `post_estimate_window_is_open(sent_at, now=...)`, and the
revival worker refuses any quote presented less than 15 days ago — in its SQL
filter *and* as a `post_estimate_window_open` stop reason before dispatch —
regardless of what the document is dated.

**Severity:** latent, not live. Reverting the rail makes
`test_revival_never_double_messages_inside_the_post_estimate_window` fail with a
real dispatch, so the path is proven in code. But the local dev database
currently holds **0** quotes where `issue_date <= sent_at - 15 days`, so nothing
is double-messaging today. This is a guard placed before the pre-booking
reservation flow starts producing back-dated quotes at volume, not a fire.

### B. One undecryptable contact silently kills the entire cadence

`_process_items` eager-loaded `joinedload(Quote.contact)`. `Contact.email` and
`Contact.phone_number` are `EncryptedString`, and `process_result_value`
re-raises `InvalidToken` for a Fernet-looking value written under a retired key.
That raise happens while the **result set is materialized**, i.e. before any
per-quote error handling, so one bad row aborts the whole tick. `_run_loop`
catches and logs it, the Redis heartbeat still writes, and `/readyz` stays green
— so the entire first-14-days cadence stalls for **every workspace**, silently,
for as long as the bad row sits inside the 15-day window (up to 15 days).

The sibling revival worker already guards against exactly this and documents
why; the post-estimate worker did not. **Fix:** mirror it — eager-load only the
workspace, materialize the contact per quote through `_load_contact`, and skip a
single undecryptable quote loudly while the tick continues.

**Severity:** live whenever an encryption key is rotated with any row left
behind, which `make rotate.encryption-key` exists precisely to manage. The local
dev database has 677 quotes in `sent`, so the old code materialized every one of
their contact rows on every tick to decide four booleans.

### C. The fetch ceiling starved the newest quotes — the cadence did not work at all

An earlier draft of this note called `MAX_QUOTES_PER_TICK = 100` "a scaling item,
not an outage" and assumed volumes were far below the threshold. **That was
wrong, and an end-to-end test drive against the local database disproved it
within minutes.** Every day-1 touch failed; every day-3, day-7 and day-14 touch
succeeded. That signature is not a cadence bug, it is a fetch bug.

Two compounding defects:

1. **The `LIMIT` was a ceiling, not a cursor.** Ordered by `sent_at` ascending,
   the newest quote in the window sorts *last*. The local database holds 424
   quotes inside the 15-day window, so a one-day-old quote ranks **302nd** and
   was never reached. The starved touches are exactly day 1 and day 3 — the most
   valuable in the sequence, and the entire premise of the feature.
2. **Disabled workspaces consumed the budget.** `enabled` defaults to `False`,
   but the fetch selected quotes across all workspaces and discarded the
   disabled ones *in Python, after the `LIMIT`*. All 100 rows in the measured
   batch belonged to workspaces with no config block at all. A workspace that
   switched the cadence on could therefore receive **nothing, indefinitely**,
   starved by unrelated tenants that do not even use the feature.

**Fix (both workers):** filter `enabled` in SQL via the JSONB predicate so
disabled workspaces cost nothing, and replace the single `LIMIT` with keyset
pagination over `(sent_at, id)` — `(anchor, id)` for revival — that pages until
the due set is exhausted. `MAX_QUOTES_PER_TICK` survives only as a 5,000-row
safety ceiling that logs loudly when crossed, since crossing it now means real
work was skipped.

`unsold_quote_worker` had the identical shape over a 366-day window. It is fixed
the same way here rather than left broken: the overlap guarantee added in §A is
worthless if the sequence enforcing it silently stops running.

## 4. How this was verified

Beyond unit tests, an end-to-end harness drove both sequences against the real
local Postgres: real workers, real config parsing, real compliance and
quiet-hours evaluation, real opt-out layer, real ledger writes, real
stop-condition SQL. The only faked functions were the two network egress calls,
`TelnyxSMSService._post_message` and `app.services.email._send`, so no live SMS
or email was billed while conversations, `Message` rows, idempotency keys and
status transitions all executed for real. Time was advanced by moving
`Quote.sent_at` backwards rather than by faking the clock, so the workers' own
`datetime.now(UTC)` and SQL windows were exercised.

24 checks covering the full ladder, idempotency, value segmentation, all five
stop conditions, quiet-hours deferral and resumption, and non-overlap with the
revival sequence in both directions. The harness lives at
`.ezcoder/eyes/out/cadence_drive.py` (gitignored); the durable regression
coverage it produced is committed in `backend/tests/workers/` and
`frontend/src/components/settings/quote-followup-settings-tab.test.tsx`.

### D. The cadence counted no sends at all

The direct-send path enforces opt-out, consent and quiet hours, but unlike
`campaign_worker` it never reserved against the sending number. Enabling the
cadence on a workspace with a backlog of in-window quotes would fire one SMS per
quote on the first tick, from a single number, ignoring its per-second, hourly
and daily limits and its warming schedule. The customer-facing harm is small;
the carrier-reputation harm is not, and a filtered number degrades deliverability
for every other message it sends.

**Fix:** both workers now call `NumberPoolManager.reserve_number_for_send`
before dispatch, exactly as `campaign_worker` does. A sender at capacity returns
`None`, which writes no ledger row, so the touch stays due and is retried on a
later tick rather than being silently consumed. `redis` is now declared in both
workers' dependency tuples, since the allowance is Redis-backed.

One deliberate hole: if the resolved sender is not a tracked `phone_numbers` row
for that workspace, the send proceeds uncapped with a warning. In the local
database 24 of 26 conversations reference such a sender, so refusing them would
silently disable follow-up for most existing contacts — the same class of failure
as §C, and worse than an uncapped send that is visible in the logs.

With production defaults (1 msg/sec, 10/hour, 75/day per number) a workspace
turning the cadence on now drains its backlog across many ticks instead of
bursting.

## 5. Still open, deliberately not changed here

The 5,000-row per-tick ceiling is now a genuine bound rather than a silent
truncation, but a single workspace with more than 5,000 quotes in-window would
still lose the tail of the ordering. Fixing that properly means per-workspace
round-robin fairness rather than a global ordering, which is a larger design
change than this audit warrants. The worker now logs a warning naming the
ceiling when it is crossed, so the condition is observable rather than silent.

The untracked-sender hole described in §D is bounded by logging rather than by
enforcement. Closing it properly means reconciling `Conversation.workspace_phone`
against `phone_numbers`, which is a data-quality question rather than a worker
question, and touches every sender in the product rather than these two
sequences.
