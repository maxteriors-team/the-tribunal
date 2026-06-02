# Prestyj Founding Cohort CRM Outbound Launch Plan

Date: 2026-05-27

## Objective

Use The Tribunal CRM production instance to acquire the first Prestyj founding cohort members for the `https://prestyj.com/founding-cohort` offer through outbound SMS/voice campaigns, with the exchange clearly tracked: free 300-ad batch for qualified service businesses in return for a written Google review, 3–5 minute video testimonial, permission to use results/logo/name, and 3 referrals.

## Offer summary from live page

Current public offer positioning:

- Headline: 300 Free Video Ads for 5 Service Businesses.
- Core promise: a $1,497 batch — 300 scripted vertical ads in 24 hours — for free.
- Scarcity: 5 founding case-study spots; page states 2 already claimed as of May 27.
- Ideal recipient: service businesses willing to run ads and provide case-study proof.
- Requirements:
  1. Run the batch for 14+ days at $100/day minimum.
  2. Record a 3–5 minute video testimonial after the test window.
  3. Leave a Google review on delivery.
  4. Give permission to use name, logo, and results in marketing.
- User also wants 3 referrals as part of the exchange.

## CRM capabilities found in this repo

Use these existing surfaces rather than inventing new workflow:

- `/phone-numbers`: search, purchase, sync Telnyx numbers; numbers expose SMS/voice capability.
- `/agents/create`: create voice/text/both agents; tools include built-in contact management and appointment booking/Cal.com tools.
- `/offers/new`: create offers with basics, pricing, value stack, lead magnets, guarantee, urgency, public landing page.
- `/p/offers/{slug}`: unauthenticated public offer landing page created from the CRM offer. Opt-ins create/update contacts and increment offer opt-ins.
- `/find-leads-ai`: search Google/business leads, filter phone/website/toll-free/rating, enrich, import into contacts with quality thresholds.
- `/contacts`: imported/manual contacts; CSV preview/import exists in API.
- `/campaigns/sms/new`: create SMS campaigns, attach an offer, select contacts, choose text AI agent for replies, schedule/rate-limit/follow up.
- `/campaigns/voice/new`: create outbound AI voice campaigns with SMS fallback, select voice agent, contacts, schedule, and rate limit.
- `/calendar` and `/appointments`: appointment tracking and Cal.com sync/reminders.
- `/opportunities`: pipeline/stage/opportunity tracking.
- `/lead-magnets`: optional bonuses/assets that can be attached to the offer.

## Production prerequisites checklist

Do this before any real outreach.

### 1. Backend production readiness

Required Railway/backend environment variables:

- `SECRET_KEY`: strong random value, at least 32 chars; e.g. `openssl rand -hex 32`.
- `ENCRYPTION_KEY`: valid Fernet key for tenant credentials; do not use `change-me-in-production`.
- `DATABASE_URL`: production Postgres URL.
- `REDIS_URL`: production Redis URL.
- `DEBUG=false`.
- `ENVIRONMENT=production`.
- `API_BASE_URL=https://<backend-production-domain>`.
- `FRONTEND_URL=https://<crm-frontend-production-domain>`.
- `PUBLIC_BASE_URL=https://<backend-production-domain>`.
- `CORS_ORIGINS=["https://<crm-frontend-production-domain>","https://prestyj.com"]` if Prestyj forms/widgets will hit backend directly.
- `TRUSTED_PROXIES` set for deployment proxy assumptions.
- Keep only one backend process/replica or one uvicorn worker until workers are leader-elected/extracted. The repo notes all background workers run inside the backend API process and duplicate if replicas/workers multiply.

### 2. Frontend production readiness

Required Vercel/frontend environment variables:

- `NEXT_PUBLIC_API_URL=https://<backend-production-domain>`.
- Optional: `NEXT_PUBLIC_SENTRY_DSN`, `SENTRY_AUTH_TOKEN` if error tracking/source-map upload is desired.

Build/deploy expectations from repo:

- Backend: Railway uses `backend/railway.toml`; pre-deploy runs `alembic upgrade head`; start command runs uvicorn.
- Frontend: deploy from `frontend/` on Vercel with `npm ci` and `npm run build`.

### 3. Integration credentials

Minimum to run outbound:

- OpenAI: `OPENAI_API_KEY` for AI replies/voice.
- Telnyx: `TELNYX_API_KEY`, `TELNYX_PUBLIC_KEY`, `TELNYX_WEBHOOK_SECRET`, `TELNYX_CONNECTION_ID` for SMS/voice and webhooks.
- Cal.com: `CALCOM_API_KEY`, `CALCOM_WEBHOOK_SECRET` if the agent should book qualification calls.
- Google Places: `GOOGLE_PLACES_API_KEY` for `/find-leads-ai` search.
- Resend: `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `RESEND_FROM_NAME=Prestyj` if email delivery/lead magnets are used.
- Stripe is optional for this free cohort offer.

### 4. Webhook setup

Configure provider webhooks to the production backend:

- Telnyx SMS/voice webhook: `https://<backend-production-domain>/webhooks/telnyx/...` using this app’s expected Telnyx webhook paths.
- Cal.com webhook: `https://<backend-production-domain>/webhooks/calcom/...`.
- Resend webhook: `https://<backend-production-domain>/webhooks/resend/...` if using email events.

Then confirm backend `/readyz` is healthy and no startup warnings mention missing critical keys.

## CRM workspace setup

### Step 1 — Create/confirm workspace identity

Create or use one workspace named:

- Workspace: `Prestyj`
- Business: Prestyj
- Default sender identity: `Prestyj Founding Cohort`

Internal tagging convention:

- `prestyj`
- `founding-cohort`
- `outbound-cold`
- `ads-ready`
- `needs-human-review`
- `qualified`
- `not-fit`
- `booked`
- `won-cohort-member`
- `review-due`
- `testimonial-due`
- `referrals-due`
- `do-not-contact`

### Step 2 — Phone number

In `/phone-numbers`:

1. Search for a US number, preferably same area as your target geography if you start local.
2. Buy one number with both SMS and voice capability.
3. If the number already exists in Telnyx, click sync from Telnyx.
4. Confirm it appears as Active with SMS and Voice badges.

Recommended first number name/usage:

- Friendly label: `Prestyj Cohort Outbound`
- Use this number for all first campaign tests to keep attribution clean.

### Step 3 — Booking calendar

In Cal.com:

1. Create an event type: `Prestyj Founding Cohort Qualification Call`.
2. Duration: 15 minutes.
3. Availability: next 5–7 business days.
4. Questions to ask:
   - Business name and website.
   - Monthly ad budget.
   - Can you run at least $100/day for 14 days?
   - Can you record one 15–20 minute founder/owner selfie video?
   - Do you agree to written review, video testimonial, results/logo/name usage, and 3 referrals if accepted?
5. Save the Cal.com event type ID for the CRM agent if needed.

### Step 4 — Create the CRM offer

In `/offers/new`, create:

- Name: `Prestyj Founding Cohort — 300 Free Video Ads`
- Headline: `Get 300 scripted vertical video ads in 24 hours — free for 5 qualified service businesses`
- Subheadline: `We waive the $1,497 batch fee in exchange for a Google review, a 3–5 minute video testimonial, results/logo/name usage rights, and 3 referrals after the test.`
- Discount type: `free_service`
- Discount value: `1497`
- Regular price: `1497`
- Offer price: `0`
- Savings amount: `1497`
- CTA: `Apply for a Founding Spot`
- CTA subtext: `Only a fit if you can run the ads for 14+ days at $100/day minimum.`
- Active: true

Value stack:

1. `300 scripted vertical video ads` — `Hooks, bodies, CTAs, and creative variations built from one 15–20 minute recording across 3 pain points.` — `$1497`.
2. `24-hour delivery window` — `Your finished batch delivered the next day after we receive the recording.` — `$500`.
3. `Founder support during test window` — `Direct line for questions, launch feedback, and performance readout.` — `$500`.
4. `Ad testing map` — `Simple instructions for launching the batch and identifying winners.` — `$300`.

Terms:

```text
Founding cohort acceptance is not automatic. To qualify, the business must sell a real service, have enough demand to run paid social ads, and commit to running the batch for at least 14 days at a minimum of $100/day in ad spend.

In exchange for the $0 founding cohort batch, accepted members agree to: (1) record one 15–20 minute source video, (2) leave a written Google review after delivery, (3) record a 3–5 minute video testimonial after the test window, (4) provide permission for Prestyj to use the business name, logo, creative, and non-private results in marketing, and (5) provide 3 relevant referrals after delivery/test review.

Prestyj may decline applicants who are not a fit, who cannot run the test, or who do not have a clear service offer. The free cohort does not include ad spend, media buying, or a guarantee of sales.
```

