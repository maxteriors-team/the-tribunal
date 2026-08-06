# Card on file

Save a customer's card once, charge it later without them present — for deposits,
recurring work, and no-show fees.

## Why this is not what exists today

Every payment in the product is a **one-off hosted Checkout link**: invoice
payment links (`invoice_service._start_checkout`), proposal deposits
(`quote_deposit_service`), and in-call deposits (`call_payment_service`). The
customer re-enters their card every single time, and nothing is retained. Grep
confirms **zero** occurrences of `stripe_customer_id`, `payment_method`,
`SetupIntent`, or `off_session` anywhere in `backend/app`.

`WorkspaceIntegration(integration_type="stripe")` stores `{customer_id,
subscribed}` — that is *the workspace as a customer of The Tribunal* (the SaaS
subscription), **not** the workspace's merchant account. There is no Connect: one
platform key (`settings.stripe_secret_key`) serves every call.

## The decision this plan bakes in

**Cards are saved on the platform Stripe account**, which is correct while The
Tribunal is Maxteriors' own tool, and is also **step 1 of the documented Connect
path** — Stripe's own guide for sharing payment methods across connected accounts
begins by saving the customer + payment method on the *platform* account, then
cloning to a connected account at charge time. Cloning is only needed for direct
charges on connected accounts; it is unnecessary when charging on the platform
account. So this is not a detour that has to be unwound.

The one thing that **is** expensive to retrofit is consent: Stripe requires
telling the customer their authorization extends to connected accounts on the
platform. That cannot be added to already-saved cards without re-asking every
customer, so the consent copy ships Connect-ready on day one (step 12).

## Product decision embedded here: the customer types their own card

Two possible surfaces:

- Operator types the customer's card into the dashboard (MOTO / card-not-present:
  higher fraud exposure, higher decline rates, and the "written agreement" record
  Stripe requires would be the *operator* clicking a box on the customer's behalf).
- **Customer opens a tokenized link and types their own card.** ← chosen.

The second reuses the `/p/{token}` public-page pattern already proven by invoices
(`frontend/src/app/p/invoices/[token]/page.tsx`) and proposals, and makes the
consent record genuinely the customer's act. The operator's job is to *send* the
link from the contact record.

Unlike the invoice token, the card-save token **expires** (72h) and is
single-use — a permanent "enter your card here" URL is a standing phishing asset.

## Compliance requirements (verbatim constraints from Stripe docs)

To charge off-session, the terms shown at save time must include:

1. the customer's agreement to us initiating payments on their behalf,
2. the anticipated timing and frequency of payments,
3. how the payment amount is determined,
4. the cancellation policy.

…and we must **keep a record of the customer's written agreement**. That record is
the `mandate_*` columns in step 2, written server-side from the request that
confirmed the SetupIntent — not a boolean the client asserts.

Also non-negotiable:

- **Raw PAN never touches our API.** Stripe.js/Elements renders in a Stripe-owned
  iframe; our server sees only `pm_...` handles and display metadata.
- Stripe.js must be loaded **from `js.stripe.com`**, never bundled or self-hosted.
- The SetupIntent `client_secret` must never be logged, embedded in a URL, or
  exposed to anyone but that customer.

## Blast radius: the two Stripe-touching files

Only two modules construct a Stripe client today (13 call sites total).

### `backend/app/services/payments/call_payment_service.py`

Owns `_stripe_client()`, `to_minor_units()`, `from_minor_units()`, and
`_ZERO_DECIMAL_CURRENCIES` — all genuinely shared, but currently living inside a
module named for *in-call payments*. Card-on-file importing from there is the
wrong dependency direction.

**Change:** extract the Stripe boundary into a new
`app/services/payments/stripe_client.py` (client factory + currency helpers +
zero-decimal set). `call_payment_service` re-exports the names it already
exposes so `invoice_service` (which calls
`call_payment_service.create_payment_checkout_session`) and the existing tests
keep working unchanged. This is the **Connect seam**: when Connect lands,
`stripe_client()` grows a `stripe_account=` parameter in exactly one place.

Risk: `tests/services/test_call_payment_service.py` asserts on
`call_payment_service.to_minor_units` directly — the re-export keeps it passing,
and that is a real regression signal to watch.

### `backend/app/api/v1/billing.py`

