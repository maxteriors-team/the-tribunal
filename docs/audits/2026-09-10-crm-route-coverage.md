# CRM continuation: explicit 87-route coverage matrix

Status: **partial audit, not whole-journey verification**. See [findings, numeric reconciliation, role coverage and remaining work](2026-09-10-crm-audit-continuation.md). This preserves the denominator from [the original audit](2026-09-09-crm-ux-reporting-audit.md); no route is silently excluded because it redirects, is public, or is a developer page.

## Evidence legend and bounds

- **R**: real local page rendered against synthetic, primarily empty, OpenAPI-derived responses. Screenshot and DOM/request metadata captured. This is NOT proof that the backend accepted a transaction or a customer journey completed.
- **K12**: first twelve desktop Tab stops recorded, including visible-focus and viewport observations. Often this only reaches navigation. NOT a completed keyboard flow, focus-trap test, screen-reader test, or WCAG conformance claim.
- **T**: separately named existing test passed. The continuation report lists these; they do not upgrade every route in a domain.
- **U**: full transaction/recovery journey not verified in this continuation. Earlier Practice Arena, invoices, reports, contacts and Today evidence remains historical and does not transfer to other journeys.
- **R / R / K12** means desktop 1440×1000 / mobile 390×844 / limited keyboard capture. Mobile is a resized Chromium viewport, not a physical touch-device or mobile-browser test. Screenshots are viewport captures, not full scroll-throughs.

Artifacts are local, ignored audit evidence under `.ezcoder/eyes/out/crm-audit-20260910/`. For each stem below: `<stem>-desktop.png`, `<stem>-mobile.png`, and `<stem>.json` contain the evidence. `coverage.cjs` is the reproducer; `coverage-results.json` is the completed run manifest. Its SHA-256 is `d43c3f88c162970b03c45aae05e01b4899b6a9eb927ac45428611937438ee1e6`.

All 87 rows have two captures and K12 metadata. There were zero uncaught page errors in that final initial-state run. There was one measured document overflow, **527px at a 390px viewport on `/dev/components`**, explicitly a developer-only gallery. The other 86 initial states had document width ≤390px. These numbers do not prove that populated tables, opened dialogs, lower-page controls, or validation/error states reflow correctly. Basic unnamed-button heuristics are investigation leads only; associated HTML labels must be checked before reporting an accessibility failure.

## Inventory

