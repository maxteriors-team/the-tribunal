# Bistro inventory lifecycle

## Outcome

Track only Bistro inventory units that materially drive stock and COGS:

- Permanent Bistro installed footage is a consumable stock item measured in feet; its weighted-average unit cost includes the socket line, bulbs, support cable, connectors, and normal small-part allowance.
- Permanent Bistro poles are consumable stock items measured individually.
- Temporary Bistro light sets and temporary Bistro poles are reusable assets: they are reserved, deployed to a completed installation job, and later returned to availability without posting their purchase price to that job's COGS.
- Christmas inventory behavior is unchanged and out of scope.

A Bistro quote will show whether these configured units are available. Accepted quotes that become jobs reserve stock. Completing the job requires an operator to confirm actual usage; the same transaction consumes permanent units, deploys temporary assets, releases unused reservations, posts permanent weighted-average COGS, and marks the job complete.

## Existing foundation to reuse

- `backend/app/models/inventory.py` already provides workspace-scoped items, stock levels, immutable ledger movements, reorder points, safety stock, and weighted-average valuation.
- `backend/app/services/inventory/stock_service.py::StockService.consume` already locks stock rows, prevents negative inventory, snapshots weighted-average COGS, and supports idempotent job references.
- `backend/app/services/jobs/job_materials.py::JobMaterialsService` and `frontend/src/components/jobs/job-materials-panel.tsx` already display job usage and reverse mistakes through return entries rather than deleting ledger history.
- `backend/app/services/inventory/quote_availability.py::QuoteInventoryAvailabilityService.check` already compares internal fulfillment SKUs with tracked stock, but deliberately does not account for reservations.
- `backend/app/services/quotes/quote_service.py::_get_or_create_job_for_quote` creates the job inside the quote-acceptance transaction and is the correct reservation boundary.
- `backend/app/schemas/pricing.py::BistroInstallationPricing` already carries server-measured permanent/temporary feet and pole counts, so inventory quantities will come from the authoritative proposal calculation rather than the canvas or browser.

## Inventory configuration and COGS

Extend each `BistroInstallationConfig` in workspace pricing with internal inventory mappings:

- `lights_inventory_sku`: active workspace inventory SKU used for light footage/sets.
- `poles_inventory_sku`: active workspace inventory SKU used for poles.
- `stock_feet_per_light_unit`: `1` for permanent footage and normally `200` for one temporary light set.

The Bistro settings card will select active inventory items with SKUs instead of accepting arbitrary identifiers. The settings endpoint will verify every selected SKU exists, is active, belongs to the workspace, and is not mapped as both permanent-consumable and temporary-reusable.

Recommended CRM items are `BISTRO-PERM-FT` (`ft`), `BISTRO-PERM-POLE` (`each`), `BISTRO-TEMP-200FT` (`set`), and `BISTRO-TEMP-POLE` (`each`). These are operator-created/mapped rather than silently seeded because physical counts, blended costs, and reorder limits are business data. Permanent receipts use installable feet/poles and their blended direct cost; tiny components remain outside CRM.

`proposal_builder.py` will append only the mapped Bistro units to the private fulfillment list:

- permanent lights: exact measured feet;
- permanent poles: marked pole count;
- temporary lights: `ceil(measured feet / stock_feet_per_light_unit)` reusable sets;
- temporary poles: marked pole count as reusable units.

`FulfillmentPart` gains a backward-compatible `inventory_behavior` field defaulting to `consumable`; existing proposal snapshots therefore continue to parse. Public proposal sanitization continues removing fulfillment data, so SKUs, quantities, and behavior never reach customers.

## Reservation and deployment model

Add `InventoryJobAllocation` in `backend/app/models/inventory.py` and an additive migration `backend/alembic/versions/20260826_bistro_inventory_allocations.py`. The table stores:

- workspace, job, inventory item, optional source location, and optional consumption ledger entry;
- `behavior`: `consumable` or `reusable`;
- `status`: `reserved`, `consumed`, `deployed`, `released`, or `returned`;
- planned and actual quantities plus reservation, fulfillment, and return timestamps;
- a unique `(job_id, item_id)` key and database checks for positive planned/nonnegative actual quantities and valid behavior/status values.

