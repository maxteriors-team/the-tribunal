# Campaigns, and how they differ from automations

A **campaign** is a batch: one list of contacts, one opening message, one
schedule. You build it, it sends to that list, and it finishes.

An **automation** is a standing rule: one trigger, then actions, applied to
individual contacts forever until you pause it. Nobody is "in" an automation —
contacts pass through it as they qualify.

Rule of thumb: a one-off push to a list of people is a campaign; a permanent
"whenever X happens, do Y" is an automation. An automation can enroll a contact
into a campaign, so the two work together.

## Questions this answers

- What is the difference between a campaign and an automation here, in this CRM?
- When should I use a campaign instead of an automation?
- How do I create or set up a campaign?
- What do the campaign statuses mean, and why is there no "active" status?
- How do I change a campaign's opening message before it goes out?
- How do sending hours and sending days work?

## Campaign types

- `sms` — text campaign.
- `voice_sms_fallback` — outbound AI calls, with an SMS sent when the call
  fails.
- `email` — email campaign; the opening message holds the body and there is a
  separate subject line.

## Campaign statuses

`draft`, `scheduled`, `running`, `paused`, `completed`, `canceled`.

"Active" is not a status. A campaign that is currently sending is `running`; one
waiting for its start date is `scheduled`.

## Building one

Create a campaign from **Campaigns** in the sidebar. The SMS wizard walks
through six steps:

1. **Basics** — name, description, and the sending phone number.
2. **Contacts** — who receives it.
3. **Message** — the opening message, optionally built around an offer.
   `{first_name}` and `{company_name}` are substituted per contact.
4. **AI Agent** — which agent handles replies.
5. **Schedule** — optional start/end dates, sending hours, sending days,
   timezone, and rate limits.
6. **Review** — a summary before you launch.

Follow-up messages stop for a contact once they reply, opt out, or reach the
campaign's per-contact message cap.

## Sending windows

Sending hours are off by default, which means "send any time" (stored as
00:00–23:59). Turn on **Restrict Sending Hours** to set a start time, end time,
and timezone. Sending days default to Monday–Friday. The campaign worker checks
both before every send and simply waits while the campaign is outside its
window.

Sending hours are not the same as quiet hours — see the messaging-compliance
help for how quiet hours, consent, opt-outs, and send caps interact.

## Asking the assistant

The assistant can list campaigns with their schedule, message, and contact
count; summarize performance; list enrolled contacts; create a campaign; and
edit one (including the opening message) before it launches. Starting or
resuming a campaign requires your approval first; pausing one does not.
