# Slow-Season Revival & Christmas Pre-Booking

**Owner:** Max / Maxteriors
**System:** The Tribunal CRM
**Status:** Designed, not yet applied
**Last updated:** September 10, 2026

## Objective

Fill a soft demand window (early September) using leads Maxteriors already paid
for, instead of raising ad spend. Two distinct problems, and they do **not**
share a solution:

1. **The backlog** — hundreds of quotes issued over the last 18 months that
   never closed. One-time campaign.
2. **The leak** — quotes that go quiet from today forward. Always-on sequence.

A third lane (Christmas pre-booking to past customers) rides the same machinery
as lane 1.

## Three lanes, three tools

| Lane | What it reaches | Tool | Status |
|---|---|---|---|
| A. Backlog blast | Quotes already sitting unsold | Pre-booking campaign | Needs capacity number |
| B. Ongoing leak | Quotes sent from now on | `unsold_quote_worker` | Config only |
| C. Christmas renewal | Prior-season lighting customers | Pre-booking campaign | Needs capacity number |

---

## Findings that constrain the design

These came out of reading the code and each one changes the plan. Do not skip.

### 1. The revival worker cannot work the backlog

`app/workers/unsold_quote_worker.py` anchors every touch to the **quote's own
issue date**, not to the day the ladder is switched on.

- `REVIVAL_MIN_OFFSET_DAYS = 15` — days 0–14 belong to
  `post_estimate_followup_worker`. The two never overlap.
- `REVIVAL_MAX_OFFSET_DAYS = 365`
- `MAX_QUOTE_AGE_DAYS = 366` (line 84) — anything older is filtered out of the
  query entirely.

Consequence: enabling the worker sends **nothing** to quotes older than a year,
and exactly **one** message to a 200-day-old quote (its newest due offset).
Everything earlier is written to the ledger as `skipped_stale` (line 314). It
looks like it ran. It didn't.

**The backlog must go through a pre-booking campaign.**

### 2. Workflow-builder branches cannot read quote state

`branch` steps evaluate contact **filter rules** via
`app/services/automations/branching.py`, which reuses `apply_contact_filters` —
the same engine behind saved segments. That engine sees contact fields, tags and
JSONB qualification signals. It does **not** see quote status or quote total.

So a workflow cannot natively ask "is this quote still unsold?" or "is this a
$6K job?". Both require the tag workaround in Appendix B, which has real costs.

### 3. Tags are per-contact; quotes are per-quote

A contact with two open quotes who buys one gets tagged `quote-won`, which kills
revival on the other. The worker avoids this because its dedupe ledger is
quote-scoped. The source calls out this exact failure mode.

### 4. Workflow SMS does not check consent by default

`automation_worker.py:1190` — `require_consent` reads from step config and
defaults to **false**. Quiet hours default to `21:00`–`08:00`
(lines 1175–1176), not the `20:00` used elsewhere. Both must be set explicitly
on every `send_sms` step.

### 5. `{expiry_date}` renders empty when unset

`unsold_quote_worker.py:786` — `quote.expiry_date.isoformat() if ... else ""`.
A template reading `expires {expiry_date}` ships as `expires .` on any quote
with no expiry set. Confirm quotes carry expiry dates before using it.

---

## Lane B — the always-on ladder (do this first, it's cheapest)

Pure configuration. No code, no migration.

### Step 1: create the templates

`POST /api/v1/workspaces/{workspace_id}/message-templates`

Body is `{"name": ..., "message_template": ...}`. Capture each returned `id`.

**Available placeholders** (`render_revival_template`, line 771, which wraps the
shared `render_quote_followup_template`):

`{first_name}` `{last_name}` `{quote_number}` `{quote_total}` `{proposal_url}`
`{company_name}` `{days_since_quote}` `{expiry_date}`

Copy must be **season-neutral** — a quote sent in April hits day 21 in May, so
no "dark by 8" or Christmas angles here. Those belong in lane A.

**`revival-d21-sms`**
```
Hey {first_name} — Max at {company_name}. Your quote {quote_number} is still
{quote_total}; I haven't changed the price. Here it is if you want another
look: {proposal_url} — Max
```

**`revival-d21-sms-highvalue`**
```
Hey {first_name} — Max at {company_name}. On a job the size of yours
({quote_total}) it's worth walking the property together a second time. Most
people want to trim a zone or add one before they commit. Want 20 minutes this
week? — Max
```

**`revival-d45-email`**
```
{first_name},

Your quote from {days_since_quote} days ago is still {quote_total}. Nothing
about it has changed, and I'm not going to chase you about it.

Two things people usually want to know before they decide: parts are warrantied
10 years and labor 1 year, and it's our own crew that comes back out. And you
can spread it over 24 months at 0% instead of paying it all at once.

It's all here: {proposal_url}

Want me to walk you through it on the phone for ten minutes?

— Max
```

**`revival-d90-sms`**
```
Hey {first_name} — Max. Quote {quote_number} is still {quote_total}. Want me to
hold that number, or close the file? — Max
```

### Step 2: apply the ladder

`PUT /api/v1/settings/workspaces/{workspace_id}/unsold-quote-revival`

```json
{
  "enabled": true,
  "high_value_threshold": 6000,
  "max_touches": 4,
  "quiet_hours_start": "20:00:00",
  "quiet_hours_end": "08:00:00",
  "timezone": "America/Detroit",
  "touches": [
    {
      "offset_days": 21,
      "channel": "sms",
      "template_id": "<revival-d21-sms>",
      "high_value_template_id": "<revival-d21-sms-highvalue>"
    },
    { "offset_days": 45,  "channel": "email", "template_id": "<revival-d45-email>" },
    { "offset_days": 90,  "channel": "sms",   "template_id": "<revival-d90-sms>" },
    { "offset_days": 150, "channel": "call" }
  ]
}
```

