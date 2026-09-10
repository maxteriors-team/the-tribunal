# Brand Voice System — README

How Maxteriors sounds, and how to keep it that way across every VA and every automation.

**The guide:** [`brand-voice-va-guide.md`](./brand-voice-va-guide.md)
**Owner:** Max · **Last reviewed:** 2026-09-09

---

## What this is

One document that makes a new VA and an AI automation write the same way on day one.

It is not a style essay. It is a working reference: rules short enough to memorize, templates you
fill in and send, a list of things you're not allowed to answer, and a prompt you paste into an
automation.

## Why it exists

Maxteriors is usually not the cheapest bid in the driveway. LumenaryPro wins on price.

So the voice has one job: **make someone feel safe spending more.** That's why the rules push toward
specifics, real prices, and warranty facts, and away from hype and pressure. Every hype word we cut
makes the higher number easier to say out loud.

## Who uses it

| You are | Read | Time |
|---|---|---|
| A new VA | Sections 1–6, then keep Section 5 open while you work | 15 min |
| A VA mid-shift | Section 5 templates, Section 3 checklist | as needed |
| Setting up an automation | Section 7, paste the prompt block | 5 min |
| Max, reviewing work | Section 8 rubric | 2 min per batch |

---

## VA onboarding — the 15-minute version

1. Read Sections 1–3. Memorize the six rules and the pre-send checklist.
2. Read Section 4 out loud. The banned words are the fastest way to spot a bad message.
3. Skim Section 5. Don't memorize it — bookmark it. You'll work out of it every day.
4. Read Section 6 twice. **Knowing what not to answer matters more than any template.**
5. Write three practice messages: a new lead, a price question, a cheaper-bid objection.
   Send them to Max before you touch a real customer.

**The one rule that survives everything else:** if you'd have to guess, escalate. A slow honest
answer beats a fast wrong one, and a wrong price is expensive to walk back.

---

## Wiring an automation

1. Open Section 7. Copy the whole fenced block.
2. Paste it as the **system prompt**, above your task-specific instructions.
3. Add the task below it — "write a second-touch SMS for an unsold permanent lighting quote."
4. Test with five real leads before turning it on. Score the output with the Section 8 rubric.

The prompt already contains the guardrails that matter:
- Never invent a price, date, timeline, warranty term, or promise
- Banned words and banned follow-up filler
- The escalation list, with a fixed reply for anything it can't handle

**Do not** paste the pricing into the automation separately. It's already in the FACTS block — two
copies means one goes stale.

---

## Maintenance

### The single source of truth

Every price, warranty term, and financing detail lives in **one place: the FACTS block in Section 7.**
The templates in Section 5 read from it by hand.

When something changes:

1. Edit the FACTS block first.
2. Grep the doc for the old number and fix the templates that quote it.
3. Re-check Section 6 — does this change move something off the escalate list, or onto it?
4. Update **Last reviewed** at the top of both files.
5. Tell the VAs what changed in one sentence. Don't make them diff a document.

### Review cadence

| When | What |
|---|---|
| Any price, warranty, or financing change | Same day — FACTS block first |
| Start of each season (spring / holiday) | Lead times and seasonal lines in Section 5 |
| Quarterly | Section 8 spot-check on a batch of real VA messages |
| New competitor or new objection shows up | Add a template to Section 5 |

---

## Open items

- [ ] **Christmas lighting deposit rule is undecided.** It's on the escalate list (Section 6) rather
      than guessed at. Once Max sets it, it's a two-line edit — add it to FACTS, add a template to
      Section 5 — and VAs can handle those inquiries end to end.
- [ ] Add a template for commercial / HOA inquiries once those terms are set. Currently escalate-only.

---

## Conventions

- `{curly braces}` in templates = fill this in before sending.
- Blockquoted text = send it roughly as written.
- The fenced block in Section 7 = machine-facing. Paste it exactly; don't reword it.
- Sign-off is always a first name. Never "The Maxteriors Team."
