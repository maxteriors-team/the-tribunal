# Post-estimate follow-up audit

**Date:** 2026-07-29

## Finding

The current system has **no quote-triggered follow-up sequence**. No worker under `backend/app/workers/` imports `Quote`, reads `Quote.sent_at`, or schedules touches when a quote enters `sent`. A dedicated first-14-days post-estimate cadence is therefore a genuine gap, not a duplicate.

## Existing worker coverage

| Worker | Target | Cadence | Why it does not cover sent quotes |
|---|---|---|---|
| `followup_worker.py` | A conversation explicitly configured with `followup_enabled=true`, a due `next_followup_at`, AI enabled, an outbound last message, and remaining follow-up count | Polls every 60 seconds. Conversation defaults are disabled, 24-hour delay, and 3 sends; each successful SMS schedules the next relative to that send. | It is conversation-scoped and SMS-only. It has no quote/status/value awareness and is not activated by `Quote.sent_at`. |
| `never_booked_worker.py` | Contacts who have replied at least once but have no appointment lifecycle tag and have gone inactive past `agent.never_booked_delay_days` | Polls hourly; effectively one SMS per contact/agent because it applies `never-booked-reengaged`. | It targets stale engaged leads who never booked, not open estimates. |
| `noshow_reengagement_worker.py` | Contacts marked as appointment no-shows | Polls hourly; SMS touches just after day 2 and day 6, tracked as day-3/day-7 tags. | It is anchored to no-show contact state, not quote presentation. |
| `reminder_worker.py` | Future appointments with `scheduled` status | Polls every 60 seconds; sends at configured minute offsets (default 60 minutes for agentless appointments) within a 25-hour lookahead, plus an optional value-reinforcement touch. | It runs before booked appointments and stops being relevant when there is no appointment. It does not inspect quotes. |

## Missing capability to add

Implement an opt-in workspace-configured sequence anchored to the immutable first `Quote.sent_at`, limited to offsets from day 0 through day 14. It should support SMS, email, and human-call tasks; promote SMS touches to call tasks above a configurable quote-value threshold; use saved `MessageTemplate` records; and stop on quote approval/decline, an inbound reply after presentation, global opt-out, or a booked appointment.

The first-14-days window must remain bounded so it cannot overlap a separate 30/60/90-day unsold-quote revival sequence.
