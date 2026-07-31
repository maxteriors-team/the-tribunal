# Post-estimate follow-up re-audit (first 14 days)

**Date:** 2026-07-30
**Supersedes:** `docs/post-estimate-followup-audit-2026-07-29.md` (the pre-build audit)

## Headline

**Coverage already exists. Do not build a second worker.** The first-14-days
cadence shipped in commit `d973342f` and is complete against the original
specification. This re-audit found two genuine residual defects in the shipped
code and one scale limitation, all narrow. Only the two defects are fixed here.

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

## 3. Residual defects found (fixed in this change)

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

## 4. Known limitation, deliberately not changed here

`MAX_QUOTES_PER_TICK = 100` with `ORDER BY sent_at` is a per-tick ceiling, not a
cursor. Above roughly 7 sent quotes/day a workspace has more than 100 quotes
inside the 15-day window, and the newest ones are crowded out until older quotes
age past day 15 — so their day-1 and day-3 touches are missed permanently, which
is precisely the part of the window worth the most. `unsold_quote_worker` has the
same shape and a far wider window (366 days), so it is affected harder.

Fixing this well means choosing a fairness model (keyset pagination per tick vs.
per-workspace round-robin) and applying it to both workers, which reaches into
the separate 30/60/90 revival task. It is called out here rather than fixed
opportunistically. Today's volumes are far below the threshold, so this is a
scaling item, not an outage.
