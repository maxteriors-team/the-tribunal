# Adding a sending phone number

Phone numbers live on the **Phone Numbers** page, in the sidebar under Tools
(`/phone-numbers`). Managing them needs the comms-management permission, so
members with view-only roles will not see the page.

## Questions this answers

- Where in the app do I add my sending phone number?
- How do I buy, search for, or set up a texting or calling number?
- How do I import the numbers I already own from Telnyx?
- Where do I set which number my campaign messages are sent from?
- How do I release a number I no longer want?
- Why can I not send anything yet?

## Get a number

There are two paths on that page:

- **Search for New Numbers** — pick a country, optionally type an area code,
  search, then purchase a result. The number is provisioned through Telnyx and
  appears in your workspace immediately.
- **Sync from Telnyx** — if you already own numbers in your Telnyx account,
  this pulls them into the workspace. It reports how many were new.

Each number lists its capabilities as badges: **SMS**, **Voice**, and whether it
is assigned to an agent. Releasing a number removes it from the workspace.

## Using a number to send

- **Campaigns** pick the sending number in the wizard's first step (Basics).
  Only senders capable of the campaign's channel are offered.
- **Voice campaigns** and **calls** need a voice-enabled number.
- **The assistant** sends one-off texts from a workspace number automatically.
  If the workspace has no number, the send fails and the assistant tells you to
  add one first — it cannot buy a number for you.

## Nothing sends without one

A workspace with zero phone numbers cannot text or call anyone: campaigns,
automations with an SMS action, and assistant sends all fail the same way. This
is the first setup step for any outbound work.
