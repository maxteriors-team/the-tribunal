# Permanent Lighting proposal and GreenSky financing

Status: approved and implementing · updated 4 September 2026

## Objective

Make the public Permanent Lighting proposal a strong video-meeting sales surface with two unmistakable next steps: accept and pay the configured Stripe deposit, or open GreenSky's official application while keeping the proposal available. The project price must be the same whichever path the customer explores.

## Settled decisions

- One-price presentation applies only to Permanent Lighting. Landscape, Christmas, bistro, and mixed-service economics remain unchanged.
- The customer sees the same Permanent project price for deposit and GreenSky. Maxteriors absorbs GreenSky's 15.25% merchant fee; it is never itemized, surcharged, or used to increase the financed price.
- Production uses a provider-approved 0% APR / 24-month program. Real merchant and plan numbers and exact approved wording must be entered in Settings.
- GreenSky may open before proposal acceptance. Applying neither accepts the proposal nor guarantees financing or reserves installation.
- Stripe deposit payment remains behind recorded proposal acceptance.
- Tribunal does not collect credit fields, receive lending decisions, infer application status, or log application intent.
- The application destination is fixed at `https://projects.greensky.com/applyshort`; operators cannot override it.
- Existing saved proposal snapshots remain immutable. Staff must regenerate a Permanent proposal after enabling GreenSky.
- GreenSky remains disabled until complete configuration and provider/counsel launch review.

## Delivered backend contract

Backend PR #227 merged to protected `main` and deployed as `a8aef252d6ecc0965fec6e30cf031b16ccd5af6e`.

- `PermanentGreenSkyConfig` stores a disabled-safe enable flag, optional digits-only merchant/plan numbers, bounded APR/term, and short approved offer copy.
- Enabling an incomplete program fails validation; disabled configurations may retain valid incomplete drafts.
- `ProposalDocument.green_sky` snapshots only the fixed URL, merchant/plan numbers, APR, term, approved details, and fixed lender/application disclosure.
- GreenSky snapshots appear only for exactly `permanent`; disabled, incomplete, mixed, and non-Permanent proposals omit them.
- Public Permanent cash totals equal the existing contract total with zero cash savings; quote line economics are unchanged.
- The 15.25% merchant fee and customer PII never enter the public GreenSky snapshot.
- OpenAPI and the generated TypeScript client were regenerated deterministically.

Backend proof: `make ci.backend` passed 5,292 tests with 61.87% coverage; `make ci.codegen` and 35 focused tests passed. Production readiness and six backend smoke tests passed.

## Delivered frontend behavior

### Staff setup

Permanent Pricing Settings now provides:

- enable/disable control;
- merchant and plan number fields;
- APR and term fields, initialized to the settled 0% / 24-month values when first enabled;
- provider-approved offer details;
- inline completeness/format validation and a disabled Save action while invalid;
- guidance that Maxteriors absorbs 15.25%, never surcharges the borrower, and receives no credit decision;
- no fake merchant number, plan number, or offer copy.

Existing billing read/write permission gates remain unchanged.

### Customer proposal

`PermanentPaymentOptions` provides one project price above two peer cards:

1. Deposit: exact configured amount, acceptance-first explanation, and the existing explicit Stripe action after acceptance. Missing deposits are stated plainly.
2. GreenSky: configured 0% / 24-month headline, merchant/plan definition list, ordered steps, provider-approved details, fixed disclosure, and official external application/disclosure links.

Both external links open separately with `noopener noreferrer` and `no-referrer`. No proposal token, customer data, merchant fee, or tracking parameter leaves Tribunal.

The generic monthly estimator is hidden whenever the specific GreenSky program appears. Repeated project totals are removed from the hero, line items, category summary, and grand-total panel. The top visual CTA becomes `Review payment options` and links to a real payment-section heading.

GreenSky-enabled acceptance stays on the proposal and reveals explicit `Pay Deposit`; every legacy deposit-bearing approval still starts Stripe automatically. Expired/declined proposals expose no payment/application action, and paid deposits suppress GreenSky application.

### Accessibility and resilience

- Native links/buttons/switch, semantic section heading, ordered steps, and definition-list program identifiers.
- New-tab purpose is included in accessible application/disclosure link names.
- Two equal desktop cards become one ordered mobile column below 660 px; zero-minimum-width cells and wrapping protect 320 px.
- Visible `focus-visible` outlines, no new animation, and no new `transition: all`.
- Program facts and disclosures remain printable while interactive controls are hidden.
- Missing imagery does not remove payment content; malformed/alternate destinations fail closed.

Automated evidence does not certify WCAG or legal compliance. Manual assistive-technology and qualified legal/provider review remain separate.