Notes:

- **`high_value_threshold: 6000`**, not the default 5000. Average job is ~$4K,
  so a $5K floor flags nearly everything as high-value and the variant stops
  meaning anything.
- **Call touches must not carry a template** — the schema validator rejects it
  (`validate_template_usage`). The worker writes the nudge for whoever's assigned.
- Offsets must be **unique and ascending**, and at least one touch must be
  `sms` or `email`.
- Validation is on the **merged** config, so a partial `PUT` that leaves an
  enabled automated touch without a template returns 422:
  `Automated touches on day(s) N need saved message templates`.
- Worker polls hourly (`POLL_INTERVAL_SECONDS = 3600`).

### What the worker gives you for free

Auto-stop on reply or booking, quote-scoped dedupe ledger, opt-out and
quiet-hours compliance, high-value variant. Rebuilding these in the workflow
builder is where the tag workaround starts leaking.

---

## Lane A — the backlog blast (the money this month)

Pre-booking is a deposit-backed seasonal offer, which is the right shape for
filling November/December — it sells a **capped number of slots**.

The warm audience (`app/services/prebooking/audience.py`) OR's three slices:

- `include_past_customers` — completed job **or** approved quote
- `include_unsold_quotes` — status in `("sent", "expired")`, the same constant
  the revival worker uses, so "unsold" has one definition
- `include_prior_season_christmas` — off by default; season arithmetic lives in
  `app/services/seasonal/christmas_renewal.py`

Opt-outs are suppressed three ways: SMS `STOP` (`GlobalOptOut`, matched on
`phone_hash` since the number is encrypted), `Contact.sms_consent_status ==
"opted_out"`, and email unsubscribe (`CampaignContact.opted_out`).

### Sequence

Audience endpoints hang off a **campaign**, so create the campaign first.

```
POST /api/v1/workspaces/{ws}/campaigns
     → campaign_id

POST /api/v1/workspaces/{ws}/campaigns/{campaign_id}/pre-booking
     service_description, season months/year, incentive_value,
     deposit_value, slot_cap, hold_hours

GET  /api/v1/workspaces/{ws}/campaigns/{campaign_id}/pre-booking/audience
       ?include_unsold_quotes=true&include_past_customers=true
     → real counts, opt-outs already excluded, BEFORE anything sends

POST .../pre-booking/audience/enroll
POST .../pre-booking/launch
```

**Run the audience preview before designing anything else.** It replaces the
back-of-napkin "~500 unsold quotes" estimate with the actual number, broken out
by slice.

Send in batches of 50–75/day. The campaign fails on reply capacity, not on copy.

### Launch copy (seasonal — this is where the timing angles live)

Sort into four buckets; a sorted send to 300 beats a blast to 500.

| Bucket | Who | Angle |
|---|---|---|
| A | Quoted last 90 days | Evening demo — dark by 8 now |
| B | Quoted Jan–May 2026 | Price unchanged + 0% financing is new |
| C | Quoted 2025 or earlier | Calendar closing before Christmas installs |
| D | Lost on price | Warranty + monthly payment reframe |

Full five-touch copy (day 1 / 4 / 8 / 15 / 22) is in the chat transcript for
this project. Key reframe for the cross-sell:

> Christmas install is $1,800 this year — and $1,800 every year after.
> Permanent is $4,200 once. That's $175 a month at 0% for 24 months, and it's
> your Christmas lights, your Halloween lights, and your everyday lights.

---

## Open items

- [ ] **Christmas install capacity** — becomes `slot_cap`. Blocks lanes A and C.
- [ ] Run the audience preview for the real backlog count.
- [ ] Confirm quotes carry `expiry_date` before any template uses it.
- [ ] Decide whether fall tune-up ($150–250) gets its own pre-booking offer or
      rides along as a campaign.

---

## Appendix A — why not the workflow builder for lane B

Buildable, with three losses:

1. **No stop-on-reply.** There is no `message_received` trigger in
   `AUTOMATION_TRIGGER_TYPES`. A customer who texts "call me in the spring"
   keeps receiving the ladder until tagged `no-automation` by hand.
2. **Contact-scoped tags vs quote-scoped work** — see finding 3.
3. **No high-value variant** — see finding 2.

Recommended split: revival ladder → the worker; tagging, hot-reply routing,
seasonal pushes and post-job review requests → the workflow builder; backlog →
pre-booking.

## Appendix B — workflow version, if built anyway

Trigger `quote_sent`. Requires three helper automations first:

| Trigger | Action | Config |
|---|---|---|
| `quote_approved` | `apply_tag` | `{"tag": "quote-won"}` |
| `quote_declined` | `apply_tag` | `{"tag": "quote-closed"}` |
| `appointment_booked` | `apply_tag` | `{"tag": "has-appointment"}` |

Then wait/branch/send, guarding before every send:

```json
{"id": "guard1", "type": "branch", "config": {
  "conditions": [{"field": "tags", "operator": "has_none",
    "value": ["quote-won", "quote-closed", "has-appointment", "no-automation"]}],
  "logic": "and", "else_goto": "end"}}
```

Waits of 21 / 24 / 45 / 60 days land the same day-21/45/90/150 cadence. Every
`send_sms` needs `"require_consent": true` and explicit quiet hours (finding 4).
`else_goto` must name a real step id — naming a missing step ends the run
silently, so a terminal `apply_tag` step gives both a clean exit and a segment
of everyone who dropped out.
