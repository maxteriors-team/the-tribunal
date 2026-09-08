# Permanent Lighting Client Quote

## Outcome

Permanent-lighting operators use one real client-quote flow. The customer receives a branded `/p/quotes/{token}` proposal containing the saved house mockup, both entered range endpoints, payment choices derived from the quote, and explicit accept or decline actions. The old `/p/compare/{token}` artifact remains only as a clearly labeled legacy estimate preview.

## Root cause

- The supplied screenshot is `/p/compare/{token}`. `LightDesigner.saveAndShare()` creates this comparison record instead of a quote.
- `frontend/src/app/p/compare/[token]/page.tsx` renders `ComparisonCard`, which has no mockup, range-high field, approval, decline, deposit checkout, or payment-selection contract. It also ignores the `logo_url`, `brand_color`, and `accent_color` already returned by the API.
- The real path already exists: `sendPermanentProposal()` creates a quote through `estimatorApi.createQuote()`, then `quotesApi.deliver()` sends `/p/quotes/{token}`. That public quote already supports a mockup, workspace branding, approval, decline, financing/cash selection, and Stripe deposit checkout.
- A linked customer currently locks name, email, and phone together. When the customer profile lacks email, the operator cannot enter one even though the email action requires it. Disabled buttons communicate their reasons mostly through hover titles.
- `price_range_high` reaches the public quote response, but permanent estimate documents fall through to `PlainQuoteView`. That component never reads `data.price_range`, so the upper amount disappears.

A minimal red check is `grep -n price_range frontend/src/components/proposal/plain-quote-view.tsx`; it currently exits 1.

## Design read

- **Surface:** high-consideration residential-service proposal, led by commerce and supported by editorial proof.
- **Audience:** a homeowner opening a link from email or text, commonly on a phone and without product expertise.
- **Single job:** recognize their home and contractor, understand the quoted range, choose payment, then answer yes or no confidently.
- **Risk:** wrong amount, accidental acceptance, unclear financing, a missing contractor identity, or a mockup belonging to another customer.
- **Content:** one customer/project, one saved visual, a lower and upper estimate, scope lines, cash/check or configured financing, deposit terms, and decision controls.
- **Platform:** Next.js public route, keyboard/touch/pointer input, narrow through wide viewports, no login.
- **Constraints:** preserve server-owned prices, existing Stripe checkout, workspace-scoped branding, public-token authorization, and existing proposal components. Add no dependency.

## Evidence and direction

- Reuse `PlainQuoteView` because it already owns the exact public approval/payment behavior and handles minimalist permanent proposal documents.
- Use the local `nike` archetype observation for image-led product proof: the customer’s own house mockup is the dominant evidence.
- Use the local `airbnb` archetype observation for familiar, low-friction selection and explicit pricing.
- Use `binance` only as a contrast: this should not become a dense financial dashboard.
- The design thesis is **one proposal, not two**: one shared content rail, full-color workspace logo, customer mockup first, one clearly labeled range with two endpoints, payment choices, then explicit yes/no actions.
- The mockup is the memorable device. No decorative card grid, fake metrics, gradients, hover lift, emoji icons, or invented claims.

## Planned behavior

### Operator flow

1. Keep the linked customer identity fixed, but allow email and phone as editable delivery destinations for this send. Explain that permanent profile changes belong on the customer record.
2. Show visible, live blockers near the actions: missing selected-photo design, missing destination, invalid deposit, or a higher amount not exceeding the lower quote total.
3. Replace ambiguous labels with `Save draft quote`, `Save & email client quote`, and `Save & text client quote`.
4. For the permanent side, remove `Save & share link only` and its comparison URL result. Seasonal/comparison behavior remains unchanged.
5. The email/text actions continue to create the server-priced quote first, then deliver its actionable `/p/quotes/{token}` link. A failed create or delivery remains visible and never reports success.

### Customer flow

1. Render workspace logo/business identity and both configured colors in the header; retain the business-name fallback when no logo is configured.
2. Put the customer’s saved composite mockup before pricing and decision content, with existing alt text and caption behavior.
3. When `data.price_range` exists, show the lower and upper amounts with equal visual weight inside one `Estimated project range`; do not style them as selectable packages.
4. State that approval locks the lower amount and any increase requires separate confirmation. Payment and deposit math continue using the server-owned lower quote total.
5. Render configured cash/check and financing choices before acceptance. Preserve financing disclosure, provider/plan terms, and server payload values.
6. Label decisions `Yes, approve this proposal` and `No, decline` while preserving confirmation, pending, success, expiry, and already-decided states.
7. Keep scope and terms readable but visually subordinate to mockup, range, payment, and decision.

### Legacy comparison links

Existing comparison records do not contain a saved mockup, range-high amount, quote ID, payment terms, or decision state, so they cannot safely become actionable proposals. Keep old links working, apply the returned logo/colors, and relabel the surface as an `Estimate preview`. New permanent jobs will no longer create these links.

## Files and changes

- `frontend/src/components/estimator/light-designer.tsx`
  - Adjust `customerProfileLocked` usage so identity remains fixed while delivery destinations are editable.
  - Add visible permanent-send blocker text derived from `permanentProjectPreviewReady`, `permanentDepositValid`, `permanentPriceRangeValid`, and the selected channel value.
  - Update `sendPermanentProposal()` action labels/status copy.
  - Gate `saveAndShare()` and its result UI away from `proposalSide === "permanent"`; keep comparison sharing for its existing seasonal/mixed use.