The single webhook endpoint. `stripe_webhook` verifies the signature then
dispatches on `event["type"]`, currently handling only
`checkout.session.completed` and `customer.subscription.deleted`.
`_handle_checkout_completed` then re-routes by metadata through a four-branch
if-chain (`invoice_id` → `quote_id` → `mode == "payment"` → subscription).

**Change:** add two event types — `setup_intent.succeeded` (persist the saved
card) and `payment_intent.payment_failed` (record an off-session decline). Both
are *new top-level branches*; the fragile metadata if-chain is left alone rather
than extended, because its ordering is load-bearing (invoice before quote before
generic payment) and this feature does not need to touch it.

Risk: `tests/api/test_billing_webhook_route.py` signs real HMAC payloads and
asserts the routing. New branches must not reorder existing ones.

## Storage

### `contacts.stripe_customer_id`

`String(255)`, nullable, indexed. An opaque Stripe handle, not PII — same
treatment as the existing plaintext `invoices.stripe_checkout_session_id`. It goes
on `contacts` (not the payment-method table) because one Stripe Customer is
reused across a contact's cards.

### New table `contact_payment_methods`

| Column | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `workspace_id` | UUID FK → workspaces, indexed | tenant scope |
| `contact_id` | BigInteger FK → contacts CASCADE, indexed | |
| `stripe_payment_method_id` | String(255), unique | the `pm_...` handle |
| `stripe_customer_id` | String(255) | denormalized for charge-time lookup |
| `brand` / `last4` / `exp_month` / `exp_year` | String(20)/String(4)/Int/Int | **display only — never PAN** |
| `is_default` | Boolean | partial unique index on (contact_id) where is_default |
| `status` | String(20) | `active` / `removed` / `expired` |
| `mandate_text_version` | String(50) | which consent wording they agreed to |
| `mandate_accepted_at` | timestamptz | |
| `mandate_ip` / `mandate_user_agent` | String | server-observed, the "written agreement" record |
| `created_at` / `updated_at` | timestamptz | |
| `removed_at` | timestamptz nullable | |

No column can hold a PAN. A test asserts the model has no field whose name
suggests one (step 16).

### New table `card_charge_attempts`

Every off-session attempt, success or failure — needed because a silent decline
on an automated charge is invisible otherwise, and because "did we already try
this?" must be answerable without asking Stripe.

Columns: `id`, `workspace_id`, `contact_id`, `payment_method_id` FK,
`stripe_payment_intent_id`, `amount`, `currency`, `status`
(`succeeded`/`declined`/`requires_action`/`error`), `decline_code`,
`failure_message`, `idempotency_key` (unique), `trigger` (`invoice`/`deposit`/
`recurring_job`/`no_show_fee`/`manual`), `invoice_id` nullable, `created_at`.

## Off-session charge semantics

`PaymentIntent.create(..., payment_method=pm, customer=cus, off_session=True,
confirm=True)`. Per Stripe: a failed attempt raises with **HTTP 402** and the
PaymentIntent lands in `requires_payment_method`.

Three distinct outcomes, and conflating them is the classic bug:

| Outcome | Detection | What we do |
|---|---|---|
| **Succeeded** | returns `status == "succeeded"` | record payment via existing `InvoiceService.record_payment` (already idempotent on `payment_intent_id`) |
| **Needs authentication** | `CardError.code == "authentication_required"` | the declined PI's `client_secret` is reusable — send the customer a recovery link to authenticate. **Not** a dead loss. |
| **Hard decline** | any other `CardError` code | mark attempt `declined`, notify the operator, **stop**. No automatic retry. |

The no-retry rule is deliberate: a worker that retries a hard decline every tick
generates repeated authorization attempts against a real person's card, which is
how you earn card-network penalties.

## Charge triggers

The service is shared; the triggers differ in policy, and two default **off**.

1. **Invoice balance, operator-initiated** — a "Charge card on file" button.
   Proves the whole loop end-to-end with a human deciding. Ships first.
2. **Quote deposit on acceptance** — reuses `quote_deposit_service.deposit_amount`.
   Default off per workspace.
3. **Recurring-job invoice** — `RecurringJobService.materialize_due` already
   creates the work; auto-charging its invoice is a setting. Default off.
