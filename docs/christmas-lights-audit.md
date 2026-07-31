# Christmas lighting: end-to-end audit

**Date:** 2026-07-30 · **Scope:** the seasonal holiday-lighting revenue line, from
pricing config to takedown. Written before any code changes, from reading the
code rather than assuming.

**Context:** a metro Detroit exteriors business whose revenue collapses
December–March. Christmas lighting is the winter revenue line, so the health of
this chain is the health of Q4/Q1.

## TL;DR

The pricing *engine* is genuinely deep and correct. The chain breaks in three
places, in descending order of cost:

1. **The operator cannot turn Christmas on.** `ChristmasConfig.enabled` defaults
   to `False` and has **no UI control anywhere**. Nine other fields the business
   actually sells on — takedown rate, storage price, season dates, job minimum —
   are equally unreachable. The only way to sell Christmas lighting today is to
   hand-edit JSONB in Postgres.
2. **No season-over-season renewal exists.** Nothing in the codebase can answer
   "who bought Christmas lighting last season". Last year's customers — the
   cheapest possible source of this year's bookings — are indistinguishable from
   a 2019 gutter-cleaning lead.
3. **Takedown is dispatched whether or not it was sold**, and **storage is
   billed but never recorded**.

Everything else in the chain works and is well tested.

---

## One correction to the brief

`frontend/src/app/christmas-lights/page.tsx` is **not** a customer-facing
surface. It renders inside `<AppSidebar>` and the route requires `billing:read`
(`app-nav.ts:181`), so it is an operator hub. It is also **hidden from the
sidebar** (`sidebar: false`) and reachable only by URL or ⌘K — which matters
more than its contents: a seasonal workflow nobody can navigate to generates no
revenue. The genuinely customer-facing seasonal surfaces are
`/p/quotes/[token]` (the proposal) and `/p/compare/[token]` (the
permanent-vs-seasonal comparison), both of which exist and render.

## The chain, link by link

### 1. Pricing config → ✅ deep, ❌ unreachable

`backend/app/schemas/pricing.py:485` `ChristmasConfig` is a complete seasonal
engine: `roofline_per_ft`, a standardized `SeasonalItem` decor catalog
(`each` / `per_ft` units), `takedown_enabled` + `takedown_rate`, `storage_price`,
per-workspace season anchors, `minimum`, `perks`, and Good/Better/Best
`packages`. Legacy `tree_rates`/`bush_rates`/`wreath_rates` blobs upgrade
transparently (`pricing.py:521`). Stored as JSONB under
`workspace.settings["pricing"]`, read leniently through
`backend/app/services/quotes/pricing_config.py:25`.

**The break.** `frontend/src/components/settings/seasonal-pricing-settings-tab.tsx`
(844 lines) edits only `roofline_per_ft`, `items`, and the package block. Its
save payload (`:427`) spreads a `serverChristmas` snapshot to preserve
everything else — which is correct round-tripping, but means the following are
**write-only from the database**:

| Field | Consequence of being unreachable |
|---|---|
| `enabled` | `frontend/src/app/quotes/page.tsx:71` gates the entire Christmas service on it. Default `False` → **the service does not exist for a new workspace.** |
| `takedown_rate` | The business cannot price its own takedown. Stuck at the 25% placeholder. |
| `storage_price` | Defaults to `0`; the wizard hides the storage checkbox when `storage_price <= 0` (`builder-sections.tsx:394`). **Storage is unsellable.** |
| `season_install_month/day`, `season_takedown_month/day` | These anchor every provisioned install/takedown job. A Detroit operator cannot move them off the mid-Nov / early-Jan defaults. |
| `takedown_enabled`, `minimum`, `label` | Takedown offer, job floor, and the customer-facing name are all frozen. |

By contrast `permanent-pricing-settings-card.tsx:170` *does* ship an `enabled`
toggle and a `minimum` field. The asymmetry is unintentional.

### 2. Proposal wizard → ✅ complete

`WizardChristmasSelection` (`backend/app/schemas/proposal_wizard.py:126`) carries
`roofline_feet`, `items`, `takedown`, `storage`, `selected_package`. Both the rep
surfaces expose all of them — `builder-sections.tsx:373-403` (wizard) and
`light-designer.tsx:741-757` (photo estimator). The wizard POSTs *selection
only*; the server computes money. Correct.