- `frontend/src/components/proposal/plain-quote-view.tsx`
  - Render `PublicProposal.price_range` and the lower-amount acceptance explanation.
  - Preserve `FinancingEstimate`, deposit checkout, mockup, line items, and server-owned approval/decline handlers.
  - Clarify yes/no labels and semantic headings without changing endpoint behavior.
- `frontend/src/components/proposal/proposal-brand.ts`
  - Extend the existing validated color-variable helper to accept primary and accent colors.
  - Use an accessible color for text/controls and reserve darker configured colors for non-text decorative rules; retain safe defaults for missing/malformed colors.
- `frontend/src/components/proposal/client-proposal-view.tsx`
  - Pass both branding colors through the shared helper so rich and plain quote variants do not drift.
- `frontend/src/components/proposal/proposal-theme.css`
  - Add range anatomy, a restrained two-color brand rule, responsive wrapping, forced-colors support, and named transitions only.
  - Keep one content rail and existing typography/spacing tokens.
- `frontend/src/app/p/compare/[token]/page.tsx`
  - Render the returned logo and safe brand variables, and label this backward-compatible route as a non-actionable estimate preview.
- `frontend/src/components/estimator/light-designer.test.tsx`
  - Cover a linked permanent customer with a missing email, visible blocker recovery, draft creation, direct email/text delivery, and absence of permanent comparison sharing.
- `frontend/src/components/proposal/plain-quote-view.test.tsx`
  - Cover mockup, logo, both range endpoints, lower-amount disclosure, payment selection, and explicit approve/decline behavior.
- `frontend/src/components/proposal/proposal-brand.test.ts`
  - Cover primary/accent selection, malformed fallbacks, and contrast guarantees.
- `frontend/src/app/p/compare/[token]/page.test.tsx`
  - Cover legacy branding and `Estimate preview` language without implying approval/payment.
- `frontend/e2e/permanent-lighting-client-proposal.spec.ts`
  - Route-mock a realistic public permanent quote and verify desktop/mobile layout, no overflow, visible mockup/range/logo, keyboard-operable payment choice, approval payload, decline flow, and checkout redirect.
- `frontend/DESIGN.md`
  - Record this design read, hierarchy, semantic colors, responsive states, and the rule that permanent customer delivery uses real quotes rather than comparison links.

## Data, security, and payment boundaries

- Do not hardcode Maxteriors branding into shared multi-tenant UI. Render `branding.logo_url`, `brand_color`, and `accent_color` from the workspace proposal template.
- Verify the Maxteriors template resolves its existing public logo (`/static/brand/maxteriors-logo.png`) and configured colors; report missing production configuration rather than leaking this brand to other workspaces.
- Never expose or log public quote/comparison tokens. Tests use fake tokens and synthetic customer data.
- Do not move pricing, financing, deposit, approval, or checkout calculations into the browser. Existing backend values and endpoints remain authoritative.
- Do not persist a one-send delivery override onto the customer profile silently.
- No schema, migration, OpenAPI, or generated-client change is expected.

## Verification criteria

- A saved permanent design with valid lower/high inputs can be saved and emailed or texted without creating a comparison record.
- A missing delivery destination can be entered; every blocked action has visible explanatory text.
- The received URL is `/p/quotes/{token}`, never `/p/compare/{token}`.
- The public quote visibly contains the configured logo/colors, customer mockup, both range endpoints, payment choices, and yes/no controls.
- Selecting cash/check or financing sends the existing exact API value; deposit checkout still uses the backend-provided amount.
- Legacy comparison URLs continue loading but identify themselves as estimate previews.
- Desktop and 390px mobile views have no horizontal overflow; zoom/reflow, keyboard focus, reduced motion, forced colors, loading, error, expired, and decided states remain operable.
- Targeted unit and Playwright tests pass, followed by `make ci.frontend`.

## Steps

1. Add failing estimator and public-proposal regression tests for missing destinations, wrong comparison routing, absent range-high display, and missing brand treatment.
2. Update `LightDesigner` so permanent jobs expose clear blockers and only create/save/deliver real client quotes.
3. Make linked-customer email and phone usable as one-send delivery destinations while keeping customer identity fixed.
4. Add the two-endpoint permanent range and lower-amount disclosure to `PlainQuoteView`.
5. Wire primary and accent workspace colors through both proposal variants and add responsive accessible theme styles.
6. Brand and relabel the legacy comparison route without making old estimate records falsely actionable.
7. Add the route-mocked desktop/mobile permanent-proposal Playwright flow covering payment, approval, decline, and checkout.
8. Document the permanent client-quote design and one-proposal rule in `frontend/DESIGN.md`.
9. Run targeted frontend unit tests, type-checking, linting, and the new Playwright specification; fix any failures.
10. Capture desktop and mobile renders, score them against the UI quality rubric, remove one unnecessary treatment, and revise any failed production check.
11. Run `make ci.frontend` and verify the Maxteriors proposal-template logo/color configuration separately from shared code.
