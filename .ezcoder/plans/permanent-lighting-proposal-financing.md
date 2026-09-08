# Permanent Lighting proposal and GreenSky financing

Status: ready for implementation after approval

## Objective

Make the public Permanent Lighting proposal a strong video-meeting sales surface with two unmistakable next steps: accept and pay the configured Stripe deposit, or open GreenSky's official application while keeping the proposal available. The project price must be the same whichever path the customer explores.

## Settled decisions

- Scope one-price presentation to Permanent Lighting only. Existing landscape, Christmas, bistro, and other service pricing remains unchanged.
- The customer sees the same Permanent project price for deposit and GreenSky paths. Maxteriors absorbs GreenSky's 15.25% merchant fee; it is never itemized, surcharged, or used to raise the financed customer's price.
- The configured GreenSky offer is 0% APR for 24 months. Its real merchant number, plan number, and provider-approved wording must be entered in Settings.
- Customers may open GreenSky before accepting the proposal. A GreenSky application neither accepts the proposal nor guarantees financing.
- Deposit payment remains behind recorded proposal acceptance and uses the existing Stripe Checkout flow.
- Do not collect credit-application fields, receive lending decisions, or infer application status in Tribunal.

## Existing system

- `frontend/src/components/proposal/client-proposal-view.tsx` already renders the public rich proposal, design mockups, night previews, exact price/range, acceptance, and deposit state.
- `frontend/src/components/proposal/deposit-panel.tsx` already starts Stripe Checkout after acceptance and reports pending/paid deposit states.
- `frontend/src/app/p/quotes/[token]/page.tsx` currently sends every deposit-bearing approval directly to Stripe. GreenSky-enabled Permanent proposals need to remain on the proposal after acceptance so the customer can explicitly choose the deposit path.
- `backend/app/schemas/pricing.py` stores workspace pricing as validated JSON under `Workspace.settings`; adding GreenSky settings requires no database migration.
- `backend/app/services/quotes/proposal_builder.py` snapshots customer-facing proposal facts into `proposal_document`; newly generated proposals can therefore preserve the GreenSky details shown at sale time.
- Public proposal links are capability URLs. Any external GreenSky link must suppress the `Referer` header so the proposal token is never disclosed.

## Design read

- **Surface:** customer-facing proposal/commerce hybrid, presented live by a consultant but still usable asynchronously.
- **Audience:** homeowners making a high-cost decision; assume touch, keyboard, mobile, and desktop use.
- **Single job:** understand the finished Permanent Lighting vision, then confidently choose deposit or GreenSky as the next step.
- **Risk:** high decision cost; unclear pricing, accidental contract acceptance, deposit ambiguity, or unverified credit claims are unacceptable.
- **Content:** customer identity, house imagery, one project price or range, deposit amount, GreenSky's merchant/plan numbers, approved 0%-for-24-month wording, and lender disclosures.
- **Local visual language:** retain the proposal's existing dark charcoal, warm gold accent, editorial display type, large house imagery, and single content rail.
- **Responsive rule:** two peer payment paths at desktop widths, one ordered column on narrow screens, with no horizontal overflow at 320px.

## Design thesis

The house preview remains the emotional first glance; one calm "Choose how to move forward" rail becomes the second glance. It repeats the same project price once, then presents two genuinely peer choices: a deposit path and an external financing path. The two-card layout is justified by exactly two mutually understandable next steps, not by decorative card repetition. Use existing borders, typography, buttons, spacing, and Lucide icons only where they clarify an action. Add no GreenSky logo, invented badge, glass effect, gradient hero, fake urgency, testimonial, approval claim, or hover lift.

Permanent-specific hero copy will name the customer's "permanent lighting plan" and year-round design without adding unsupported hardware, warranty, savings, or performance claims. Real mockups and night previews remain the persuasive device.

## Backend contract

### Workspace settings

In `backend/app/schemas/pricing.py` add:

- `PermanentGreenSkyConfig`: `enabled`, optional digits-only `merchant_number` and `plan_number`, bounded `term_months`, bounded `apr_percent`, and short provider-approved `offer_details`.
- `PermanentConfig.green_sky`, defaulting disabled with no fabricated merchant, plan, or promotional values.
- Validation that rejects enabling GreenSky without complete merchant, plan, term, APR, and approved-copy fields. Disabled configurations may retain drafts.
- The Maxteriors production setup uses 0% APR and 24 months. The 15.25% merchant fee is not part of the public contract and is never sent to the customer.

The application destination is not operator-controlled. Use the currently verified official HTTPS endpoint `https://projects.greensky.com/applyshort`, avoiding a public phishing/open-redirect surface.

### Proposal snapshot

In `backend/app/schemas/proposal_wizard.py` add an optional public-safe GreenSky snapshot to `ProposalDocument` containing only:

- the fixed application URL;
- merchant and plan numbers;
- the configured APR, term, and provider-approved offer details;
- a fixed plain-language lender/application disclosure.

The public snapshot never includes GreenSky's 15.25% merchant fee.

In `backend/app/services/quotes/proposal_builder.py`:

- include the snapshot only when the proposal service is exactly `permanent` and GreenSky is enabled;
- omit it for incomplete, disabled, mixed-service, and every non-Permanent proposal;
- normalize public Permanent-only `cash_total` values to the existing contract total and zero cash savings, so the customer sees one price without changing quote economics or repricing other services;
- leave existing global financing fee, discount, eligibility, and monthly-estimate behavior unchanged for every other service.

Existing saved proposal snapshots remain immutable. Staff must regenerate/save a proposal after enabling GreenSky for the card to appear.

## Staff setup

Extend `frontend/src/components/settings/permanent-pricing-settings-card.tsx` and `frontend/src/types/sales-wizard.ts` with a GreenSky section:

- enable/disable control;
- merchant and plan numbers;
- APR, term, and provider-approved offer details, with the production values set to 0% and 24 months;
- an inline validation summary and disabled save when enabled data is incomplete;
- read-only guidance that GreenSky charges Maxteriors 15.25%, that this fee must not be passed to the borrower, and that customers submit financial information directly to GreenSky;
- copy requiring staff to use only GreenSky-approved program language.

Do not prefill fake plan IDs or promotional terms. Existing billing read/write permission gates continue to protect these settings.

## Customer flow

Create `frontend/src/components/proposal/permanent-payment-options.tsx` and integrate it through `client-proposal-view.tsx`:

1. Show the selected Permanent project price once above the options and state that it is the same for either path.
2. Deposit path: show the exact configured amount due, explain acceptance first, and lead to the existing Stripe Checkout. If no deposit is configured, state that plainly rather than inventing an amount.
3. GreenSky path: show `0% APR for 24 months`, merchant and plan numbers, ordered application steps, and an accessible `Start GreenSky application` external link.
4. State that the 0%/24-month program is subject to credit approval and the customer's GreenSky loan documents; applying does not accept this proposal, reserve an installation date, or guarantee approval.
5. Open GreenSky in a new tab with `rel="noopener noreferrer"` and `referrerPolicy="no-referrer"`; send no customer data, proposal token, merchant fee, or tracking parameters.
6. Hide the generic monthly-payment estimator whenever the specific GreenSky block is present, preventing conflicting or unapproved payment claims.
7. For GreenSky-enabled Permanent proposals, acceptance updates the proposal but does not auto-redirect to Stripe. The deposit card then exposes the existing explicit `Pay deposit` action. All existing non-GreenSky acceptance-to-checkout behavior remains unchanged.
8. Expired or declined proposals do not offer active payment/application actions. Paid deposits suppress the alternative application action.

The top visual CTA becomes `Review payment options` when GreenSky is available and scrolls to the semantic payment heading. The standard acceptance section remains the contract action; GreenSky never silently accepts on the customer's behalf.