Urgency:

- Type: `limited_quantity`
- Text: `Only 5 founding cohort spots. When the 5 accepted members are in, this free batch closes.`
- Scarcity count: set to current remaining spots. If 2 already claimed, set `3`.

Guarantee:

- Type: `satisfaction` or leave off if you do not want “guarantee” language on the CRM page.
- Text if using: `If we accept you and you send the recording, we will deliver the 300-ad batch within 24 hours or tell you before starting why we cannot meet the window.`
- Days: `1` or `14`; be careful because public UI says “X-Day Satisfaction Guarantee.”

Public landing page:

- Enable public landing page.
- Slug: `prestyj-founding-cohort`.
- Require name: true.
- Require email: true.
- Require phone: true.
- Resulting CRM link shape: `https://<crm-frontend-production-domain>/p/offers/prestyj-founding-cohort`.

Important limitation: the current CRM public offer opt-in form only captures name/email/phone. Use the existing Prestyj page or a qualification call for richer application questions unless we add custom questions later.

### Step 5 — Optional lead magnet/bonus

Create one `/lead-magnets` asset if useful:

- Name: `300-Ad Launch Checklist`
- Type: PDF or rich text.
- Estimated value: `$97`.
- Description: `The exact checklist for recording the source video, launching the ad batch, and tracking winners during the 14-day test.`

Attach it to the offer if you want prospects to receive something immediately after opt-in. If not ready, skip lead magnets and keep the CTA purely appointment/application oriented.

## Agent setup

Create two agents if using both SMS and voice. If moving fast, create one `both` agent and use it for SMS replies plus voice campaign.

### Agent A — SMS reply/qualification agent

Route: `/agents/create`

- Pricing: `premium` unless cost requires otherwise.
- Name: `Prestyj Cohort SMS Qualifier`
- Channel mode: `text` or `both`.
- Language: `en-US`.
- Temperature: `0.4`.
- Recording/transcript: enabled where applicable.
- Tools: enable built-in Contact Management. Enable Appointment Booking / Cal.com only if Cal.com credentials and event type are configured.

System prompt:

```text
You are the Prestyj Founding Cohort SMS assistant. Your job is to respond to service business owners who received an outbound message about a free 300-video-ad founding cohort.

Offer facts:
- Prestyj creates 300 scripted vertical video ads from one 15–20 minute owner/founder recording.
- Normal price is $1,497. Founding cohort price is $0 for a small number of qualified service businesses.
- Delivery target is 24 hours after we receive the source recording.
- This is for service businesses that can run the ads for at least 14 days at a minimum of $100/day in ad spend.
- In exchange, accepted members agree to leave a Google review, record a 3–5 minute video testimonial after the test, permit use of their name/logo/results/creative in Prestyj marketing, and provide 3 relevant referrals.
- Ad spend is not included. Prestyj does not guarantee sales.

Conversation goals:
1. Be concise, human, and respectful. Never sound like a spam bot.
2. If they ask what this is, explain the free founding cohort in one or two texts.
3. Qualify them on: service business, website/business type, ability to run $100/day for 14 days, willingness to record the source video, willingness to provide review/testimonial/results permission/3 referrals.
4. If they qualify and show interest, book or offer a 15-minute qualification call.
5. If they are not a fit or say no, politely close and do not pressure.
6. If they opt out, acknowledge once and stop.

Do not claim they are accepted. Say “looks like you may be a fit” or “we can review you for a spot.”
Do not promise results or ROI.
Do not ask for payment.
Always preserve consent and be transparent that this is a business outreach from Prestyj.
```

Qualification criteria for SMS campaign:

```text
Qualified if the contact is a service business owner/operator or marketing decision-maker, has a real business website or public business presence, can run at least $100/day in ads for 14+ days, can record a 15–20 minute source video, and agrees in principle to a written Google review, 3–5 minute video testimonial, usage rights, and 3 referrals if accepted.
```

### Agent B — voice outreach agent

Route: `/agents/create`