| Route | Artifact stem | Desktop / mobile / keyboard | Exact observation scope | Full journey this continuation |
|---|---|---|---|---|
| `/` | `01-root` | R / R / K12 | Anonymous redirect to `/login` | U |
| `/agents` | `02-agents` | R / R / K12 | Fixture initial state | U |
| `/agents/[id]` | `03-agents-id` | R / R / K12 | Synthetic detail | U |
| `/agents/create` | `04-agents-create` | R / R / K12 | Builder entry | U |
| `/agents/practice` | `05-agents-practice` | R / R / K12 | Setup only; separate choice-control test | U |
| `/assistant` | `06-assistant` | R / R / K12 | Empty conversation | U |
| `/automations` | `07-automations` | R / R / K12 | Empty list | U |
| `/billing` | `08-billing` | R / R / K12 | Synthetic subscription state, no checkout | U |
| `/calendar` | `09-calendar` | R / R / K12 | Empty appointments/jobs | U |
| `/calls` | `10-calls` | R / R / K12 | Empty history, no dial | U |
| `/campaigns` | `11-campaigns` | R / R / K12 | Empty list | U |
| `/campaigns/[id]` | `12-campaigns-id` | R / R / K12 | Synthetic detail | U |
| `/campaigns/email/new` | `13-campaigns-email-new` | R / R / K12 | Builder entry | U |
| `/campaigns/new` | `14-campaigns-new` | R / R / K12 | Channel chooser, not campaign execution | U |
| `/campaigns/pre-booking/new` | `15-campaigns-pre-booking-new` | R / R / K12 | Builder entry | U |
| `/campaigns/sms/new` | `16-campaigns-sms-new` | R / R / K12 | Builder entry | U |
| `/campaigns/voice/new` | `17-campaigns-voice-new` | R / R / K12 | Builder entry | U |
| `/catalog` | `18-catalog` | R / R / K12 | Fixture initial state | U |
| `/christmas-lights` | `19-christmas-lights` | R / R / K12 | Estimator entry | U |
| `/christmas-lights/renew` | `20-christmas-lights-renew` | R / R / K12 | Renewal entry | U |
| `/contacts` | `21-contacts` | R / R / K12 | Empty list; separate import/control tests | U |
| `/contacts/[id]` | `22-contacts-id` | R / R / K12 | Synthetic detail | U |
| `/contacts/[id]/details` | `23-contacts-id-details` | R / R / K12 | Synthetic detail | U |
| `/dashboard` | `24-dashboard` | R / R / K12 | Empty counters; separate DB service probe | U |
| `/dev/components` | `25-dev-components` | R / R / K12 | Developer gallery; mobile overflow 527px | U |
| `/embed/[publicId]` | `26-embed-publicId` | R / R / K12 | Synthetic public configuration | U |
| `/embed/[publicId]/both` | `27-embed-publicId-both` | R / R / K12 | Synthetic public configuration | U |
| `/embed/[publicId]/chat` | `28-embed-publicId-chat` | R / R / K12 | Synthetic public configuration | U |
| `/embed/[publicId]/fullpage` | `29-embed-publicId-fullpage` | R / R / K12 | Synthetic public configuration | U |
| `/estimator` | `30-estimator` | R / R / K12 | Redirect to `/quotes`, light designer | U |
| `/experiments` | `31-experiments` | R / R / K12 | Empty list | U |
| `/experiments/[id]` | `32-experiments-id` | R / R / K12 | Synthetic detail | U |
| `/experiments/new` | `33-experiments-new` | R / R / K12 | Builder entry | U |
| `/find-leads` | `34-find-leads` | R / R / K12 | Discovery entry, no provider search | U |
| `/find-leads-ai` | `35-find-leads-ai` | R / R / K12 | AI discovery entry, no model call | U |
| `/find-leads/ad-library` | `36-find-leads-ad-library` | R / R / K12 | Search entry, no provider search | U |
| `/find-leads/people` | `37-find-leads-people` | R / R / K12 | Search entry, no provider search | U |
| `/forgot-password` | `38-forgot-password` | R / R / K12 | Form entry, no email | U |
| `/inventory` | `39-inventory` | R / R / K12 | Empty list; separate stock-cost service probe | U |
| `/invite/[token]` | `40-invite-token` | R / R / K12 | Synthetic token state, no accepted invite | U |
| `/invoices` | `41-invoices` | R / R / K12 | Empty list; separate AR/P&L probe | U |
| `/jobs` | `42-jobs` | R / R / K12 | Empty list; separate cost probe | U |
| `/knowledge` | `43-knowledge` | R / R / K12 | Fixture initial state | U |
| `/landscape-lighting` | `44-landscape-lighting` | R / R / K12 | Designer entry | U |
| `/landscape-lighting/[projectId]` | `45-landscape-lighting-projectId` | R / R / K12 | Synthetic project | U |
| `/lead-magnets` | `46-lead-magnets` | R / R / K12 | Empty list | U |
| `/lead-magnets/new` | `47-lead-magnets-new` | R / R / K12 | Builder entry | U |
| `/login` | `48-login` | R / R / K12 | Form entry, no real authentication | U |
| `/messages` | `49-messages` | R / R / K12 | Empty conversations, no send | U |
| `/nudges` | `50-nudges` | R / R / K12 | Empty queue | U |
| `/offers` | `51-offers` | R / R / K12 | Empty list | U |
| `/offers/[id]` | `52-offers-id` | R / R / K12 | Synthetic detail | U |
| `/offers/new` | `53-offers-new` | R / R / K12 | Builder entry | U |
| `/onboarding` | `54-onboarding` | R / R / K12 | Calendar prerequisite/skip entry only | U |
| `/opportunities` | `55-opportunities` | R / R / K12 | Empty pipeline | U |
| `/opportunities/[id]` | `56-opportunities-id` | R / R / K12 | Synthetic detail | U |
| `/p/compare/[token]` | `57-p-compare-token` | R / R / K12 | Synthetic token state | U |
| `/p/invoices/[token]` | `58-p-invoices-token` | R / R / K12 | Synthetic token state, no payment | U |
| `/p/landing` | `59-p-landing` | R / R / K12 | Public entry only | U |
| `/p/offers/[slug]` | `60-p-offers-slug` | R / R / K12 | Synthetic public offer state | U |
| `/p/quotes/[token]` | `61-p-quotes-token` | R / R / K12 | Synthetic token state, no approval/deposit | U |
| `/p/referral-partners/intake` | `62-p-referral-partners-intake` | R / R / K12 | Form entry only | U |
| `/p/reviews/[token]` | `63-p-reviews-token` | R / R / K12 | Synthetic token state | U |
| `/payment-cancelled` | `64-payment-cancelled` | R / R / K12 | Static result page, not payment proof | U |
| `/payment-complete` | `65-payment-complete` | R / R / K12 | Static result page, not payment proof | U |
| `/pending-actions` | `66-pending-actions` | R / R / K12 | Empty queue, no approved tool execution | U |
| `/permanent-lighting` | `67-permanent-lighting` | R / R / K12 | Designer entry | U |
| `/permanent-lighting/[projectId]` | `68-permanent-lighting-projectId` | R / R / K12 | Synthetic project | U |
| `/phone-numbers` | `69-phone-numbers` | R / R / K12 | Fixture initial state; no purchase | U |
| `/quotes` | `70-quotes` | R / R / K12 | Estimator/designer entry | U |
| `/referral-partners` | `71-referral-partners` | R / R / K12 | Empty list | U |
| `/referral-partners/[partnerId]` | `72-referral-partners-partnerId` | R / R / K12 | Synthetic detail | U |
| `/register` | `73-register` | R / R / K12 | Form entry, no real registration | U |
| `/reports` | `74-reports` | R / R / K12 | Empty/synthetic windows; separate DB probe | U |
| `/reports/sales` | `75-reports-sales` | R / R / K12 | Empty counters | U |
| `/reset-password` | `76-reset-password` | R / R / K12 | Form entry, no real reset | U |
| `/reviews` | `77-reviews` | R / R / K12 | Empty list, no review request | U |
| `/sales-onboarding` | `78-sales-onboarding` | R / R / K12 | Redirect to `/today` | U |
| `/scoreboard` | `79-scoreboard` | R / R / K12 | Empty counters | U |
| `/scorecard` | `80-scorecard` | R / R / K12 | Empty counters; separate DB service probe | U |
| `/segments` | `81-segments` | R / R / K12 | Empty list | U |
| `/service-plans` | `82-service-plans` | R / R / K12 | Empty list | U |
| `/settings` | `83-settings` | R / R / K12 | Initial settings tab only | U |
| `/suggestions` | `84-suggestions` | R / R / K12 | Empty recommendations | U |
| `/time` | `85-time` | R / R / K12 | Empty attendance; no clock-in/out | U |
| `/today` | `86-today` | R / R / K12 | Empty queue | U |
| `/upsell` | `87-upsell` | R / R / K12 | Fixture initial state | U |

## Completion rule

Do not replace U with verified because a screenshot, unit test in the same directory, schema fixture, source inspection, or static payment-success page exists. Record the exact role, synthetic record IDs, action/recovery steps, API effects, provider fake, keyboard completion and narrow-layout evidence first. The original whole-CRM task remains open until the continuation report's remaining journey checks are completed or explicitly rescoped by the user.