## Accessibility and resilience

- Use a real section heading, ordered lists for steps, definition-list semantics for merchant/plan numbers, native buttons/links, and visible `:focus-visible` treatment.
- Give the external link an accessible name announcing that it opens GreenSky in a new tab.
- Maintain one shared content rail and a single-column mobile flow; long labels/details wrap instead of widening the page.
- Preserve usable content when imagery is missing and preserve proposal/deposit recovery states.
- Keep application details and disclosure printable while hiding only interactive controls.
- Respect reduced motion; add no new ambient animation or `transition: all`.
- Automated checks are evidence, not a claim of legal or WCAG conformance; keyboard, zoom/reflow, contrast, and assistive-technology checks remain separately recorded.

## Compliance and security controls

- Tribunal acts only as a merchant-facing referral surface to GreenSky's official application. It does not originate credit, make decisions, collect application data, or claim to be a lender.
- GreenSky Merchant Program Agreement v7.1, dated June 30, 2026, sections 5(b) and 11(a)(x) prohibit passing merchant transaction fees to borrowers through a surcharge or higher financed price. The customer therefore sees one project price, and Maxteriors absorbs the 15.25% fee.
- Show 0% APR for 24 months only from the configured, provider-approved plan. Do not invent approval odds, alternate terms, or savings claims.
- Include a link to GreenSky's current official disclosures and identify GreenSky Servicing, LLC as a financial technology company, not a lender; program lenders determine credit and terms.
- GreenSky remains disabled until merchant/plan details and approved offer wording are complete. Provider/counsel review of merchant marketing obligations, exact plan copy, trademark treatment, and Equal Housing Lender presentation remains a launch prerequisite outside code.
- Update `COMPLIANCE.md` with a dated, scoped addendum labelled NOT LEGAL ADVICE and distinguish runtime, code, and deduced evidence.
- Never log merchant application interactions as customer credit intent and never place proposal capabilities in outbound referrers.

## Files

Backend/API:

- `backend/app/schemas/pricing.py`
- `backend/app/schemas/proposal_wizard.py`
- `backend/app/services/quotes/proposal_builder.py`
- `backend/tests/api/test_pricing_settings_financing_api.py`
- `backend/tests/services/quotes/test_proposal_builder.py`
- `backend/tests/services/quotes/test_financing_regression.py`
- `backend/openapi.json`

Frontend:

- `frontend/src/types/sales-wizard.ts`
- `frontend/src/lib/api/_generated.ts`
- `frontend/src/components/settings/permanent-pricing-settings-card.tsx`
- `frontend/src/components/settings/permanent-pricing-settings-card.test.tsx`
- `frontend/src/components/proposal/document.ts`
- `frontend/src/components/proposal/permanent-payment-options.tsx` (new)
- `frontend/src/components/proposal/client-proposal-view.tsx`
- `frontend/src/components/proposal/client-proposal-view.test.tsx`
- `frontend/src/components/proposal/proposal-theme.css`
- `frontend/src/app/p/quotes/[token]/page.tsx`
- `frontend/src/app/p/quotes/[token]/page.test.tsx`
- `frontend/DESIGN.md`

Governance:

- `COMPLIANCE.md`
- `.ezcoder/plans/permanent-lighting-proposal-financing.md`

No new dependency and no database migration are expected.

## Verification criteria

