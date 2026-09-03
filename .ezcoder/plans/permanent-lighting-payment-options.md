# Permanent Lighting Payment Options

## Outcome

Permanent Lighting quotes will offer two ways to pay while keeping one contracted customer price:

- **GreenSky financing:** the normal selling price, with an automatic payment estimate.
- **Cash/check:** the same normal selling price.
- GreenSky's merchant fee remains an internal company expense and never increases borrower pricing.
- Landscape, Christmas, Bistro, service, mixed-service, and every other quote receive no financing presentation or financing-derived pricing.
- The customer or approving operator must select the payment method before a Permanent Lighting quote is accepted.
- Carter's/sales commission defaults to 7% of the final contracted quote total for either method.
- Labor is intentionally excluded per the latest instruction; the internal result will be labelled **Contribution Before Labor**, not misleadingly presented as net profit.

This replaces the original financed-price gross-up after the user selected the one-price path. At a $5,200 contract price, both options remain $5,200, the 24-month 0% estimate is $216.67 (shown as approximately $217/month), commission is $364, and a financed job records a $793 GreenSky merchant cost.

## Pricing Rules

1. Treat every salesperson-entered/configured amount as the actual selling price. Stop using the existing global financing and commission buffers to gross up Landscape, Christmas, Bistro, Permanent, add-on, price-book, and upsell prices.
2. Offer payment options only when the snapshotted proposal service is exactly `permanent`; `mixed` and every other service remain single-price with no financing copy.
3. Use one server-owned Permanent Lighting financing configuration nested under permanent pricing:
   - provider fixed to `GreenSky`
   - plan number default `6124`
   - APR default `0`
   - term default `24` months
   - merchant fee default `0.1525`
   - sales commission default `0.07`
4. Calculate the estimated payment on the server. At 0% APR use `price / term`; if an admin changes APR above zero, use the existing amortized-payment formula rather than continuing to show a false zero-interest division.
5. Round stored/displayed money to cents with `Decimal`; the customer presentation rounds only the “approximately $X/month” headline to the nearest dollar.
6. Snapshot the Permanent Lighting price, GreenSky terms, merchant fee, commission rate, and material COGS when the quote is built. Later settings edits must not silently rewrite a sent or approved quote.

## Data Model and Migration

Update `backend/app/models/quote.py` with two nullable, additive fields:

- `payment_option`: `cash_check`, `financing`, or `NULL` while undecided/non-applicable.
- `permanent_pricing_snapshot`: private JSONB containing cash/check price, financing price, plan number, APR, term, merchant fee rate, commission rate, and material COGS.

Add `backend/alembic/versions/20260903_permanent_quote_payment_options.py`, based on the current `20260902_referral_partner_intake` head. It will add both nullable columns and a check constraint limiting `payment_option`; no existing quote is backfilled or repriced. Downgrade drops only the new metadata.

Existing Permanent Lighting quotes without a snapshot remain readable and approvable through their existing flow; the new payment selector and profitability view activate only for newly snapshotted quotes.

## Backend Contracts and Logic

### Pricing configuration

Update `backend/app/schemas/pricing.py`:

- Add a validated `PermanentFinancingConfig` under `PermanentConfig` with the five admin-editable values.
- Add `plan_number` to the client-safe financing presentation schema.
- Retain legacy top-level financing/commission settings only for stored-settings compatibility, but stop consulting them for prices or payment presentation.

Update `backend/app/services/quotes/proposal_pricing.py`:

- Make legacy gross-up/cash adapters return the direct selling price, so previously stored nonzero buffers cannot affect any service.
- Add Permanent-only payment-estimate and profitability helpers.
- Calculate cash and financing scenario commission from the same final contract price.
- Calculate merchant fee as zero for cash/check and `contract price × merchant fee rate` for financing.
- Calculate contribution before labor as contract price minus merchant fee, package material COGS, and sales commission.

Update `backend/app/services/quotes/proposal_builder.py`:

- Build `ProposalFinancing` only when `service == "permanent"`.
- Snapshot GreenSky plan/APR/term/disclosure; never include merchant fee or commission in the customer document.
- Keep `cash_total` and `financed_total` equal under the approved one-price design.
- Ensure non-Permanent category sections, add-ons, and price-book items remain direct selling prices without monthly estimates.

### Quote lifecycle

Update `backend/app/services/quotes/quote_service.py`:

- Detect eligibility from the exact snapshotted service, never titles or free-form line-item categories.
- Build/update `permanent_pricing_snapshot` for both wizard-created Permanent quotes and Permanent lighting-project quote creation.
- Keep snapshot prices synchronized when a mutable Permanent quote is repriced, discounted, or has services changed.
- Require a server-validated payment option when a newly snapshotted Permanent quote is approved publicly or internally.
- Persist the selected method atomically with approval; do not accept customer-supplied prices, rates, fees, terms, or commission.
- Make approval retries idempotent only when they repeat the stored option; reject attempts to change an approved contract's payment method.
- Return generic financing estimates only for eligible Permanent quotes; all other services return `null`.
- Add a profitability response that computes both scenarios and identifies the selected one.

Update `backend/app/schemas/quote.py` and `backend/app/schemas/proposal.py` with:

- `QuotePaymentOption`.
- Optional payment choice on internal/public approval requests.
- Selected payment choice on quote/public responses.
- Admin-only Permanent profitability response and scenario models.

Update `backend/app/schemas/proposal_wizard.py` so financing is optional, carries plan number, and remains customer-safe. Strengthen `client_safe_document()` to strip existing tier commission fields so no internal commission or cost value leaks through the public token API.

Update `backend/app/api/v1/quotes.py`:

- Accept the option on both approval routes.
- Add `GET /workspaces/{workspace_id}/quotes/{quote_id}/permanent-profitability` guarded by `billing:read` plus existing workspace/quote scope.
- Return no profitability data for non-Permanent or legacy unsnapshotted quotes.

## Frontend

### Admin settings

Rework `frontend/src/components/settings/financing-settings-card.tsx` into **Permanent Lighting — GreenSky** settings:

- Plan number.
- Merchant fee percentage.
- Financing term in months.
- APR percentage.
- Sales commission percentage.
- Clear copy that the merchant fee is a company cost and never changes the customer's price.

The existing billing/admin capability gate remains the enforcement layer; salespeople receive no editor. Update `frontend/src/components/settings/financing-settings-card.test.tsx` for nested values, validation, save behavior, and the Permanent-only explanation.

### Customer proposal

Update `frontend/src/components/proposal/document.ts`, `frontend/src/components/proposal/client-proposal-view.tsx`, `frontend/src/components/proposal/financing-estimate.tsx`, and `frontend/src/components/proposal/financing-estimate.css`:

- Render a labelled `PAYMENT OPTIONS` radiogroup only for exact Permanent Lighting snapshots.
- Show `X% APR FINANCING`, the contract price, approximately `$N/month for T months`, plan number, and `Subject to credit approval`.
- Show `CASH/CHECK` with the same contract price; do not call it a discount under the approved one-price path.
- Require a payment-method selection before acceptance and send only the enum plus proposal version/package choice.
- Preserve keyboard navigation, visible focus, programmatic labels, and selected-state text.
- Keep non-Permanent proposal output unchanged except that obsolete financing blocks disappear.
- Append fixed, non-removable GreenSky estimate/credit wording; admin fields cannot erase required disclosure.

Update `frontend/src/app/p/quotes/[token]/page.tsx` and `frontend/src/lib/api/public-proposals.ts` to carry the selected payment option through approval.

### Internal quote workflow

Update `frontend/src/lib/api/quotes.ts`, `frontend/src/types/quote.ts`, `frontend/src/lib/query-keys.ts`, and `frontend/src/components/quotes/quotes-list.tsx`:

- Prompt for cash/check versus financing when an operator approves a newly snapshotted Permanent quote.
- Add an admin-only `Profitability` action for eligible Permanent quotes.
- Fetch profitability only after opening the dialog; never place private fee/COGS data in normal quote-list or public responses.

Add `frontend/src/components/quotes/permanent-profitability-dialog.tsx` to display:

