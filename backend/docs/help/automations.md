# Setting up an automation

An automation is a standing rule: **one trigger, then a list of actions**, run
automatically for the contact that fired it. It keeps running until you pause or
delete it, and it applies to contacts one at a time as they qualify.

## Questions this answers

- How do I set up an automation in this CRM app?
- Where do I create or add a new automation?
- How do I change what an existing automation does?
- How do I turn an automation off, or delete one?
- Which triggers and actions can an automation use?
- Can the assistant build an automation for me?

## Create one in the app

1. Open **Automations** at `/automations`.
2. Select **Create Automation**.
3. Fill in **Name** and, optionally, **Description**.
4. Pick a **Trigger Type** — when the rule should fire.
5. Pick an **Action** — what should happen.
6. Fill in the extra field the choice reveals:
   - `Apply Tag` action → **Tag to apply**. The tag is created in this workspace
     if it does not exist yet, then added to the contact.
   - `Move deal to stage` action → the destination **stage**, chosen from a
     pipeline. You need a pipeline in Opportunities first.
   - `Lead created` trigger → **Lead source**. Leave it on *All lead sources* to
     catch every new lead, or pick one form.
   - `Contact tagged` trigger → the **tag** that fires the rule.
7. Click **Create**. New automations start active.

## Manage an existing one

Every automation card has a switch to activate or pause it, and a `⋯` menu with
**Configure**, **Pause/Activate**, **Duplicate**, and **Delete**. Configure
re-opens the same dialog and edits the rule in place — you never need to
recreate an automation to change a wait, a tag, or a message.

## Triggers

Generic kinds: `event`, `schedule`, `condition`.

Contact triggers: `appointment_booked`, `booking_created`, `no_show`,
`contact_tagged`, `never_booked`.

Event triggers emitted by the system: `review_received`,
`review_request_response`, `opportunity_created`, `deal_stage_changed`,
`missed_call`, `roleplay_completed`, `knowledge_document_uploaded`,
`lead_created`.

Billing and job triggers: `quote_sent`, `quote_approved`, `quote_declined`,
`quote_converted`, `invoice_sent`, `invoice_paid`, `job_scheduled`,
`job_completed`.

## Actions

`send_sms`, `send_email`, `make_call`, `enroll_campaign`, `move_to_stage`,
`apply_tag` (alias `add_tag`), and `wait` (alias `delay`). Actions run in the
order listed. A `wait` pauses the sequence and defaults to one hour when no
duration is given.

`enroll_campaign` is the bridge between the two systems: an automation can drop
the matched contact into an existing campaign.

## Asking the assistant to do it

The assistant can list, read, create, edit, enable, disable, and delete
automations. Creating, updating, enabling, and deleting one all require your
approval before they take effect — the assistant queues the change and you
approve it in chat or on the Pending Actions page.