`backend/app/services/inventory/job_allocations.py` will own transitions and workspace authorization:

- reserve tracked fulfillment SKUs when an accepted quote is converted to a job, aggregating duplicate SKU lines;
- lock allocation and stock rows before completion;
- reject insufficient stock without partially completing the job;
- post consumable usage through `StockService.consume`, then mark the allocation consumed;
- mark reusable quantities deployed without reducing owned stock or adding COGS;
- release reservations when a job is canceled;
- return deployed reusable units through an explicit idempotent action;
- prevent deletion of a job while it has consumed/deployed inventory history or assets still out.

Available-to-promise quantity is `on_hand - reserved - deployed`. Consumable completion removes its reservation and reduces on-hand by actual usage; reusable completion removes its reservation and moves the actual quantity to deployed, keeping owned stock unchanged. The first version intentionally posts no depreciation COGS for reusable assets; a `simplification:` comment will name cycle-based amortization as the upgrade path.

## Completion API and UI

Add workspace-scoped routes in `backend/app/api/v1/jobs.py`:

- `GET /{job_id}/inventory-plan` returns planned/current allocation lines, behavior, status, stock position, and whether completion confirmation is required.
- `POST /{job_id}/complete-with-inventory` accepts actual quantities and optional source locations, then atomically posts inventory and completes the job.
- `POST /{job_id}/inventory-allocations/{allocation_id}/return` returns one deployed reusable allocation to available stock.

A direct `PATCH` to `status=completed` will fail closed when active allocations exist, forcing the atomic completion endpoint; jobs without allocations retain the current status flow. Retrying an identical completion or return is idempotent; a conflicting retry returns `409` rather than double-consuming stock.

In `frontend/src/components/jobs/job-detail-dialog.tsx`, selecting Completed for a job with allocations opens a focused completion dialog. `frontend/src/components/jobs/job-inventory-completion-dialog.tsx` will:

- prefill quote-planned feet/sets/poles;
- let the operator enter actual quantities and source locations;
- label permanent lines “Consume and post COGS” and temporary lines “Deploy — reusable”; and
- show shortages before the irreversible confirmation.

`job-materials-panel.tsx` will continue showing consumed permanent COGS and add a separate “Temporary Bistro equipment out” section with an idempotent Return action. Inventory lists, reorder reports, and the proposal availability card will show on-hand, reserved/deployed, and available-to-promise quantities so minimum-stock decisions use what can actually be promised.

## Files and contracts

Backend production paths:

- `backend/app/models/inventory.py`
- `backend/app/models/__init__.py`
- `backend/alembic/versions/20260826_bistro_inventory_allocations.py`
- `backend/app/schemas/inventory.py`
- `backend/app/schemas/pricing.py`
- `backend/app/schemas/proposal_wizard.py`
- `backend/app/services/inventory/job_allocations.py`
- `backend/app/services/inventory/__init__.py`
- `backend/app/services/inventory/inventory_service.py`
- `backend/app/services/inventory/quote_availability.py`
- `backend/app/services/inventory/reorder_service.py`
- `backend/app/services/jobs/job_service.py`
- `backend/app/services/quotes/proposal_builder.py`
- `backend/app/services/quotes/quote_service.py`
- `backend/app/api/v1/jobs.py`
- `backend/app/api/v1/settings.py`

Frontend production paths:

- `frontend/src/components/settings/bistro-pricing-settings-card.tsx`
- `frontend/src/components/estimator/inventory-availability-card.tsx`
- `frontend/src/components/inventory/inventory-list.tsx`
- `frontend/src/components/jobs/job-detail-dialog.tsx`
- `frontend/src/components/jobs/job-inventory-completion-dialog.tsx` (new)
- `frontend/src/components/jobs/job-materials-panel.tsx`
- `frontend/src/lib/api/jobs.ts`
- `frontend/src/lib/query-keys.ts`
- `frontend/src/types/inventory.ts`

Public route/schema changes require regeneration and commit of `backend/openapi.json` and `frontend/src/lib/api/_generated.ts` in the same commit.