- Cash/Check Price and Financing Price (equal under one-price policy).
- Financing plan, APR, term, merchant fee percentage/dollars, and estimated monthly payment.
- Sales commission percentage/dollars and package Material COGS.
- Cash/check and financed **Contribution Before Labor** and margins, highlighting the contracted selection after approval.

Add focused component tests for payment selection, non-Permanent hiding, approval payloads, permission hiding, and the two profitability scenarios.

## Security, Data Integrity, and Compliance

- Settings remain writable only through existing `billing:write`; profitability requires `billing:read`.
- Public APIs expose GreenSky terms and the selected method, but never merchant fee, commission, COGS, or the private snapshot.
- The database constraint and service validation prevent arbitrary payment-method values.
- Sent/approved terms remain snapshotted; an admin settings change affects only future/repriced mutable quotes.
- Update `COMPLIANCE.md` without overwriting its existing work:
  - Record the one-price design as mitigation for GreenSky Merchant Program Agreement section 2(b)(v), which prohibits adding transaction fees to borrower prices.
  - Keep an open lawyer/provider-review item for written GreenSky approval of the custom quote copy/layout and confirmation that Plan 6124 terms remain current.
  - Label this engineering guidance, not legal advice; do not claim the feature is compliant.

## Verification Criteria

- A Permanent quote priced at $5,200 shows both methods at $5,200 and approximately $217/month for 24 months.
- Financing profitability records a $793 merchant fee and $364 commission at default rates; cash records no merchant fee and the same commission.
- No non-Permanent quote is grossed up, receives financing metadata, shows payment options, or accepts a financing selection.
- Salespeople cannot write plan/rate settings or read private profitability data.
- A public customer cannot set a price, fee, APR, term, or commission in the approval request.
- Approval stores exactly one method atomically and cannot be replayed to switch an approved contract.
- Existing quotes without the new snapshot continue to work.
- Migration upgrade/downgrade/upgrade is reversible and preserves existing quote rows.
- OpenAPI and the generated frontend client remain synchronized.

## Steps

1. Add the Permanent-only GreenSky configuration and direct-selling-price math in `backend/app/schemas/pricing.py` and `backend/app/services/quotes/proposal_pricing.py`.
2. Scope financing snapshots to exact Permanent Lighting proposals in `backend/app/services/quotes/proposal_builder.py` and remove financing output from every other service.
3. Add `payment_option` and private Permanent pricing snapshot fields to `backend/app/models/quote.py` with `backend/alembic/versions/20260903_permanent_quote_payment_options.py`.
4. Add payment-selection and profitability contracts in `backend/app/schemas/quote.py`, `backend/app/schemas/proposal.py`, and `backend/app/schemas/proposal_wizard.py`.
5. Implement snapshot creation, repricing synchronization, atomic payment selection, and profitability scenarios in `backend/app/services/quotes/quote_service.py`.
6. Wire guarded internal profitability and approval payloads through `backend/app/api/v1/quotes.py`, preserving public/private field separation.
7. Replace the global financing settings editor with Permanent Lighting GreenSky fields and tests in `frontend/src/components/settings/financing-settings-card.tsx`.
8. Add accessible Permanent-only customer payment selection and disclosures across the proposal document, view, API client, and styles.
9. Add internal payment-selection approval and admin profitability UI across quote types, API client, query keys, quote list, and the new dialog.
10. Rewrite backend pricing/settings tests and add lifecycle, authorization, redaction, snapshot, and profitability coverage.
11. Update frontend proposal, settings, quote-list, and profitability tests for Permanent and non-Permanent behavior.
12. Update `COMPLIANCE.md` with the fee-pass-through mitigation and unresolved GreenSky/counsel approval item.
13. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` together.
14. Run targeted backend/frontend suites, formatting, type checks, and reversible migration checks; fix every regression without weakening assertions.
15. Exercise the public proposal and admin profitability endpoints with `.ezcoder/eyes/http.sh`, verifying Permanent 2xx behavior plus non-Permanent/unauthorized denial and redacted payloads.
