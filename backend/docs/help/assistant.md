# What the CRM assistant can do

The assistant is the chat surface at **Assistant** in the sidebar. It answers
questions by calling the same CRM the app uses, so its answers reflect live
data rather than a snapshot.

## Questions this answers

- What can the CRM assistant do for me in this app?
- Can the assistant send a text, edit a contact, or start a campaign?
- How does the assistant know about my contacts and campaigns?
- Why does the assistant say it needs approval?
- How do I get a morning briefing or plan my day?
- Why will the assistant not answer a question?

## What it can read

Contacts (including a full profile, notes, tags, and recent activity),
conversations and their messages, campaigns and their performance, automations,
AI agents, appointments, pipeline opportunities, offers, dashboard totals, and
today's mission queue.

List answers carry three separate numbers: `returned` (rows in this reply),
`total` (all matching rows), and `has_more`. "How many" questions are answered
from `total`, so a capped list never becomes a wrong count.

## What it can change

Create and update contacts, add notes, add tags, create and edit campaigns,
create and edit automations, create and edit AI agents, draft offers, and send a
text. Every genuinely risky one of those queues for your approval first — see
the approvals help.

## What it will not do

- Invent facts. If the data cannot answer the question, it says so.
- Approve its own actions.
- Answer product how-to questions from memory. It searches this help corpus
  first and tells you when the answer is not in there.

## Starting your day

Ask for a morning briefing (or "what should I do today?") and it works the
**Today** queue in order: approvals waiting, replies needing a human,
appointments, nudges due, fresh prospect batches, draft campaigns ready to
launch, and setup gaps.
