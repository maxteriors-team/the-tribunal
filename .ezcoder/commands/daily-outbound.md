---
name: daily-outbound
description: Review daily outbound health and recommend Prestyj next actions
---

Run the daily outbound review for Prestyj offers. Do not change code or data unless the user explicitly asks for follow-up implementation.

## Step 1: Inspect Campaign Health

Review active outbound campaigns and summarize:
- Campaigns that are running, paused, failed, or underperforming
- Delivery, reply, booking, and conversion trends where available
- Recent errors, blocked sends, bounced messages, or telephony/SMS failures
- Any campaigns needing copy, audience, schedule, or offer adjustments

Use the app's existing campaign APIs, database-access patterns, dashboards, or logs as appropriate for the local environment. Do not run destructive database operations.

## Step 2: Check Pending Approvals

Inspect human-in-the-loop queues and identify:
- Pending outbound messages, calls, nudges, or suggested actions awaiting approval
- Time-sensitive approvals that could unlock same-day pipeline movement
- Items that appear stale, duplicate, unsafe, or off-brand

Group approvals by urgency and expected revenue/pipeline impact.

## Step 3: Identify Warm Leads

Find contacts or opportunities showing recent buying intent, including:
- Replies, missed calls, booked meetings, reschedules, or positive sentiment
- Recent site/widget conversations, lead-magnet activity, or high-fit segments
- Opportunities with upcoming follow-up windows or stalled next steps

Prioritize leads tied to Prestyj offers and include the evidence for why each lead is warm.

## Step 4: Review Outbound Analytics

Assess outbound performance across channels:
- Call connect rates, voicemail outcomes, and call dispositions
- SMS/email send, delivery, reply, opt-out, and booking rates
- Segment, tag, offer, and campaign-level performance differences
- Notable day-over-day or week-over-week changes

Call out anomalies, risks, and quick wins instead of dumping raw metrics.

## Step 5: Recommend Next Actions

Return a concise daily brief with:
1. **Health summary** — 3–5 bullets on campaign/outbound status.
2. **Warmest opportunities** — the top leads or segments to act on today, with supporting evidence.
3. **Pending approvals** — what should be approved, edited, or rejected first.
4. **Recommended next actions** — exactly 1–3 concrete actions for Prestyj offers.

Each recommended action must include:
- The target lead, segment, campaign, or approval queue
- The action to take today
- Why it matters now
- Any risk or dependency before execution

If data access is unavailable, state exactly what could not be inspected and provide the best next manual check rather than guessing.
