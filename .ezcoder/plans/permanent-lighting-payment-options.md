# Permanent-lighting Stripe payment choices

## Objective

The public permanent-lighting proposal must present:

- **Financing estimate:** `$417/mo` and `for 24 months` only. It is informational, not selectable, and cannot approve a proposal.
- **50% down:** exact server-calculated amount due now, with the completion balance shown.
- **Pay in full:** exact server-owned proposal total due now.

Only 50%-down and pay-in-full are approval choices. Approving either must persist the selected choice and exact amount, then redirect to hosted Stripe Checkout.

## Design decisions

### Financing stays display-only

- Remove the financing radio control and selected state.
- Do not include financing in the approval enum or approval payload.
- Reject `payment_option="financing"` on this permanent public-approval path, including stale clients.
- Keep the generic credit-approval disclosure below the financing estimate.

### Persist payment truth separately from deposit terms

Add explicit nullable permanent-proposal payment fields to `quotes`:

- `proposal_payment_choice`: `fifty_percent_down` or `pay_in_full`.
- `proposal_payment_amount`: the immutable accepted amount in major currency units.
- `proposal_payment_checkout_session_id`: the active Stripe Checkout Session.
- `proposal_payment_intent_id`: Stripe’s successful PaymentIntent identifier.
- `proposal_payment_paid_at`: provider-confirmed completion time.

Add database constraints for allowed choices, positive amounts, and choice/amount pairing. Do not mutate or reinterpret `deposit_percentage`, `deposit_amount_fixed`, or existing deposit payment fields. Those remain the original quote terms and legacy deposit record.

The migration is additive and needs no backfill because this permanent-payment selection has not shipped. Its downgrade removes only the new fields and constraints.

### Server owns every amount

- The browser submits only `fifty_percent_down` or `pay_in_full`; it never submits money.
- After package selection and proposal-version validation, lock the quote and calculate from the accepted server total.
- `fifty_percent_down` persists a currency-rounded 50% of the accepted total.
- `pay_in_full` persists the accepted total.
- Persist choice and amount in the same approval transaction.
- Idempotent retries may repeat the same choice; a different choice is rejected after approval.
- Existing `payment_option` may remain `cash_check` for internal pricing economics, but it is not the customer’s payment schedule or card-payment record.

### Dedicated permanent-payment checkout

- Add `/p/quotes/{token}/payment-checkout` and `/payment-status`; retain legacy deposit endpoints unchanged.
- Checkout requires an approved permanent proposal with a persisted unpaid choice and amount.
- Stripe receives the persisted amount, currency, quote/workspace IDs, and a dedicated metadata kind.
- Product copy distinguishes `50% payment for …` from `Payment in full for …`.
- Store the returned session/intent identifiers in the new fields.
- The Stripe webhook routes the dedicated metadata kind to the new reconciliation path.
- Before recording payment, verify the signed event’s stored session ID, quote/workspace metadata, paid status, amount, and currency.
- Reconciliation on Stripe return provides the same checks as a webhook backstop and remains idempotent.

### Public response and UI

- Expose server-calculated 50% and full amounts before approval.
- Expose persisted choice, amount, paid state, and payment-required state after approval.
- Render financing as a non-interactive estimate card beside two accessible payment radios.
- Label the radios `50% down` and `Pay in full`, each with its exact amount.
- Update the approval button’s accessible text to name the selected amount.
- Approval success immediately calls the dedicated checkout endpoint and redirects to Stripe.
- A cancelled or delayed checkout leaves a correct retry panel using the persisted amount.
- A completed checkout shows `Payment received`; 50% down also shows the remaining completion balance.

### Receipts and existing behavior

- Acceptance receipts state the selected payment schedule and exact amount due without calling pay-in-full a deposit.
- Operator payment notifications identify down payment versus paid in full.
- Non-permanent proposals and existing deposit checkout/manual-recording behavior remain unchanged.
- Comparison links remain read-only and expose no approval or payment controls.

### Generated contracts and compliance note

- Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together.
- Append a focused `COMPLIANCE.md` entry recording hosted checkout, server-owned amounts, and immutable payment evidence.
- Keep cancellation, refund, tax, and contract wording as residual legal-review work. This is engineering guidance, not legal advice.

## Steps

1. Add the new quote payment fields and reversible Alembic migration with constraints.
2. Extend public proposal schemas with two approvable choices and server-calculated amounts.
3. Persist the selected choice and immutable amount inside locked, version-checked approval.
4. Reject financing and contradictory or changed payment selections on public approval.
5. Add dedicated checkout, reconciliation, and webhook handling using the new payment fields.
6. Validate session identity, paid status, amount, currency, and metadata before marking paid.
7. Update acceptance receipts and operator notifications with accurate payment wording.
8. Render display-only financing plus selectable 50%-down and pay-in-full cards.
9. Redirect either approved payment choice to Stripe and restore cancelled-checkout retry behavior.
10. Regenerate OpenAPI and generated frontend contracts together.
11. Add focused backend, component, and browser coverage for both Stripe amounts.
12. Update the focused compliance register entry and residual legal-review note.
13. Run migration checks, targeted suites, lint/types, production build, browser flows, axe scans, and screenshots.

## Verification

- **Migration:** upgrade, model/schema check, downgrade, and re-upgrade against a local test database.
- **Approval:** 50% persists half; full persists total; financing/unknown/missing choices fail closed; same-choice retry is idempotent; changed choice is rejected.
- **Stripe:** each choice creates a distinct server-priced Checkout Session; mismatched session, status, amount, currency, or metadata cannot mark payment paid.
- **Legacy:** existing deposit checkout, manual deposit recording, and non-permanent proposal tests remain green.
- **Frontend:** component tests require display-only financing, two radios, exact amounts, payloads, no provider copy, and retry/paid states.
- **Browser:** independently approve 50%-down and pay-in-full, observe both Stripe redirects and distinct amounts, then run desktop/mobile overflow and axe checks.
- **Independent gates:** backend/frontend lint and type checks plus production frontend build must pass; changed tests are supplemental rather than the sole proof.