- Backend settings tests prove authorized round-trip, disabled defaults, bounded/trimmed values, incomplete-enabled rejection, fixed production 0%/24-month values, and non-Permanent isolation.
- Proposal-builder tests prove the GreenSky snapshot contains no customer PII or merchant fee, appears only for Permanent Lighting, preserves old snapshots, and produces one public contract price.
- Existing financing regression tests prove landscape and every other service retain current price calculations.
- Frontend settings tests prove complete payloads, incomplete-state blocking, 0%/24-month display, and no fabricated defaults.
- Public proposal tests prove one project price, exact deposit copy, pre-acceptance GreenSky availability, approved 0%/24-month copy, official fixed URL, no-referrer attributes, disclosure text, expired/declined suppression, paid-deposit suppression, and absence of duplicate generic financing estimates.
- Page-flow tests prove GreenSky-enabled approval stays on-page while legacy deposit-bearing approval still opens Stripe Checkout.
- `make ci.codegen` is clean; targeted backend/frontend tests pass; `make ci.all` exits zero.
- Runtime public-proposal fixture is captured at desktop, 390px, and 320px; no horizontal overflow; keyboard order and visible focus pass; Axe reports no tested A/AA violations.
- The external GreenSky page responds and still asks for merchant and plan numbers; failure leaves the proposal open and usable.
- Production backend reports the deployed main ancestor and passes readiness/backend smoke; both frontend aliases serve the final Vercel deployment and frontend smoke passes.

## Release strategy

Use a new clean worktree because the original checkout contains preserved user work. Release additively in two stages:

1. Backend/schema/OpenAPI/generated-client PR, merge to protected `main`, deploy Railway from updated clean `main`, then verify `/version`, readiness, and backend smoke.
2. Frontend/customer/settings/docs PR from updated `main`, merge, wait for Vercel production readiness, verify both aliases and frontend smoke.

GreenSky is disabled by default. After deployment, an authorized user enters the real merchant number and provider-approved plan details in Settings, regenerates a Permanent proposal, and confirms the card before sharing it with customers.

## Risks and prerequisites

- **External prerequisite:** the repository contains no GreenSky merchant number or approved plan details. The production option cannot be enabled until an authorized user supplies them in Settings.
- **Provider/legal review:** linking is technically safe, but exact promotional copy, marks, and lender disclosures must be approved for this merchant program. This plan does not certify legality or compliance.
- **Old proposals:** proposal snapshots intentionally do not mutate. Existing links need regeneration to gain GreenSky details.
- **External availability:** GreenSky owns the application page. Opening a separate tab contains outages; Tribunal must not claim an application started or succeeded.
- **Pricing:** Permanent shows one contract price for both paths. Maxteriors absorbs the 15.25% fee; the implementation must never expose it or derive a GreenSky-specific surcharge. Other services remain unchanged.

## Steps

1. Create a clean backend release worktree from current `origin/main` without touching the preserved dirty checkout.
2. Add validated Permanent GreenSky merchant, plan, 0%-APR, 24-month, and approved-copy settings with disabled-safe defaults.
3. Add the public-safe GreenSky proposal snapshot and Permanent-only one-price normalization, excluding the 15.25% merchant fee.
4. Add backend settings, builder, isolation, and pricing-regression tests.
5. Regenerate OpenAPI and the frontend generated client, then verify codegen is clean.
6. Run targeted backend checks and the full backend-relevant CI gate.
7. Commit conventionally, open the backend PR, pass required checks, merge, deploy Railway, and smoke-test production.
8. Create a clean frontend release worktree from the newly deployed `origin/main`.
9. Add GreenSky setup controls to Permanent Pricing Settings with complete-state validation and fee-pass-through warning.
10. Build the responsive Permanent payment-options component with one project price, deposit steps, and approved 0%-for-24-month copy.
11. Separate GreenSky-enabled acceptance from explicit Stripe deposit checkout while preserving every legacy flow.
12. Add frontend component, settings, page-flow, external-link, and accessibility regression tests.
13. Update the design record, compliance register, and approved implementation plan.
14. Run codegen validation, targeted frontend checks, full CI, and desktop/mobile runtime visual-accessibility probes.
15. Commit conventionally, open the frontend PR, pass required checks, merge, and verify the final Vercel deployment on both aliases.
16. Enable GreenSky in production Settings only after entering the real merchant number, plan number, 0% APR, 24-month term, and provider-approved offer wording; then regenerate and inspect a Permanent proposal.
