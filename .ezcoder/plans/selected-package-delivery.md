# Selected-package customer delivery

## Objective

Make landscape-lighting proposal links show and sell only the package selected by the staff user, while reusing the existing quote delivery, terms, acceptance, and Stripe deposit flows.

The existing system already provides:

- package selection and server pricing in `frontend/src/components/estimator/light-designer.tsx`;
- draft quote creation plus explicit email/SMS actions through `salesWizardApi.deliver`;
- tokenized public proposal links from `backend/app/services/quotes/quote_service.py`;
- terms at the bottom of `frontend/src/components/proposal/client-proposal-view.tsx`;
- server-derived deposit amounts and hosted Stripe Checkout after acceptance.

The missing behavior is locking a newly created landscape proposal to the staff-selected package. Today the public response exposes every priced tier and accepts another tier key from the customer.

## Design

### Backward-compatible quote intent

Add `customer_can_select_package: bool = True` to `ProposalWizardPayload` in `backend/app/schemas/proposal_wizard.py`.

- Existing saved/sent proposals omit the field and retain today’s customer-choice behavior.
- New landscape proposals set it to `false` in `frontend/src/lib/estimator/landscape-proposal.ts`.
- No migration is needed because wizard input is already stored as versioned JSON in `quotes.proposal_input`.
- Quote edits/revisions preserve the field through existing Pydantic validation and snapshot persistence.

### Public selected-package boundary

Update `backend/app/services/quotes/quote_service.py` at the public proposal chokepoint:

- detect the saved `customer_can_select_package` value, defaulting old payloads to `true`;
- return no public package-choice cards when selection is locked;
- filter the client-safe proposal document to its `selected_tier` only;
- filter tier-scoped additional charges to unscoped or selected-tier charges;
- reject a crafted approval request naming another tier;
- allow approval with the selected tier or no tier, preserving idempotency and proposal-version checks.

This must be enforced server-side, not only hidden in React, so a customer cannot switch packages by editing the request.

### Staff and customer presentation

Keep the deliberate staff sequence in `frontend/src/components/estimator/light-designer.tsx`:

1. select the fixture package;
2. create the draft quote;
3. set the deposit/payment terms;
4. email or text the public link.

Rename the actions to `Email selected package` and `Text selected package`, and add concise copy that the customer link is locked to the highlighted package. Reuse the existing authenticated delivery endpoint, recipient resolution, SMS opt-out gate, Resend/Telnyx integrations, idempotency, tracked link, and error handling.

The public page requires no new payment or terms implementation. With a one-tier client-safe document and no package choices, `ClientProposalView` already renders the selected-package presentation, terms footer, approval action, deposit due, and Stripe Checkout handoff.

## Files

- `backend/app/schemas/proposal_wizard.py` — backward-compatible package-choice intent.
- `backend/app/services/quotes/quote_service.py` — public filtering and alternate-tier rejection.
- `backend/tests/services/quotes/test_wizard_flow.py` — locked-package and legacy behavior regression coverage.
- `backend/openapi.json` — regenerated request contract.
- `frontend/src/lib/api/_generated.ts` — regenerated typed client contract.
- `frontend/src/lib/estimator/landscape-proposal.ts` — lock new landscape quotes.
- `frontend/src/lib/estimator/landscape-proposal.test.ts` — exact payload assertion.
- `frontend/src/components/estimator/light-designer.tsx` — selected-package delivery wording.
- `frontend/src/components/estimator/light-designer.test.tsx` — email/SMS selected-package actions.
- `frontend/src/components/proposal/client-proposal-view.test.tsx` — one-package terms and deposit regression.
- `frontend/DESIGN.md` — operator/customer behavior documentation.
- `COMPLIANCE.md` — focused engineering note and retained legal-review caveat.

Existing uncommitted Accent-Uplight override work in `workflow-tables.tsx`, its test, and `frontend/DESIGN.md` remains intact and is verified separately.

## Safety and compliance

- No provider key or payment credential reaches the browser.
- Package totals and deposit amounts remain server-derived.
- Card entry remains on hosted Stripe Checkout.
- Email/SMS remains an explicit operator action; SMS continues through the existing opt-out-aware transactional gate.
- Public responses continue using allowlisted proposal fields and high-entropy tokens.
- Existing quotes keep their original package-choice behavior.
- Actual cancellation, refund, tax, contract-capacity, and jurisdiction-specific terms still require legal review; this plan does not invent legal language.

## Risks

- Filtering tiers without filtering tier-scoped charges could expose the wrong add-on; test both together.
- A frontend-only lock would be bypassable; reject alternate tier keys in the service.
- Changing the default for old proposals would rewrite customer expectations; default the new field to `true`.
- Repricing or deposit logic must not be duplicated in the browser; reuse existing server calculations.
- Delivery must remain two-step after quote creation so the operator can review deposit terms before sending.

## Verification

- Backend integration: locked proposals expose one selected tier, no package choices, and reject alternate-tier approval without mutating quote totals/status.
- Backend compatibility: existing payloads still expose and accept all priced package choices.
- Frontend payload: landscape quote creation sends `customer_can_select_package: false` with the selected tier.
- Frontend customer view: selected package, terms footer, acceptance, and deposit CTA remain visible; no package chooser appears.
- Staff UI: both email and SMS selected-package actions call the existing delivery client.
- Contract generation: run `make ci.codegen` and inspect both generated artifacts.
- Targeted suites: proposal wizard flow, public proposal API/view, landscape proposal helper, light designer, and workflow tables.
- Full checks: `make ci.all`.
- Runtime boundary: exercise a representative local public proposal with `.ezcoder/eyes/http.sh`, confirming the selected-only response and rejecting an alternate tier; do not trigger paid Stripe, Telnyx, or Resend activity.

## Steps

1. Add the backward-compatible `customer_can_select_package` field to the proposal wizard contract.
2. Enforce selected-only public document filtering and alternate-tier rejection in `QuoteService`.
3. Add backend regressions proving locked-package behavior and unchanged legacy customer choice.
4. Send the selected-only intent from new landscape proposal payloads and update its unit tests.
5. Clarify the staff email/SMS actions and selected-package link behavior in the landscape quote builder.
6. Add frontend regressions for selected-package delivery, public terms, acceptance, and deposit presentation.
7. Regenerate OpenAPI and frontend client artifacts.
8. Update design and focused compliance documentation without inventing legal terms.
9. Re-run the retained Accent-Uplight override tests alongside the selected-package suites.
10. Run full CI and a local public-proposal HTTP boundary probe without sending messages or creating a paid checkout.