4. **No-show fee** — needs an amount + explicit enable, default off. Charging
   someone for missing an appointment is a policy call with real chargeback risk,
   and the consent text must name it (requirement 2 above: timing and frequency).

Every trigger honours the existing **`no-automation` contact tag** — a contact
opted out of automation must not be silently charged by a worker. Manual
operator-initiated charges are unaffected, matching the tag's documented meaning.

## Codegen

New public routes (`POST /p/card-setup/{token}/intent`) and authenticated routes
under `/workspaces/{id}/contacts/{contact_id}/payment-methods` change the OpenAPI
contract. Run `make codegen` and commit `backend/openapi.json` +
`frontend/src/lib/api/_generated.ts` **in the same commit** as the schema change —
`codegen/check` diffs against HEAD and fails on uncommitted artifacts.

## Tests

Unit tests mock the Stripe client (matching `tests/services/test_call_payment_service.py`,
which patches module attributes rather than hitting the network). Integration
tests use the real local DB under `-m integration`.

**Save:**
- SetupIntent creation returns a client secret and creates/reuses one Stripe
  Customer per contact (second call does not create a second customer).
- `setup_intent.succeeded` webhook persists brand/last4/exp + the mandate record.
- Replaying that webhook is idempotent — no duplicate row.
- Saving without consent is refused (422), and no Stripe call is made.
- **No PAN is persisted**: the stored row's values contain no 13–19 digit run.
- An expired or already-used setup token is refused (410/404) before any Stripe call.

**Off-session charge:**
- Success records the payment through `InvoiceService.record_payment` and writes a
  `succeeded` attempt row.
- The same `idempotency_key` charged twice produces **one** PaymentIntent and one
  attempt row.
- A contact with no active card returns a typed "no card on file" result rather
  than raising.
- Cross-workspace isolation: workspace A cannot charge workspace B's saved card.
- A contact tagged `no-automation` is skipped by automated triggers but still
  chargeable by an explicit operator action.

**Declined card:**
- A `CardError` with `code="card_declined"` → attempt row `declined` with the
  decline code, invoice **not** marked paid, operator notified once, and **no
  retry scheduled**.
- A `CardError` with `code="authentication_required"` → attempt row
  `requires_action` carrying the client secret handle, and a recovery link is
  issued instead of a failure notice.
- `payment_intent.payment_failed` webhook reconciles an attempt row that the
  synchronous path never saw (network drop mid-charge).
- The failure path never leaves an invoice partially mutated.

Manual sandbox pass before merge, using Stripe test values (`pm_card_visa` for
success; the decline / `authentication_required` PaymentMethod ids to be read
from `docs.stripe.com/testing` at implementation time rather than from memory).

## Risks

- **Money is real.** Everything ships behind test keys and a sandbox pass first.
- **`stripe_publishable_key` is configured but never used** and there is no
  `@stripe/stripe-js` dependency. The key is served from a backend endpoint rather
  than a `NEXT_PUBLIC_` var: it keeps one source of truth, and under Connect the
  publishable key becomes per-connected-account, so the endpoint shape survives.
- **Unauthenticated endpoint that creates billable Stripe objects** — must be rate
  limited per IP and per token, following `services/rate_limiting/embed_limiter.py`.
- The eyes redaction filter covers `client_secret` as a *field name* but not bare
  `sk_live_`/`sk_test_`/`seti_..._secret_...` shapes (it only masks OpenAI `sk-`).
  Widening it is step 21.

## Steps