- Name: `Prestyj Cohort Voice Qualifier`
- Channel mode: `voice` or `both`.
- Voice provider: OpenAI realtime or preferred production-supported voice provider.
- Max call duration in campaign: 120 seconds for cold first touch.
- Tools: Call Control; Contact Management; Appointment Booking if ready.

Voice system prompt:

```text
You are calling on behalf of Prestyj. You are brief, transparent, and polite. This is a cold business outreach call to see if a service business may be a fit for a free founding cohort.

Opening:
“Hi, this is Prestyj’s assistant. Quick reason I’m calling: we’re taking a few service businesses for a founding cohort where we create 300 vertical video ads for free in exchange for a review, testimonial, results permission, and 3 referrals if it works. Is the owner or person who handles marketing available?”

If interested, qualify:
- Are you a service business and what service do you sell?
- Are you currently running or willing to run Facebook/Instagram ads?
- Could you spend at least $100/day for 14 days to test the ads?
- Could the owner record a 15–20 minute source video?
- If accepted, would you be comfortable with a written review, a 3–5 minute testimonial, name/logo/results usage, and 3 referrals?

If qualified, offer a 15-minute call with the founder to confirm fit.
If not interested, politely thank them and end the call.
If they ask to stop calling, apologize, confirm, and end.
Never say they are accepted. Never promise sales or ROI. Never hide that this is outreach from Prestyj.
```

## Lead sourcing plan

### ICP for first outbound batch

Prioritize businesses that can produce strong case studies and actually run the ads:

- Local service companies with visible owner/operator brands.
- Med spas, aesthetic clinics, chiropractors, dentists, roofers, HVAC, remodelers, personal injury/local lawyers, gyms/fitness studios, high-ticket home services, real estate teams.
- Website present, phone present, decent reviews, active or at least plausible social presence.
- Avoid franchises with gatekeepers, national chains, low-ticket commodity businesses, and businesses with no website/phone.

### Initial search batches in `/find-leads-ai`

Run 5–10 searches with 40–60 max results each. Examples:

- `med spas in Scottsdale AZ`
- `roofing companies in Dallas TX`
- `HVAC companies in Phoenix AZ`
- `cosmetic dentists in Austin TX`
- `personal injury lawyers in Tampa FL`
- `home remodelers in Orange County CA`
- `real estate teams in Miami FL`
- `chiropractors in Charlotte NC`

Filters/settings:

- Has phone: on.
- Has website: on.
- Hide toll-free: on.
- Minimum rating: 4.0+ if enough volume.
- AI enrichment: on.
- Min quality: start at 80; lower to 40 only if volume is too small.
- Import as: `new`.

After import, manually review the first 50 before outreach. Do not blast unreviewed contacts.

### Contact enrichment/tags

For every imported lead, aim to tag/source:

- Source: `find-leads-ai: <query>` if the UI supports it; otherwise notes/tags.
- Tags: `prestyj`, `founding-cohort`, vertical tag (`med-spa`, `roofing`, etc.), city/state, `outbound-cold`.
- Notes should include website, business type, and any personalization angle.

## Campaign sequencing

### Compliance guardrails

Before sending:

- Use business contact numbers only, not scraped personal mobile numbers where possible.
- Include clear identity and opt-out language in SMS.
- Start low volume and monitor opt-outs/complaints.
- Respect “stop,” “unsubscribe,” “not interested,” and any negative replies immediately.
- Avoid implying a prior relationship.
- Avoid guaranteed outcomes.

### Campaign 1 — tiny smoke test

Goal: validate deliverability, replies, AI qualification, and call booking before scale.

Create `/campaigns/sms/new`:

- Name: `Prestyj Cohort SMS Smoke Test — <vertical/city>`
- Description: `10-contact validation batch for founding cohort offer.`
- From: Prestyj outbound number.
- Contacts: 10 hand-reviewed leads.
- Offer: `Prestyj Founding Cohort — 300 Free Video Ads`.
- Agent: `Prestyj Cohort SMS Qualifier`.
- AI enabled: true.
- Sending hours: weekdays only, 10:00 AM–4:00 PM recipient/business local timezone if possible.
- Messages per minute: 5 or lower.
- Max messages/contact: 3.

Initial SMS option A:

```text
Hi {first_name}, this is Nolan with Prestyj. We’re taking a few service businesses as founding case studies: 300 scripted vertical video ads in 24 hours, free, if you can test them with ads and give a review/testimonial/referrals if it works. Worth sending details? Reply STOP to opt out.
```

Initial SMS option B, slightly shorter:

```text
Hi {first_name}, Nolan from Prestyj. We’re giving 5 service businesses a free 300-video-ad batch ($1,497 value) for a founding case study. Catch: you’d need to run the ads + give review/testimonial/3 referrals if accepted. Interested? STOP to opt out.
```

Follow-up 24–48 hours later:

```text
Quick follow-up, {first_name}. The free Prestyj cohort is for service businesses that can run $100/day for 14 days and want 300 ad variations from one owner recording. If it’s not relevant, no worries — reply STOP and I won’t follow up.
```

Success threshold before scaling:

- Less than 5% opt-out/negative rate.
- At least 5–10% reply rate.
- At least 1 qualified conversation or booked call from first 20–30 sends.
- AI replies are accurate and not overpromising.

### Campaign 2 — vertical-specific SMS batch

Create one campaign per vertical/city so copy and results are trackable:

- `Prestyj Cohort — Med Spas — Scottsdale/Phoenix`
- `Prestyj Cohort — Roofers — Dallas`
- `Prestyj Cohort — Dentists — Austin`

Use 25–50 contacts per batch, not hundreds, until the first accepted member is closed.

Vertical-specific openers:

Med spas:

```text
Hi {first_name}, Nolan from Prestyj. We’re looking for a med spa to be a founding case study: we make 300 short-form ad variations from one recording, free, in exchange for testing them + review/testimonial/3 referrals if accepted. Want the details? STOP to opt out.
```

Home services:

```text
Hi {first_name}, Nolan with Prestyj. We’re choosing a few home service companies for a free 300-video-ad batch built from one owner recording. It’s normally $1,497; founding members test the ads and give review/testimonial/3 referrals. Interested? STOP to opt out.
```

Professional services:

```text
Hi {first_name}, Nolan from Prestyj. We’re taking a few local service/professional firms for a free 300 vertical-ad batch as case studies. If you can run the ads for 14 days, we waive the $1,497 fee for review/testimonial/referrals. Worth a look? STOP to opt out.
```

### Campaign 3 — voice + SMS fallback for high-fit leads

Use only after SMS smoke test succeeds or for very high-fit hand-picked leads.

Create `/campaigns/voice/new`:

- Name: `Prestyj Cohort Voice — High Fit Leads — <date>`
- Contacts: 10–25 maximum.
- Voice agent: `Prestyj Cohort Voice Qualifier`.
- SMS fallback enabled: true.
- Fallback template:

```text
Hi {first_name}, Prestyj tried reaching you about a free founding cohort: 300 scripted vertical video ads in 24 hours for qualified service businesses. In exchange we ask for ad test data, a review, testimonial, and 3 referrals if accepted. Want details? STOP to opt out.
```

- Calling hours: Tuesday–Thursday, 10 AM–3 PM.
- Calls per minute: 1.
- Max call duration: 120 seconds.

## Human operating rhythm

Daily, during launch week:

1. Import/review 25–50 leads.
2. Send 10–25 new SMS messages.
3. Check `/campaigns` for delivery/replies/opt-outs.
4. Check conversations and pending actions; manually take over hot/uncertain conversations.
5. Move promising leads to `qualified` or create opportunity.
6. Book qualification calls for interested leads.
7. End each day with a short campaign note: sent, replies, qualified, booked, opt-outs, objections.

## Qualification call script

Opening:

```text
Thanks for taking the call. The offer is simple: if you’re a fit, we create the 300-ad batch free instead of $1,497. We’re doing that because we want real case studies, reviews, testimonials, and referrals from businesses that will actually run the ads.
```

Questions:

1. What service do you sell and what is an average customer worth?
2. Are you currently running paid social ads? If not, have you run them before?
3. Can you commit to at least $100/day for 14 days?
4. Who will record the 15–20 minute source video?
5. Do you have any offers/promotions you already know convert?
6. Are you comfortable giving a Google review after delivery?
7. Are you comfortable recording a 3–5 minute video testimonial after the 14-day test?
8. Are you comfortable with us using your logo/name/non-private results/creative?
9. Can you introduce 3 relevant business owners if the batch is delivered as promised?

