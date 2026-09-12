# SMS consent capture — plan

**Status:** proposal, nothing changed yet.
**Not legal advice.** Engineering guidance; a lawyer should confirm the wording before it goes live.

## What I found (evidence: prod DB, read-only, 2026-09-11)

BEAM's consent plumbing **already exists and is built correctly**:

- `POST /api/v1/lead-form/{public_key}` accepts `sms_consent` (`app/schemas/lead_source.py:379`), defaulting to `false`.
- It records consent **only** when the box was actually ticked — status, source, timestamp and a note — and an unticked box never downgrades existing consent (`app/api/v1/lead_form.py:560-568`).
- The offer page renders the checkbox optional and unchecked-by-default, with frequency, rates, STOP/HELP and "not a condition of purchase" (`frontend/src/app/p/offers/[slug]/page.tsx:313-338`). That matches 10DLC/TCR expectations and avoids the bundled-consent rejection (TCR error 803).

So this is **not** a missing-feature problem. It is a wiring problem on the external landing pages.

| Lead source | Site | Action | Consent recorded |
|---|---|---|---|
| permholidaylights.com instant quote | permholidaylights.com | **auto_text** | **0** — never sends the field |
| FB Christmas light leads | maxteriors-christmas-lights.netlify.app | auto_text | 1 ✅ sends it |
| Website Quote Form | maxteriorslighting.com | collect | 29 ✅ |
| landscape-quote, Google Ads, Facebook, radio, truck wrap | various | collect | 0 |

**30 of 1,970 contacts have recorded consent.** The remaining 1,939 are mostly Jobber-imported past customers who predate any consent field.

## The distinction that actually matters

- **Responding to someone's own quote request** (today's auto-text) is a reply to their inquiry. Defensible, and it is what is happening now.
- **Marketing and upsell to past customers** is promotional. That needs express written consent — a ticked box with the disclosure, logged with a timestamp.

The upsell agent is therefore blocked on consent in a way the current auto-text is not. That is the whole reason this comes first.

## Proposed work

### 1. permholidaylights.com — add the checkbox (external site, ~20 min)
Highest value: it is the only `auto_text` source sending zero consent, and it produced 69 texts since July.

Add to the quote form, unchecked, not required, and post `sms_consent: true` when ticked. Wording, matching what BEAM already uses:

> I agree to receive text messages from Maxteriors Lighting about my inquiry, including follow-ups, offers, and appointment reminders. Message frequency varies. Message & data rates may apply. Reply STOP to opt out or HELP for help. Consent is not a condition of purchase. (Optional)

No BEAM change needed — the endpoint already accepts it and `permholidaylights.com` is in `allowed_domains`.

### 2. Same checkbox on the other landing pages
landscape-quote, radio landing, truck-wrap QR, and any Google/Facebook form. Identical wording and field.

### 3. BEAM guard so this cannot silently recur (small change here)
A lead source set to `auto_text` that has never received a `sms_consent: true` is a configuration mistake that is invisible today. Surface it in the lead-source UI as a warning. Small, self-contained, no customer-facing effect.

### 4. The 1,939 existing contacts — capture, do not blast
Do **not** mass-text asking for permission; that is the same unconsented marketing text the consent is meant to authorise. Instead capture consent at the next real touchpoint: booking confirmation, invoice, and the job-completion flow. Consent then accrues naturally as work happens.

## Explicitly out of scope
- Backfilling consent for imported contacts from implied or historical contact. There is no record to support it.
- Treating a reply to a text as written marketing consent.

## Open questions for Max
- Who can edit permholidaylights.com, and is it a site builder (Wix/Webflow/Squarespace) or hand-written HTML? That decides whether I hand over a snippet or a click-path.
- Is there a written privacy policy and terms URL to link from the checkbox? BEAM links `TermsAndConditionsLink`; the external sites need their own.