## Integrity and security guards

- Every read/write filters `workspace_id`; cross-workspace item, job, location, or allocation IDs return the same tenant-safe 404.
- Quote conversion and completion use `TransactionalDB`, row locks, unique constraints, and idempotent terminal-state checks; no partial consumption can survive a failed completion.
- Physical stock never becomes negative, and an insufficient permanent or reusable quantity blocks completion with exact shortages.
- Existing jobs/quotes receive no backfill. New proposal snapshots without configured Bistro mappings continue pricing normally but clearly show inventory as not connected; no stock is invented.
- The migration only creates a new table and indexes; downgrade drops only that empty/new allocation structure. No existing inventory ledger rows are rewritten.
- Public proposal tests must prove fulfillment SKUs, quantities, behaviors, costs, reservations, and COGS remain absent from customer payloads.
- Reusable return changes allocation state only; it cannot create stock because owned on-hand was never reduced.

## Verification criteria

- Permanent quote example: 180 planned feet/4 poles reserves those quantities; completing with 165 feet/4 poles consumes only actual usage, snapshots weighted-average COGS, frees the 15-foot difference, and leaves the job completed.
- Temporary quote example: 250 feet/4 poles with 200-foot sets reserves 2 sets/4 poles; completion deploys them with zero material COGS; return restores available-to-promise without changing owned on-hand.
- Concurrent completion/reservation attempts cannot overdraw stock or create duplicate ledger/allocation rows.
- Canceling a reserved job releases availability; deleting a job with deployed assets or consumed history is blocked with an actionable response.
- Reorder and quote availability use on-hand minus reserved/deployed, while standard stock valuation remains owned on-hand times weighted-average cost.
- Unauthenticated and cross-workspace inventory-plan/completion/return requests expose no allocation, SKU, stock, or cost data.
- Targeted backend service/API tests, frontend component tests, OpenAPI codegen drift checks, migration up-check-down-up, Ruff/mypy, ESLint/typecheck/build, and the focused landscape-lighting Playwright workflow all pass.
- With local services and background workers disabled, `.ezcoder/eyes/http.sh` verifies inventory plan, permanent completion, temporary deployment/return, shortage 409 behavior, and workspace isolation; production remains untouched.

## Steps

1. Add the `InventoryJobAllocation` model, constraints, indexes, model exports, and reversible additive Alembic migration.
2. Extend pricing, fulfillment, availability, and inventory response schemas with Bistro SKU mappings, consumable/reusable behavior, allocation state, and available-to-promise fields while preserving public redaction.
3. Generate mapped Bistro fulfillment requirements from server-calculated permanent footage/poles and rounded temporary sets/poles, with focused pricing/builder/public-sanitization tests.
4. Implement the workspace-scoped allocation service for reservation, atomic actual-usage completion, cancellation release, reusable deployment/return, idempotency, concurrency locking, and deletion guards.
5. Reserve tracked quote requirements during accepted-quote job creation and update quote availability, inventory lists, and reorder reports to subtract reserved/deployed quantities.
6. Add inventory-plan, complete-with-inventory, and reusable-return job routes plus tenant, authorization, shortage, retry, and lifecycle API/service tests.
7. Add Bistro inventory item selectors and temporary set coverage to the pricing settings UI, including server validation and component tests.
8. Add the job completion confirmation dialog, route status completion through it when allocations exist, and show deployed temporary assets with Return actions in job materials.
9. Update proposal availability and inventory screens to distinguish owned, reserved, deployed, and available quantities, with focused frontend tests.
10. Regenerate `backend/openapi.json` and `frontend/src/lib/api/_generated.ts`, then update `docs/inventory-quoting-workflow.md` with the four aggregate Bistro units and permanent-versus-temporary lifecycle.
11. Run targeted backend/frontend tests, migration up-check-down-up, codegen drift checks, Ruff/mypy, ESLint/typecheck/build, and the focused Playwright Bistro workflow; fix every failure.
12. Exercise the local API with `.ezcoder/eyes/http.sh` for permanent consumption, temporary deployment/return, shortage, idempotent retry, and cross-workspace denial, then record counts and keep production untouched.
