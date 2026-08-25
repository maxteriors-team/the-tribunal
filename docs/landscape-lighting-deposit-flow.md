# Landscape lighting client-deposit flow

Snapshot: 2026-08-17 · code: `1b782acae56f8a558f64b4372b508433d28e938c`

This is the operator and engineering source of truth for how a landscape-lighting
proposal becomes a deposit. It distinguishes what the production workspace does
today from the payment path that runs when a real deposit term is configured.

## Current production answer

**The Maxteriors Lighting production workflow does not currently request or
collect a client deposit.** A read-only production query on 2026-08-17 found:

```json
{"enabled": false, "mode": "percentage", "value": 0.0}
```

That value is `workspace.settings["pricing"]["deposit"]` for workspace
`ba0e0e99-c7c9-45ec-9625-567d54d6e9c2`. There were also no production quotes
linked to a landscape-lighting project yet, so there is no historical landscape
deposit transaction to inspect.

The proposal tab currently displays a **Payment milestones** input with
`50% scheduling deposit, 50% at completion`, but the input has no state or change
handler and is not included in `buildLandscapeProposalPayload()`. It is display-only.
The quote instead takes its deposit from the workspace pricing config. With the
production config disabled, a generated quote has no deposit amount, the client
approves without Stripe Checkout, and the operator receives no deposit.

## Supported operator path today

To collect a deposit on a landscape proposal without changing the workspace
default:

1. In the landscape studio, use **Create draft proposal** but do not send it yet.
2. Open **Quotes**, edit that draft, enable **Requires deposit**, and choose either
   a percentage or fixed amount. Save the quote.
3. Send the proposal by email or SMS from **Quotes**.
4. The client opens the public proposal, selects a package, and chooses
   **Accept … & Pay …**. Acceptance is recorded first; the browser then opens a
   Stripe-hosted Checkout page.
5. Confirm both the quote's **Deposit paid** state in **Quotes** and the charge in
   the Stripe Dashboard before scheduling work.
6. Use **Close Out Quote** to create the scheduled job and draft invoice. A paid
   deposit is carried to the invoice as an amount already paid.