1. Create `backend/app/services/payments/stripe_client.py` holding `stripe_client()`, `to_minor_units()`, `from_minor_units()`, and `_ZERO_DECIMAL_CURRENCIES`, moved from `call_payment_service.py`; document it as the single Connect seam where a future `stripe_account=` parameter lands.
2. Update `backend/app/services/payments/call_payment_service.py` to import from the new module and re-export `to_minor_units`/`from_minor_units` so `invoice_service` and `tests/services/test_call_payment_service.py` keep passing; run that test file to confirm no regression.
3. Add `stripe_customer_id` (String(255), nullable, indexed) to `backend/app/models/contact.py`.
4. Create `backend/app/models/contact_payment_method.py` with the columns in the Storage section, including the `mandate_*` consent record and a partial unique index enforcing one default card per contact; no column may hold a PAN.
5. Create `backend/app/models/card_charge_attempt.py` with a unique `idempotency_key` and the `trigger`/`status`/`decline_code` columns.
6. Generate the migration with `make migrate.new m="card on file"`, verify the autogenerated diff matches the three model changes, then `make migrate`.
7. Create `backend/app/services/payments/card_on_file_service.py` with `ensure_stripe_customer()`, `create_setup_intent()`, and `save_payment_method_from_setup_intent()`; the save path writes brand/last4/exp plus the mandate record and is idempotent on `stripe_payment_method_id`.
8. Add `charge_saved_card()` to that service: `off_session=True, confirm=True`, wrapped so a `stripe.CardError` returns a typed result distinguishing `succeeded` / `requires_action` (code `authentication_required`, carrying the reusable client secret) / `declined`, writing a `card_charge_attempt` row in every case and never auto-retrying a hard decline.
9. Add a `contact_card_setup_tokens` concern: a 72-hour expiring, single-use token minted per contact (mirroring `invoices.public_token` generation via `secrets.token_urlsafe`), plus its migration.
10. Add the authenticated router `backend/app/api/v1/payment_methods.py` under `/workspaces/{workspace_id}/contacts/{contact_id}/payment-methods` — list, delete, set-default, mint-setup-link, and `POST /charge` — gated on `CanWriteBilling`/`CanReadBilling`; register it in `backend/app/api/v1/router.py`.
11. Add the public router for `/p/card-setup/{token}`: `GET` returns the contact's display name, the publishable key, and the consent text version; `POST /intent` creates the SetupIntent and returns its client secret. Rate limit per IP and per token following `backend/app/services/rate_limiting/embed_limiter.py`, and never log the client secret.
12. Write the Connect-ready consent copy as a versioned constant in the service module, covering all four Stripe-required terms (agreement to initiate payments, timing/frequency, how the amount is determined, cancellation policy) **and** stating that authorization extends to connected accounts on the platform; store its version string on every saved card.
13. Extend `stripe_webhook` in `backend/app/api/v1/billing.py` with two new top-level branches — `setup_intent.succeeded` → persist the saved card, `payment_intent.payment_failed` → reconcile the attempt row — without reordering the existing `checkout.session.completed` metadata routing.
14. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts` in the same commit as the schema change.
15. Write `backend/tests/services/payments/test_card_on_file_save.py` covering the Save bullet list: customer reuse, webhook persistence of brand/last4/mandate, webhook replay idempotency, consent refusal, expired/used token refusal, and an assertion that no stored value contains a 13–19 digit run.
16. Write `backend/tests/services/payments/test_card_on_file_charge.py` covering the Off-session bullet list: success recording through `InvoiceService.record_payment`, idempotency-key deduplication, the typed no-card-on-file result, cross-workspace isolation, and `no-automation` skipping automated triggers while still allowing a manual charge.
17. Write `backend/tests/services/payments/test_card_on_file_declines.py` covering the Declined bullet list: hard decline records and notifies without retrying, `authentication_required` issues a recovery link instead of a failure, the `payment_intent.payment_failed` webhook reconciles an attempt the sync path missed, and a failed charge leaves the invoice unmutated.
18. Add `@stripe/stripe-js` and `@stripe/react-stripe-js` to `frontend/package.json` (resolve current versions from the npm registry, do not pin from memory).
19. Build `frontend/src/app/p/card-setup/[token]/page.tsx` plus its card-form component using the Stripe Payment Element loaded from `js.stripe.com`, rendering the versioned consent text with an explicit opt-in the customer must check before the submit button enables.
20. Add the operator surface: a "Payment method" section on the contact sidebar showing brand/last4/expiry or an empty state, a "Send card-on-file link" action, a remove-card action with confirmation, and a "Charge card on file" action on the invoice detail view; add frontend tests for the save-link and charge mutations including the declined-card error path.
21. Widen `.ezcoder/eyes/_redact.sh` to mask bare `sk_live_`/`sk_test_` keys and `seti_`/`pi_`-style `..._secret_...` values so probe artifacts never persist a Stripe secret.
22. Run `make ci.all` and confirm exit 0, then do a Stripe **sandbox** pass with test keys: save a card via the public link, charge it off-session, and force one hard decline and one `authentication_required` decline, capturing the resulting attempt rows as evidence.
