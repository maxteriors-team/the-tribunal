# Unify quoting into one source of truth + reliable deposit capture

## Goal
1. **One quoting system.** Make the sales-wizard proposal engine the single source of truth for building quotes and retire the parallel plain "New quote" builder so operators have exactly one quoting flow feeding one `Quote` lifecycle.
2. **Deposits that always resolve to payment.** Make deposits first-class on every quote (percentage *or* fixed, with a workspace default), settable from the wizard, and guarantee every deposit path reliably marks the quote paid — webhook primary, with a Stripe reconcile-on-return backstop and an "Approve → pay deposit" hand-off.

## Current state (verified)
- **Pricing math is already centralized** in `backend/app/services/quotes/proposal_pricing.py` (+ `proposal_builder.py`, `pricing_config.py`). Both the wizard (`preview_from_wizard`/`save_from_wizard`) and the roofline estimator (`_compute_comparison`) price through it. There is **no duplicate pricing engine**.
- **Two creation UIs exist**, which is the real duplication:
  - Plain manual `frontend/src/components/quotes/quote-create-dialog.tsx` → `POST /quotes` (`create_quote`), rep types unit prices. Only used by `quotes-list.tsx`.
  - `frontend/src/components/sales-wizard/*` → `POST /quotes/wizard` (`save_from_wizard`), config-driven engine.
- **One Quote lifecycle** already: `draft → sent → approved/declined`, `deliver`, public `approve/decline`, `convert` (→ job/invoice, now schedulable), deposit fields on `Quote`.
- **Deposit today**: `Quote.deposit_percentage` only (no fixed amount); `deposit_amount(quote)` = `total × pct/100`. Set only via the **plain** dialog; the **wizard never sets a deposit**. Public page renders `DepositPanel` → `POST /p/quotes/{token}/deposit-checkout` → Stripe Checkout (`payment` mode) → billing webhook `checkout.session.completed` routes by `quote_id` metadata to `handle_deposit_checkout_session_completed` → `deposit_paid_at`. Real Stripe (`stripe.StripeClient`), real webhook in `backend/app/api/v1/billing.py`.
- **Reliability gaps**:
  - Wizard quotes cannot take a deposit at all (no field, `save_from_wizard` never sets it).
  - Only percentage deposits; no fixed amount; no workspace default.
  - `deposit_paid_at` flips **only via webhook**. On return from Stripe (`?deposit=paid`) the public page does **not** reconcile or poll, and if `stripe_webhook_secret` is unset the payment is never recorded → "paid but proposal still says unpaid."
  - "Approve" and "Pay deposit" are fully independent; accepting never routes into payment.
  - Wizard-saved quotes have `contact_id=None` (wizard collects client as free text), which **blocks convert→job** (job requires a contact). This must be fixed for the wizard to be the single system.

## Key paths
- Public proposal router prefix: `/api/v1/p/quotes` (`backend/app/api/v1/router.py:219`). Reconcile endpoint will be `POST /p/quotes/{token}/deposit-status`.
- Stripe webhook + routing: `backend/app/api/v1/billing.py:309` (`stripe_webhook`) → `_handle_checkout_completed` (routes `quote_id` → deposit handler).
- Deposit service: `backend/app/services/payments/quote_deposit_service.py`; shared checkout + `retrieve_session_status` in `backend/app/services/payments/call_payment_service.py`.
- Deposit column migration to mirror: `backend/alembic/versions/21019f8d527d_add_quote_deposit.py`.