A workspace-wide default can instead be enabled by updating the top-level
`deposit` block through `PUT /api/v1/settings/workspaces/{workspace_id}/pricing`.
There is no Settings UI for this block. See [price-book-editing.md](price-book-editing.md#2-pricing-config-blocks--the-api-mostly).
Changing the production default is a business decision: every new quote that does
not override the term can begin requesting real money.

## End-to-end system flow when a deposit is configured

### 1. Draft creation and delivery

`LightDesigner` builds a `ProposalWizardPayload` and calls the shared proposal-save
endpoint with the saved `LightingProject` ID. Without changing the designer, the
backend validates that project against the workspace/contact, snapshots its selected
installation-sheet image into the quote's customer mock-up gallery, and computes every
displayed price from the existing server price book. The visual gallery shows that
authoritative total and the configured amount due today beside the mock-up.

Deposit terms still come only from an explicit quote override or the workspace pricing
config. The designer's display-only payment-milestone text is never converted into a
charge. When a positive deposit is configured, the mock-up action accepts the exact
proposal first and then opens the existing Stripe Checkout flow.

The saved `Quote` is linked to the `LightingProject` and stores one of these:

- percentage: `deposit_percentage`
- fixed amount: `deposit_amount_fixed`

The draft is sent by email or SMS. Delivery changes the quote to `sent`, stamps
`sent_at`, exposes its public token, and—when the quote has a contact—creates or
links an open opportunity. The client receives a link to
`/p/quotes/{public_token}`. Merely sending does not charge anything.

Opening the public page records first/last view timestamps and creates the normal
operator view nudge. Staff preview links do not record a client view.

### 2. Acceptance and deposit calculation

The public proposal is the authoritative acceptance surface. If several packages
are offered, the client chooses one before approval. `QuoteService.approve_public()`
replaces the quote's line-item snapshot and total with the selected package, then
sets:

- `status = "approved"`
- `approved_at`
- the selected tier in `proposal_document`

The amount due is resolved against the **final accepted quote total**:

- percentage: `round(total × percentage / 100, 2)`
- fixed: `min(fixed amount, total)`, rounded to cents

A fixed amount takes precedence if both fields somehow exist. A non-positive
value produces no deposit.

Approval sends two best-effort notifications before payment:

- the customer receives an acceptance email when the contact has an email address;
  it states whether a deposit is still due and links back to the proposal;
- workspace members receive the normal proposal-approved push/email notification,
  according to their notification settings.

The quote is already `approved` at this point. If the client closes Checkout,
cancels, or the card fails, the quote remains **approved with deposit unpaid**.

### 3. Card collection and settlement

After approval, the public page calls
`POST /api/v1/quotes/public/{token}/deposit/checkout`. The backend creates a
Stripe Checkout Session in `payment` mode for exactly the resolved deposit,
then redirects the browser to Stripe. Quote and workspace identifiers are placed
in Stripe metadata so the billing webhook can reconcile the result.

A successful `checkout.session.completed` webhook marks the quote paid. The
success page also calls the reconcile endpoint and polls deposit status, which
covers a delayed webhook when the client returns to the proposal.

The quote stores:

- `deposit_paid_at`
- `deposit_payment_method = "card"`
- `deposit_payment_intent_id`
- `deposit_checkout_session_id`

The Checkout Session is created with the backend's single production
`STRIPE_SECRET_KEY`. There is no Stripe Connect account, `transfer_data`,
application fee, workspace-specific Stripe key, in-app wallet, or payout ledger.
Therefore the card charge belongs to the **one Stripe account configured for the
backend**, and Stripe pays that account's linked bank according to its
[Dashboard payout schedule](https://docs.stripe.com/payouts). The repository cannot
identify the receiving bank or payout schedule; verify those in **Stripe Dashboard →
Balances/Payouts and Settings → Bank accounts**.

This routing is suitable only when every workspace collecting money is the legal
merchant for that one Stripe account. Before allowing independent customer
businesses to collect deposits, use
[Stripe Connect](https://docs.stripe.com/connect/charges) or another tenant-specific
merchant setup and have the merchant-of-record/payment-facilitation arrangement
reviewed. This is engineering guidance, not legal advice.

### 4. Payment confirmation

On the first paid transition, every workspace member with payment notifications
enabled receives:

- a push notification titled **Payment received**;
- an email titled **Payment received — {quote number}** with the amount, customer,
  payment method, and quote number.

The **Quotes** list/detail displays the amount, paid timestamp, and method. The
customer's public proposal changes to **Deposit Paid** after reconciliation.
There is no separate CRM payment-ledger row for a quote deposit; the durable
record is on `quotes`, with the Stripe PaymentIntent ID for card payments.

The application sends the customer an **acceptance** receipt, not a post-payment
receipt. Checkout does not set `receipt_email`, so any card receipt depends on the
Stripe account's [automatic receipt setting](https://docs.stripe.com/receipts).
Verify that setting before promising the client a receipt.

### 5. Offline deposits

An operator with billing-write access can choose **Record deposit** in **Quotes**
and attest that cash, check, or another method was received. The operator can add
a note. This writes `deposit_paid_at`, method, note, and recorder user ID, and
expires any open Checkout Session.

Because the operator is recording their own action, this path does not send the
workspace's **Payment received** notification and it does not create a Stripe
charge. The paid amount is still credited if the quote is later converted to an
invoice.

### 6. Job, invoice, and fulfillment effects

Deposit payment alone does **not** create or schedule a job, create/send an
invoice, order parts, or move the opportunity to won. The operator must close out
the approved quote.

`Close Out Quote` can create a scheduled job and a draft invoice. Scheduling is
blocked while a required deposit is unpaid unless the operator explicitly
confirms an override. When an invoice is created after payment, its `amount_paid`
is initialized to the deposit, its status becomes `partial` when a balance
remains, and only the remaining balance is due. The invoice is not automatically
sent to the client.

The landscape project's design and installation sheet remain attached to the
quote/job handoff. Crew assignment notifications occur when a job is created with
crew members.

## State and notification matrix

| Event | Durable state | Client sees/receives | Operator sees/receives |
|---|---|---|---|
| Draft created | `Quote.status=draft`, linked lighting project and deposit terms | Nothing | Draft in Quotes |
| Proposal sent | `status=sent`, `sent_at`, public token; open opportunity linked when contact exists | Email or SMS proposal link | Sent quote; delivery result |
| Proposal viewed | `first_viewed_at`, `last_viewed_at`, `view_count` | Public proposal | View nudge |
| Client accepts | selected package snapshot; `status=approved`, `approved_at` | Confirmation page and acceptance email | Proposal-approved push/email |
| Checkout succeeds | paid timestamp, method, Stripe intent/session IDs | **Deposit Paid**; Stripe receipt only if Stripe is configured to send one | **Payment received** push/email and paid quote state |
| Offline payment recorded | paid timestamp, method, note, recorder | No automatic message | Paid quote state; no self-notification |
| Quote closed out | source job/invoice links | Draft invoice only if operator later sends it | Scheduled job and/or draft invoice; deposit credited |

## Current gaps and manual controls

1. **Production deposit is disabled.** No landscape deposit is collected until an
   operator sets terms on a quote or the workspace default is deliberately enabled.
2. **The studio's Payment milestones field is not persisted.** It must not be used
   as proof that a deposit was configured.
3. **Acceptance precedes payment.** An abandoned Checkout leaves an approved,
   unpaid quote; the operator must follow up or record an offline payment.
4. **Text-message acceptance is a human handoff, not quote approval.** The AI
   acknowledges the text, pauses itself, and pages the team. A human must approve
   the quote and separately direct the client to pay or record an offline deposit.
5. **Public acceptance does not trigger the operator-only approval side effects.**
   `approve_public()` currently does not call the parts-order notifier or
   `ServicePlanProvisioner`; use the landscape BOM/supplier CSV and verify any care
   plan manually. Operator-side `approve_quote()` does run those actions.
6. **The landscape studio does not refresh external acceptance.** Its quote-detail
   query is enabled only when its in-memory draft already says `approved`, so use
   **Quotes**—not the still-open studio—to confirm payment and close out the job.
7. **One Stripe account receives every card deposit.** There is no tenant payout
   routing. Confirm the actual bank and payout schedule in Stripe Dashboard.
8. **Refunds and term changes are manual.** Editing or clearing a deposit does not
   refund or recharge a client. Refund card payments in Stripe and reconcile the
   quote/invoice record deliberately.

## Evidence map

### Runtime checks — production, read-only, 2026-08-17

- Maxteriors Lighting pricing config: deposit disabled, percentage value `0`.
- Landscape-linked quote aggregate: `0` total, `0` with deposit terms, `0` paid.
- Production backend has a live restricted Stripe key and webhook secret configured;
  no charge or write was performed during this review.

### Code paths

- Landscape payload and send flow:
  `frontend/src/components/estimator/light-designer.tsx`,
  `frontend/src/lib/estimator/landscape-proposal.ts`
- Public approval and package repricing:
  `backend/app/services/quotes/quote_service.py`
- Checkout, reconciliation, manual recording:
  `backend/app/services/payments/quote_deposit_service.py`
- Stripe account routing:
  `backend/app/services/payments/call_payment_service.py`
- Billing webhook:
  `backend/app/api/v1/billing.py`
- Customer/operator notifications:
  `backend/app/services/email.py`,
  `backend/app/services/payments/customer_payment_notifications.py`
- Job/invoice handoff:
  `backend/app/services/quotes/quote_service.py`,
  `frontend/src/components/quotes/convert-quote-dialog.tsx`

### Regression coverage

- `backend/tests/services/quotes/test_wizard_flow.py`
- `backend/tests/services/quotes/test_quote_deposit.py`
- `backend/tests/services/quotes/test_quote_service.py`
- `frontend/src/components/proposal/client-proposal-view.test.tsx`
- `frontend/src/components/quotes/record-deposit-dialog.test.tsx`

Targeted verification on 2026-08-17 passed **18 backend integration tests** and
**18 frontend component tests** covering landscape deposit defaults, package
repricing, Stripe/manual payment state, invoice credit, unpaid-deposit override,
the public acceptance UI, and offline recording.
