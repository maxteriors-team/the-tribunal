# How the approval queue works

Risky actions the AI proposes do not run immediately. They are queued as
**pending actions** and wait for a human. Nothing is sent, started, or changed
until someone approves.

## Questions this answers

- How does the approval queue work in this CRM app?
- Why is the assistant waiting for my approval before it does something?
- Where do I approve or reject what the AI wants to do?
- What happens to a pending action if I ignore it until it expires?
- Which assistant actions need approval, and which do not?
- Can the AI approve its own actions?

## Where to review them

**Pending Actions** in the sidebar. The page shows counters for Pending,
Approved, Rejected, Expired, and Executed, plus tabs to filter the list. Each
card carries a plain-language description of what would happen, its urgency, and
when it was created.

- **Approve** runs the action immediately.
- **Reject** cancels it. You can attach an optional reason.

Approvals also appear inline in the assistant chat, with the same Approve and
Reject buttons, so you do not have to leave the conversation.

## Expiry

A pending action that nobody touches before it expires is **auto-rejected**. It
never runs. Expiry is a safety default, not a delayed send: if an action matters,
approve it.

## What the assistant has to get approved

These assistant tools always queue for approval first:

- Sending an SMS to a contact.
- Starting or resuming a campaign.
- Creating, updating, enabling, or deleting an automation.
- Creating or updating an AI agent.
- Assigning an AI responder to a conversation.

Read-only work — searching contacts, listing campaigns, reading a conversation,
summarizing performance — never needs approval. Pausing a campaign does not
either, because pausing only ever stops sending.

## What the assistant cannot do

The assistant cannot approve its own actions. Approval is decided by the server
when the tool runs, not by anything the model writes, so it cannot mark a
request as already confirmed to skip the queue.

When a tool is queued, the assistant tells you it is waiting for approval and
stops. Approve it and the original action runs as proposed.