## Compliance controls and launch gates

The dated scoped register is in `COMPLIANCE.md` and is explicitly **NOT LEGAL ADVICE**.

GreenSky Merchant Program Agreement v7.1, last updated 30 June 2026 and retrieved 4 September 2026, prohibits passing program/processing fees through a surcharge or increased borrower price (including sections 2(b)(v), 5(b), and 11(a)(x)). It also restricts merchant-created marketing, loan claims, and application handling. Re-check the current agreement and Operating Instructions before enablement.

Provider/counsel must approve:

- exact 0% / 24-month promotional wording and current plan eligibility;
- GreenSky marks, lender/Equal Housing presentation, employee training, and Operating Instructions;
- the underlying consumer contract, cancellation/refund/cooling-off terms, capacity, tax, and every served jurisdiction.

## Files

Backend/API:

- `backend/app/schemas/pricing.py`
- `backend/app/schemas/proposal_wizard.py`
- `backend/app/services/quotes/proposal_builder.py`
- `backend/tests/api/test_pricing_settings_financing_api.py`
- `backend/tests/services/quotes/test_proposal_builder.py`
- `backend/tests/services/quotes/test_financing_regression.py`
- `backend/openapi.json`

Frontend/governance:

- `frontend/src/types/sales-wizard.ts`
- `frontend/src/lib/api/_generated.ts`
- `frontend/src/components/settings/permanent-pricing-settings-card.tsx`
- `frontend/src/components/settings/permanent-pricing-settings-card.test.tsx`
- `frontend/src/components/proposal/document.ts`
- `frontend/src/components/proposal/permanent-payment-options.tsx`
- `frontend/src/components/proposal/client-proposal-view.tsx`
- `frontend/src/components/proposal/client-proposal-view.test.tsx`
- `frontend/src/components/proposal/proposal-theme.css`
- `frontend/src/app/p/quotes/[token]/page.tsx`
- `frontend/src/app/p/quotes/[token]/page.test.tsx`
- `frontend/DESIGN.md`
- `COMPLIANCE.md`
- `.ezcoder/plans/permanent-lighting-proposal-financing.md`

No dependency or database migration was added.

## Verification criteria

- [x] Backend settings round-trip, disabled defaults, trim/bounds, incomplete rejection, and 0% / 24-month fixture.
- [x] Snapshot public-safety, fixed destination, Permanent isolation, old-snapshot behavior, and one price.
- [x] Landscape, Christmas, bistro, and mixed-service financing regressions.
- [x] Staff setup complete/incomplete states, settled term display, safeguards, and no fabricated identifiers/copy.
- [x] Public one-price, deposit, pre-acceptance GreenSky, disclosures, fixed/no-referrer URL, closed/paid suppression, and estimator removal.
- [x] GreenSky stays on-page after acceptance; legacy approvals still start Stripe.
- [x] Backend full CI/codegen and production deployment/smoke.
- [x] Frontend codegen, targeted checks, full CI, and production build.
- [x] Desktop, 390 px, and 320 px runtime captures; overflow, keyboard/focus, reduced-motion, print, and Axe evidence.
- [x] Current GreenSky application returned HTTP 200 and requested merchant/plan values without an application submission.
- [ ] Frontend PR checks, protected merge, Vercel aliases, and frontend production smoke.
- [ ] Authorized production user enters real approved program details, regenerates, and inspects one Permanent proposal.

## Ordered implementation progress

- [x] 1. Create a clean backend release worktree from `origin/main`.
- [x] 2. Add validated disabled-safe GreenSky settings.
- [x] 3. Add public-safe snapshot and Permanent one-price normalization.
- [x] 4. Add backend settings, builder, isolation, and pricing tests.
- [x] 5. Regenerate OpenAPI/generated client and verify deterministic codegen.
- [x] 6. Run targeted and full backend CI.
- [x] 7. Commit, pass protected PR checks, merge, deploy Railway, and smoke production.
- [x] 8. Create a clean frontend worktree from deployed `origin/main`.
- [x] 9. Add staff GreenSky setup and fee-pass-through warning.
- [x] 10. Build the responsive two-path Permanent payment section.
- [x] 11. Separate GreenSky acceptance from explicit Stripe deposit checkout.
- [x] 12. Add settings, customer, external-link, state, and page-flow tests.
- [x] 13. Update design, compliance, and implementation records.
- [x] 14. Run codegen, frontend/full CI, and runtime visual/accessibility proof.
- [ ] 15. Commit, open/merge the frontend PR, and verify both Vercel aliases.
- [ ] 16. Enable only after real program values and provider-approved wording are available; regenerate and inspect a Permanent proposal.