### 3. Quote / pricing → ✅ correct and covered

`price_christmas` (`proposal_pricing.py:584`) grosses roofline, each decor
category, takedown (a fraction of the **net** install subtotal) and storage
individually, so display lines sum exactly to `raw_total`.
`price_christmas_package` (`:658`) is the same engine restricted to a package's
coverage — no second pricing path. Covered by 14 tests in
`backend/tests/services/quotes/test_proposal_pricing.py`, including
legacy-blob-price-parity (`:566`) and package monotonicity (`:652`).

### 4. Public proposal → ✅ renders, ⚠️ generic

`client-proposal-view.tsx:479` renders a Christmas `category_section` with the
exact same markup as permanent — no season dates, no takedown/storage callout,
no seasonal iconography. Functional, not differentiated. The
permanent-vs-seasonal comparison page (`p/compare/[token]`) *is* Christmas-themed.
Field-level leakage is guarded by the allowlist at
`proposal_wizard.py:327` (`CLIENT_SAFE_DOCUMENT_FIELDS`).

### 5. Deposit → ✅ works

Generic quote deposit (`DepositConfig`, `quote_deposit_service.py`) applies to
Christmas quotes with no seasonal special-casing needed.

### 6. Scheduled job + takedown → ✅ exists, ❌ two defects

**This was the item most likely to be missing, and it is not.**
`backend/app/services/recurring_jobs/service_plan_provisioner.py:198` creates, on
quote approval and *inside the approval transaction*, a **pair** of
`ServicePlanType.CHRISTMAS_LIGHTS` templates — Install and Takedown — both
`YEARLY`, anchored on the workspace's configured season, with takedown forced to
fall after the install it belongs to (`:207`). `recurring_job_worker` then
materializes real `Job` rows 30 days ahead. Idempotent via the partial unique
index on `(source_quote_id, plan_type, title)`. Twelve tests cover it.

Two defects:

- **Takedown is provisioned unconditionally.** `_has_christmas_section`
  (`:181`) only checks that a Christmas section exists; `WizardChristmasSelection.takedown`
  never reaches the stored document in queryable form (it survives only as a
  display line labelled "Post-season takedown"). A customer who declined takedown
  still gets a takedown crew dispatched every January — recurring unpaid work.
- **Storage has no operational record.** `storage: true` produces a fee line and
  nothing else. Sell storage and you are physically holding a customer's decor
  with no record that you have it, what it is, or that it must go back on the
  truck in November.

### 7. Season-over-season renewal → ❌ absent (highest-value gap)

Exhaustively verified. Nothing anywhere queries "bought Christmas lighting last
season":

- `ServicePlanType.CHRISTMAS_LIGHTS` is **written** by the provisioner and
  **read** by exactly one place — a list-endpoint filter
  (`recurring_job_service.py:161`). Never used for audience selection.
- Christmas `category_sections` are read only at approval time
  (`service_plan_provisioner.py:181`). No index, no `WHERE`, ever.
- `contact_filters.py` cannot reach jobs, quotes, or service plans at all — its
  field vocabulary is 14 `Contact` columns plus tags and BANT signals.
- The seeded "lead reactivation" campaign is a **CSV import**, not a query
  (`workspace_setup.py:358`).

The only automatic renewal that exists is **delivery-side**: the `YEARLY`
service plan silently materializes next November's install job. Nobody re-quotes,
re-prices, or asks the customer. That is simultaneously a missed sale (no price
increase, no upsell) and an operational risk (a job on the board for a customer
who never re-confirmed).

### 8. Early-bird booking → ⚠️ exists in the working tree, seasonally blind

There is substantial **uncommitted, staged** pre-booking work (2 tables, 8
services, a worker, a 4-step frontend wizard; tests pass). It sells future-dated
seasonal work to a warm database and takes a deposit. It is complete and good —
but **service-blind and date-blind**:

- The season is hand-typed months (`season-step.tsx`); it never reads
  `ChristmasConfig.season_install_month/day`, which already exist per workspace.
