# Invoice optional line items

## Outcome
Senders can mark invoice line items as optional. Recipients see selected-by-default checkboxes, can include or remove optional items, see totals update immediately, and send the selected item IDs to a server-priced Stripe Checkout flow.

## Data and payment integrity
- Add `is_optional` and `is_selected` booleans to `invoice_line_items`; existing rows migrate to required/selected.
- Required items are always selected. New optional items begin selected so the sent invoice total matches the sender’s preview.
- The public pay request accepts only selected optional line-item UUIDs. The service validates ownership/optionality, applies the choice, recomputes totals/status server-side, and charges the resulting balance.
- Expire a previous open Stripe Checkout Session before replacing it, preventing an obsolete item selection from remaining payable.

## Files
- Model/migration: `backend/app/models/invoice.py`, new file under `backend/alembic/versions/`.
- API contracts/routes: `backend/app/schemas/invoice.py`, `backend/app/api/v1/invoices.py`.
- Domain/payment logic: `backend/app/services/invoices/invoice_service.py`, `backend/app/services/payments/call_payment_service.py`.
- Backend coverage: `backend/tests/services/invoices/test_invoice_service.py` and public invoice API tests.
- Sender UI/types: `frontend/src/components/invoices/invoice-create-dialog.tsx`, `frontend/src/components/invoices/invoice-edit-dialog.tsx`, `frontend/src/types/invoice.ts`.
- Recipient UI/API/types/styles: `frontend/src/components/invoice/public-invoice-view.tsx`, `frontend/src/components/invoice/invoice-theme.css`, `frontend/src/lib/api/public-invoices.ts`, `frontend/src/types/public-invoice.ts`.
- UX coverage: `frontend/src/components/invoice/public-invoice-view.test.tsx` and a Playwright invoice optional-item journey under `frontend/e2e/`.
- Generated contracts: `backend/openapi.json`, `frontend/src/lib/api/_generated.ts`.

## Verification
- Backend service/API tests prove required items cannot be removed, foreign/non-optional IDs are rejected, totals are recomputed server-side, and checkout receives the selected balance.
- Frontend component tests prove checkbox interactions update subtotal/total/balance and the pay payload.
- Playwright exercises sender marking an item optional and recipient selecting/deselecting it at desktop and mobile widths before checkout.
- Run targeted backend tests, frontend tests/type checks, codegen drift check, migration checks, and inspect Playwright screenshots/results.

## Steps
1. Add and migrate invoice line-item optional/selected state with safe defaults for existing invoices.
2. Extend invoice schemas, public pay request, and generated API contracts with optional-item fields and stable public line-item IDs.
3. Update invoice service totals and Stripe checkout creation to validate/persist recipient choices and invalidate obsolete checkout sessions.
4. Add sender create/edit controls and typed request handling for marking invoice rows optional.
5. Add recipient checkbox controls, live server-equivalent totals, selected-ID checkout payload, responsive styling, and accessible status text.
6. Add backend and frontend automated coverage for optional-item pricing, validation, and checkout behavior.
7. Add and run a Playwright sender-to-recipient UX journey at desktop and mobile sizes, then fix any interaction or layout failures.
8. Run codegen, targeted CI/migration checks, and the invoice HTTP probe against representative public read/pay requests.