Acceptance criteria:

- Clear service offer.
- Can afford ad test.
- Decision-maker agrees to obligations.
- Can record quickly.
- Has enough urgency and credibility for a case study.

If accepted, next steps:

- Send source-video instructions.
- Confirm testimonial/review/referral agreement in writing.
- Set expected delivery and launch date.
- Create opportunity as `Won cohort member` or move stage.

If not accepted:

- Keep relationship warm.
- Offer paid path or waitlist if appropriate.

## Pipeline/opportunity setup

Create a pipeline in `/opportunities`:

- Pipeline: `Prestyj Founding Cohort`

Suggested stages:

1. `Imported lead` — 0%.
2. `Contacted` — 10%.
3. `Replied` — 25%.
4. `Qualified` — 50%.
5. `Call booked` — 65%.
6. `Accepted / assets requested` — 80%.
7. `Batch delivered` — 90%.
8. `Won cohort member` — 100%.
9. `Not fit / lost` — 0%.

Opportunity fields:

- Amount: `$1497` value even though price is `$0`; this tracks value given away.
- Source: campaign name.
- Primary contact: decision-maker contact.
- Notes: obligations and status.

## Fulfillment handoff tracking

For accepted members, add contact/opportunity notes with this checklist:

- Agreement confirmed in writing.
- Source video received.
- 300 ads delivered.
- Google review requested.
- Google review received.
- 14-day test started.
- 14-day test completed.
- Results collected.
- Video testimonial requested.
- Video testimonial received.
- 3 referral names requested.
- Referral 1 received.
- Referral 2 received.
- Referral 3 received.

Use tags:

- `review-due`
- `review-received`
- `testimonial-due`
- `testimonial-received`
- `referrals-due`
- `referrals-received`

## KPI dashboard to watch manually in CRM

Campaign-level:

- Contacts sent.
- Delivered.
- Failed.
- Replies.
- Opt-outs.
- Qualified.
- Appointments booked.

Offer-level:

- Public offer page views.
- Opt-ins.

Business-level:

- Leads imported.
- Replies per vertical.
- Booked calls.
- Accepted members.
- Reviews collected.
- Testimonials collected.
- Referrals collected.

Initial targets:

- First 30 reviewed contacts: 3+ replies, 1+ booked call.
- First 100 reviewed contacts: 10+ replies, 3+ calls, 1 accepted member.
- Stop/adjust any sequence with negative/opt-out rate above 5–8%.

## Suggested launch timeline

### Day 0 — production hardening

- Confirm backend/frontend deploys are live.
- Confirm env vars/integrations.
- Confirm `/readyz`.
- Confirm login and workspace.
- Buy/sync phone number.
- Create Cal.com event.

### Day 1 — CRM asset build

- Create offer.
- Publish public CRM offer page.
- Create agent(s).
- Create pipeline/stages.
- Create first lead magnet only if already available.
- Import 25–50 hand-reviewed leads.

### Day 2 — smoke test

- Launch 10-contact SMS smoke test.
- Monitor replies live.
- Fix agent prompt/copy if needed.
- Manually book first calls.

### Day 3–4 — first real batches

- Send 25–50 contacts per vertical.
- Add voice follow-up only to high-fit non-repliers.
- Create opportunities for all replies/qualified leads.

### Day 5–7 — close first member

- Run qualification calls.
- Accept the highest-fit business.
- Fulfill fast.
- Begin review/testimonial/referral tracking immediately.

## What I can help execute next

1. Production readiness audit: inspect deployed env/config checklist and produce missing-variable list.
2. Offer creation: turn the above offer copy into exact CRM fields while you click through, or create a seed/script if production API access is available.
3. Agent prompts: refine for SMS/voice and create test conversations.
4. Lead sourcing: build the first 100-lead target list and import plan.
5. Campaign launch: set up the smoke test campaign, monitor replies, and iterate copy.

## Open decisions needed from Nolan

- What is the CRM production frontend URL and backend URL?
- Which city/vertical should the first 25-contact batch target?
- Do we use the CRM public offer page, the existing `prestyj.com/founding-cohort` page, or both?
- Do you already have a Telnyx outbound number, Cal.com event type, and Google Places API key in production?
- Are you comfortable with cold SMS as the first channel, or should the first batch be manual/voice/warm outbound?