- `past_customer_condition` (`audience.py:74`) is *any* completed job or *any*
  approved quote, **with no date bound and no service predicate**.

So the machinery to run an early-bird Christmas campaign exists; the ability to
aim it at last year's lighting customers does not.

---

## What this task changes

Additive only. The pricing engine is untouched (package-tier generalization is a
separate task and must not collide). Regression tests were added around the
existing Christmas pricing output *before* adjacent code changed.

1. **Seasonal settings UI** — expose the unreachable `ChristmasConfig` fields
   (`enabled`, `label`, `takedown_enabled`, `takedown_rate`, `storage_price`,
   `minimum`, and the four season anchors). Unblocks the whole line.
2. **Takedown/storage are recorded on the quote** — two optional booleans on the
   Christmas `ProposalCategorySection`. Old documents lack them and fall back to
   today's behaviour, so nothing already sold changes.
3. **Takedown is provisioned only when sold**; when storage is sold the takedown
   plan says so, so the crew brings bins.
4. **Prior-season Christmas customers become a targetable audience** — a new
   season-aware predicate, wired into the existing pre-booking audience as an
   opt-in slice. Reuses the existing enroll → launch → deposit path; no new
   worker, no new campaign type.
5. **The renewal path is discoverable** — the `/christmas-lights` hub leads with
   it.

### Proof

`make ci.all` exits 0 (3,660 backend tests, 787 frontend, no codegen drift,
migrations up→check→down→up). The load-bearing new tests:

| What it protects | Where |
|---|---|
| Christmas pricing output is byte-identical | `backend/tests/services/quotes/test_christmas_regression.py` (8 tests: totals, display line wording/order, per-category costs, job minimum, legacy-blob parity, package totals + order, premier≡à-la-carte) |
| Takedown is dispatched only when sold, and an old quote never loses it | `backend/tests/services/recurring_jobs/test_service_plan_provisioner.py` (5 new tests) |
| Season arithmetic across the New Year boundary | `backend/tests/services/seasonal/test_christmas_renewal.py` |
| The renewal audience really finds last season's homes, is off by default, bounds its lookback, and still honours opt-out | `backend/tests/services/prebooking/test_prebooking_flow.py` (4 new DB-backed tests) |
| The new slice is reachable over HTTP and its flags actually reach the service | `backend/tests/api/test_prebooking_audience_api.py` |
| Settings fields the editor does not expose still round-trip | `frontend/src/components/settings/seasonal-pricing-settings-tab.test.tsx` |

## Known follow-ups (deliberately out of scope)

- **Storage inventory.** Recording *that* storage was sold is not the same as
  knowing which bins, where, and whether they came back. A real
  `SeasonalStorageItem` table is the right next step once storage is actually
  being sold.
- **Christmas-aware public proposal.** Season dates and a takedown/storage
  callout on the client page.
- **Pre-booking season prefill from `ChristmasConfig`** — the wizard should
  offer the workspace's configured install/takedown anchors instead of blank
  month pickers.
- **Config-driven icon legend** on `/christmas-lights`: `LEGEND_CATEGORIES` is
  hardcoded to 6 keys and ignores custom decor categories.
- **Renewal without a re-sell.** The `YEARLY` service plan still auto-materializes
  next season's install with no customer confirmation. Once the renewal campaign
  is running, that auto-roll should arguably become opt-in.
- **Signups that predate the provisioner** are invisible to the renewal
  predicate, which keys off the `CHRISTMAS_LIGHTS` plan row (indexed) rather
  than scanning every quote's `category_sections` JSONB (not indexed). If that
  back-catalogue matters, backfill plan rows rather than widening the query.

## Dependency note

The renewal audience is wired into the **pre-booking** feature, which was
uncommitted staged work in the tree when this audit was written. That was a
deliberate choice: pre-booking already owns enrollment, opt-out suppression, slot
caps, deposits and the scheduled launch, and re-deriving opt-out logic in a
second place is exactly how a customer ends up in two campaigns or none. The
season arithmetic itself lives in `backend/app/services/seasonal/`, which has no
pre-booking dependency, so it survives if that work is ever dropped.