## Decisions (defaults chosen; flag for reviewer)
- **D1 — Retire the plain create dialog as the operator path.** `/quotes` "New quote" launches the sales-wizard (`/sales-wizard?contact=<id>`). The plain `create_quote` **API stays** (generic line-item primitive, used by tests/quick-actions) but its **duplicate UI is removed**. This is the "replace the current quoting system" step. *If the reviewer wants generic non-lighting quotes to keep a manual UI, we instead fold a "Custom line items" category into the wizard — larger; not the default.*
- **D2 — Deposit modes:** support `percentage` and `fixed`. Store both nullably; resolver prefers fixed. Workspace default lives in pricing config (`DepositConfig`).
- **D3 — Accept = pay when a deposit is required.** Public CTA becomes "Approve & Pay Deposit" (approve records acceptance, then hand off to Stripe). Standalone "Pay Deposit" remains for return visits. Approval is still recorded even if the customer abandons Stripe (so we don't lose the acceptance).
- **D4 — Reliability = webhook primary + reconcile-on-return + short poll.** Never rely on a single mechanism.

## Risks & mitigations
- **Migration touches `quotes`** (prod has live data). Additive nullable column only; back up prod first per CLAUDE.md release process. Test up→down→up locally.
- **Stripe is external.** Unit/integration tests stub the Stripe client (mirror existing `call_payment_service` tests). Local eyes probe covers the public payload + reconcile endpoint state transitions, not a real charge.
- **Removing the plain dialog** could hide generic quotes — mitigated by keeping the API and by D1's fallback option.
- **Contact linking in the wizard** must not create duplicate contacts — resolve by email/phone within the workspace before creating.

## Verification strategy
- Backend: `make ci.backend`; targeted `pytest -m integration tests/services/quotes/…` and new deposit tests; `pytest tests/api/test_public_proposal_api.py`.
- Migrations: `make ci.migrations` (up→check→down→up).
- Codegen: `make codegen` then commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together; `make ci.codegen`.
- Frontend: `make ci.frontend` (lint/type/test/build).
- Runtime eyes: with `make dev` up, `.ezcoder/eyes/http.sh` to (a) save a wizard quote with a deposit and confirm the priced deposit in the response, (b) GET `/p/quotes/{token}` and confirm `deposit_mode/amount/required`, (c) exercise `POST /p/quotes/{token}/deposit-status` idempotency with a stubbed session, (d) confirm convert→job works on a wizard quote (contact linked).
- Full: `make ci.all`.

## Out of scope
- Real end-to-end Stripe charge in CI (needs live keys). Rooflined estimator's `RooflineComparison` stays a pre-quote tool, not a quote.

## Steps
1. **Deposit column migration.** Add `make migrate.new m="add quote fixed deposit + config"`; add nullable `quotes.deposit_amount_fixed` (`Numeric(12,2)`) mirroring `21019f8d527d_add_quote_deposit.py`; add the column to `backend/app/models/quote.py` with a doc comment. Run `make migrate`; verify up→down→up.
2. **Deposit resolver + config schema.** In `backend/app/services/payments/quote_deposit_service.py` update `deposit_amount(quote)` to prefer `deposit_amount_fixed` (clamped to `≤ total`), else `deposit_percentage × total`. Add a `DepositConfig` model (`enabled: bool`, `mode: Literal["percentage","fixed"]`, `value: float`) to `backend/app/schemas/pricing.py` and wire it into `PricingSettings` (default disabled).
3. **Quote schemas.** In `backend/app/schemas/quote.py` add `deposit_amount_fixed` to `QuoteCreate`/`QuoteUpdate` (validated `≥ 0`) and to `QuoteResponse` (+ expose derived `deposit_amount` and `deposit_required`). Keep `deposit_percentage`. Ensure exactly one of pct/fixed is used (model validator).
4. **Persist deposit everywhere in the service.** In `backend/app/services/quotes/quote_service.py`: `create_quote` and `update_quote` handle `deposit_amount_fixed`; both `create_quote` and `save_from_wizard` fall back to the workspace `DepositConfig` default when the payload sets no deposit. Have the public-proposal serializer include `deposit_mode`/`deposit_amount`/`deposit_required`.
5. **Wizard deposit input.** Add an optional `deposit` object (`mode`, `value`) to `ProposalWizardPayload` (`backend/app/schemas/proposal_wizard.py`); have `build_proposal_document`/`save_from_wizard` carry it onto the saved `Quote` and surface the resolved deposit amount in the returned `ProposalDocument` (new optional field) so the preview shows it.
6. **Link a contact from the wizard.** In `save_from_wizard`, when `payload.contact_id` is null but client email/phone is present, resolve an existing workspace contact (by email then hashed phone) or create one, and set `quote.contact_id`, so wizard quotes can convert→scheduled job.
7. **Reconcile-on-return endpoint.** Add `POST /p/quotes/{token}/deposit-status` to `backend/app/api/v1/quotes.py` (`public_router`) → new `reconcile_deposit(token)` in `quote_deposit_service.py` that loads the quote, calls `retrieve_session_status(deposit_checkout_session_id)`, and if `payment_status == "paid"` calls `mark_deposit_paid` (idempotent); returns `{deposit_paid, deposit_amount, currency}`. No-op safely when no session/deposit.
8. **Accept → pay hand-off (backend).** Extend the public approve result (`PublicProposalActionResult`) with `deposit_required`/`deposit_amount` so the client can chain into checkout; ensure `approve_public` records approval before any payment step.
9. **Codegen.** Run `make codegen`; commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` together.
10. **Frontend quoting consolidation.** In `frontend/src/components/quotes/quotes-list.tsx`, replace the `QuoteCreateDialog` "New quote" action with navigation to the sales-wizard (`/sales-wizard`, passing `?contact=<id>` when launched from a contact); remove the `QuoteCreateDialog` import/usage. Delete `frontend/src/components/quotes/quote-create-dialog.tsx` (and any now-unused `quotesApi.create` UI wiring), keeping the API client method.
11. **Wizard deposit UI.** Add a deposit control (mode toggle % / $ + value, prefilled from workspace `DepositConfig`) to the Review step in `frontend/src/components/sales-wizard/calculator-screen.tsx` (+ `use-sales-wizard.ts` state and payload `deposit`), and show the resolved deposit amount in the client-link summary.
12. **Public page reliable capture.** In `frontend/src/app/p/quotes/[token]/page.tsx` + `frontend/src/components/proposal/deposit-panel.tsx`: on mount with `?deposit=paid` (or after returning), call `POST /p/quotes/{token}/deposit-status`, then refetch; poll up to ~5× with backoff until `deposit_paid` or timeout, showing a "confirming payment…" state.
13. **Accept → pay (frontend).** In `client-proposal-view.tsx`/`plain-quote-view.tsx`, when `deposit_required` and unpaid, make the primary CTA "Approve & Pay Deposit": call approve, then `depositCheckout` and redirect to Stripe. Keep standalone "Pay Deposit" and plain "Approve" (no deposit) paths.
14. **Add `deposit_amount_fixed`/`deposit`/config types** to `frontend/src/lib/api/quotes.ts`, `sales-wizard.ts`, and relevant `types/*`; update the plain `quotesApi.create` type (still used programmatically).
15. **Backend tests.** Add to `backend/tests/services/quotes/test_quote_service.py` and a deposit test module: deposit resolution (fixed vs pct, clamp to total), workspace-default inheritance, wizard save persists deposit + links/creates a contact + converts to a job, and reconcile-on-return marks paid idempotently (stubbed `retrieve_session_status`). Extend `tests/api/test_public_proposal_api.py` for `deposit-status` and the approve result deposit fields.
16. **Runtime verification with eyes.** With `make dev` running, use `.ezcoder/eyes/http.sh` to: save a wizard quote with a 50% deposit and confirm the priced deposit; GET the public proposal and confirm `deposit_mode/amount/required`; POST `deposit-status` twice and confirm idempotent `deposit_paid`; confirm convert→job succeeds on the wizard quote.
17. **Full CI parity.** Run `make ci.all`; fix any drift (codegen, lint, types, tests, migration up→down→up) until it exits 0.
