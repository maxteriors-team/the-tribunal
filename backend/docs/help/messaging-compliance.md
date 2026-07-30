# Quiet hours, consent, and send limits

Every campaign send passes a compliance check before it leaves the system. The
checks run in order, and the first one that fails suppresses that send and
records the reason on the contact's campaign row.

## Questions this answers

- Does the system respect quiet hours when it sends texts to my contacts?
- Why did my campaign message not send to someone in this app?
- How do opt-outs and STOP replies work?
- Do I need consent before texting a contact?
- How many messages can one campaign or one contact receive?
- What is the difference between quiet hours and sending hours?

## 1. Global opt-out

If the number is on the workspace's opt-out list, nothing is sent — ever, on any
campaign. Replies containing opt-out keywords (`stop`, `stopall`,
`unsubscribe`, `cancel`, `end`, `quit`, `opt out`, `optout`, `remove`, `unsub`)
put the number on that list.

## 2. SMS consent

SMS sends require the contact's consent status to be `opted_in`. A contact whose
status is still `unknown` is skipped rather than texted.

## 3. Quiet hours

Quiet hours are a per-campaign window with its own timezone: `quiet_hours_start`,
`quiet_hours_end`, and `quiet_hours_timezone` (falling back to the campaign's
timezone, then UTC). A send landing inside that window is suppressed with the
reason `quiet_hours`. The window may cross midnight — 21:00 to 08:00 works as
expected.

**Quiet hours are only enforced when they are set.** A campaign with no quiet
hours configured passes this check, which is why the answer to "does the system
respect quiet hours?" is: yes, for campaigns that have them configured.

Quiet hours are not the same as **sending hours**. Sending hours (plus sending
days and timezone) are the schedule set in the campaign wizard, and the worker
waits outside them. Quiet hours are a compliance block applied per send. Set
sending hours in the wizard; quiet hours are set through the API or by asking
the assistant to update the campaign.

Other outbound paths carry their own quiet-hours windows with sensible defaults,
including missed-call text-backs (21:00–08:00), unsold-quote nudges
(21:00–08:00), and nudge delivery (22:00–08:00).

## 4. Send caps

- `max_messages_per_campaign` — total messages the campaign may ever send.
- `max_messages_per_contact` — messages one contact may receive from it.
- Duplicate protection stops a contact being sent the opening message twice from
  the same campaign.

## What is not covered

A one-off SMS the assistant sends for you is gated by **human approval** rather
than by campaign quiet hours: it is a message you explicitly approved, sent at
the moment you approved it. If timing matters, approve it when you want it to
land.
