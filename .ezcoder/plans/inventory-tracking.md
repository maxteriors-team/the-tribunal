# Inventory Tracking + Reorder Alerts + COGS

Net-new `inventory` domain in the backend, wired into the existing catalog, jobs,
nudges, and reporting surfaces, plus an `/inventory` dashboard screen.

## Researched approaches (and what we take from each)

**ERPNext** uses a dual-layer model: an immutable `Stock Ledger Entry` per movement
plus an aggregated `Bin` per item+warehouse for fast on-hand reads. It supports FIFO,
LIFO, Moving Average, and Standard Cost valuation. Backdated entries force a "repost"
that recomputes every later ledger row for that item/warehouse — slow and it mutates
stock values you considered settled.

**Odoo** splits `stock.quant` (how much of product X is at location Y) from
`stock.move` / `stock.move.line` (the movement events), with quants as the queryable
on-hand state and moves as the analytical history.

**Reorder point** is standard across NetSuite/MRPeasy/Fishbowl:
`ROP = (average daily usage × lead time days) + safety stock`.

### Decisions for this repo

1. **Dual-layer, same as both**: append-only `inventory_ledger_entries` (truth) +
   `inventory_stock_levels` (per item+location cache, rebuildable from the ledger).
   Every read of "what's on hand" hits the cache; every audit hits the ledger.
2. **Weighted-average cost (WAC), forward-only.** Simplest correct model for the
   trades this product serves (bulk chemicals, gutter guard, light strings — fungible,
   no lot identity). **No repost engine in v1**: a ledger row is never edited or
   deleted, and `occurred_at` is only metadata. Corrections are *new* adjustment
   entries. This deliberately trades "perfectly restated history after a backdated
   receipt" for "no background reposting job and no mutating settled costs" — the
   pain point called out in the ERPNext docs.
3. **Valuation method is a per-item column** (`valuation_method`, default
   `weighted_average`) so FIFO layers can be added later without a data migration,
   but only WAC is implemented now; any other value is rejected at write time.
4. **No purchase orders, suppliers-as-entities, serial/lot tracking, or barcode
   scanning in v1.** Items carry `supplier_name`, `supplier_sku`, and
   `lead_time_days` as plain fields — enough to compute a reorder point and tell an
   operator who to call.
5. **Reorder point is stored, not inferred.** The service *suggests* a value from
   trailing consumption + lead time, but never silently overwrites the operator's
   number.

## Integration with the existing CRM

- **Catalog (`catalog_items`)**: an `InventoryItem` optionally links to a catalog item
  via `catalog_item_id` (`ON DELETE SET NULL`). It is a *separate table*, not columns
  on `catalog_items`, because `CatalogService.delete_item` hard-deletes templates on
  the documented promise that documents snapshot their values — stock history must
  survive that. Uniqueness: partial unique index on
  `(workspace_id, catalog_item_id) WHERE catalog_item_id IS NOT NULL`.
- **Jobs (`field_service_jobs`)**: consuming stock on a job writes a ledger row with
  `reference_type='job'`, and the job's material cost flows into
  `JobCostingService.get_profitability` and `ReportingService.job_pnl_summary`.
- **Nudges**: low-stock alerts are a new `NudgeStrategy`, so they ride the existing
  hourly `nudge_worker`. **No new worker** — per CLAUDE.md every poll loop is
  duplicated by each backend replica, so adding loops is a real cost.
- **Reports**: new `GET /reports/cogs` next to `ar-aging` / `job-pnl`, gated on
  `reports:view` like its neighbors.

## Data model (`backend/app/models/inventory.py`)

**`inventory_locations`** — where stock physically sits.
`id, workspace_id (FK CASCADE), name, kind (warehouse|truck|other), crew_id (FK crews SET NULL, nullable), is_active, is_default, created_at, updated_at`.
Unique `(workspace_id, lower(name))`. Onboarding-free: the service lazily creates a
`"Main"` warehouse on first stock movement so an operator never has to configure
locations before receiving stock.

**`inventory_items`** — the tracked SKU.
`id, workspace_id, catalog_item_id (nullable FK SET NULL), name, sku, unit_of_measure (default "each"), is_active, valuation_method (default "weighted_average"), reorder_point Numeric(14,4) nullable, reorder_quantity Numeric(14,4) nullable, safety_stock Numeric(14,4) default 0, lead_time_days Integer nullable, supplier_name, supplier_sku, notes, created_by_id, created_at, updated_at`.
Indexes: `(workspace_id, is_active)`, partial unique `(workspace_id, sku) WHERE sku IS NOT NULL`.
`reorder_point IS NULL` means "not managed" — such items never raise alerts.

**`inventory_ledger_entries`** — append-only movement log (immutable).
`id, workspace_id, item_id (FK CASCADE), location_id (FK RESTRICT), quantity_delta Numeric(14,4) (signed), unit_cost Numeric(12,4), value_delta Numeric(14,2) (signed), reason (enum), reference_type (job|invoice|quote|manual|transfer, nullable), reference_id (UUID, nullable), occurred_at, note, created_by_id, created_at` plus post-state snapshot `quantity_after Numeric(14,4), value_after Numeric(14,2), unit_cost_after Numeric(12,4)`.
`reason` enum (`inventory_ledger_reason`, `create_type=False`, migration owns it):
`receipt, job_usage, sale, adjustment, shrinkage, return_to_stock, transfer_in, transfer_out, opening_balance`.
Indexes: `(workspace_id, item_id, created_at)`, `(workspace_id, reason, created_at)` for
COGS, `(workspace_id, reference_type, reference_id)` for job roll-ups, plus a partial
unique idempotency guard on `(workspace_id, reason, reference_type, reference_id, item_id) WHERE reference_id IS NOT NULL AND reason = 'job_usage'`.
Snapshotting `*_after` is what makes the COGS report a cheap scan and makes a
corrupted cache detectable (recompute vs. stored).

**`inventory_stock_levels`** — the Bin/quant cache.
`id, workspace_id, item_id, location_id, quantity_on_hand Numeric(14,4), total_value Numeric(14,2), avg_unit_cost Numeric(12,4), last_movement_at, updated_at`.
Unique `(workspace_id, item_id, location_id)`. Derived — never written except by the
posting engine.

Money in major units via `Numeric`, matching `invoice.py` / `job_costing.py`.

## Posting engine (`backend/app/services/inventory/stock_service.py`)

One private `_post(...)` used by every public verb, inside the caller's transaction:

1. `SELECT ... FOR UPDATE` the `inventory_stock_levels` row (insert-if-missing first,
   via `INSERT ... ON CONFLICT DO NOTHING`). The row lock is what makes two concurrent
   consumptions safe — without it both read the same WAC and one overwrites the other.
2. Compute new state:
   - **inbound** (`quantity_delta > 0`): `total_value += qty × unit_cost`;
     `avg_unit_cost = total_value / quantity_on_hand` (guard divide-by-zero → keep the
     prior cost rather than resetting to 0, the ERPNext bug called out in issue #1473).
   - **outbound**: `unit_cost = avg_unit_cost` (server-side, **never** from the client);
     `value_delta = -qty × avg_unit_cost`; `avg_unit_cost` unchanged.
3. Reject outbound beyond on-hand with `ConflictError` (409) unless
   `workspace.settings["inventory"]["allow_negative_stock"]` is true; when negative is
   allowed, cost at the last known `avg_unit_cost`.
4. Insert the ledger row with the post-state snapshot; update the level row.

Public verbs: `receive()`, `consume()`, `adjust()` (absolute count → signed delta,
`reason=adjustment`), `write_off()` (`reason=shrinkage`), `transfer()` (two rows,
`transfer_out` at source WAC then `transfer_in` at that same cost, one transaction).

## Reorder flagging (`reorder_service.py`)

- `low_stock(workspace_id)` → items where `SUM(quantity_on_hand) <= reorder_point` and
  `reorder_point IS NOT NULL` and `is_active`. Aggregated across locations (a truck
  being empty is not a reorder signal if the warehouse is full).
- `suggest_reorder_point(item)` → `avg_daily_usage × lead_time_days + safety_stock`,
  where `avg_daily_usage` comes from `job_usage`+`sale` ledger rows over a trailing
  90-day window. Returned as `suggested_reorder_point` alongside the stored value;
  applying it is an explicit operator action.
- Each row also returns `days_of_cover` (`on_hand / avg_daily_usage`) and
  `shortfall` (`reorder_point - on_hand`) so the UI can rank urgency.

## COGS reporting (`cogs_service.py` + `/reports/cogs`)

Sum `-value_delta` over ledger rows in the window where `reason IN ('job_usage','sale')`
— i.e. **cost recognized when stock is consumed**, valued at the WAC at posting time
(already snapshotted, so the report never recomputes history). Response:

- `total_cogs`, `currency`, `date_from/date_to`
- `shrinkage_cost` reported **separately** (`reason='shrinkage'`) so waste never hides
  inside gross margin
- breakdown by `group_by = item | service_category | job` (service category resolved
  through `catalog_items.service_category`, NULL → "uncategorized")
- `ending_inventory_value` = `SUM(total_value)` across stock levels, and
  `gross_margin` when the window's invoice revenue is available.

Currency: reuse the `_require_single_currency` guard pattern from
`reporting_service.py` (422 rather than a wrong sum).

**Double-count risk, handled explicitly:** `JobExpense` already has a free-form
`"materials"` category. `JobProfitability` gains a distinct `material_cost` field fed
only from the inventory ledger; consuming stock **does not** create a `JobExpense`, and
the job costing panel labels the two separately with a hint when both are non-zero.

## API surface

All under `/api/v1/workspaces/{workspace_id}/inventory` (`backend/app/api/v1/inventory.py`):

| Method | Path | Capability |
|---|---|---|
| GET/POST | `/items` | `jobs:read` / `billing:write` |
| GET/PUT/DELETE | `/items/{item_id}` | `jobs:read` / `billing:write` |
| GET | `/items/{item_id}/ledger` | `jobs:read` (costs redacted without `billing:read`) |
| POST | `/items/{item_id}/receipts` | `billing:write` |
| POST | `/items/{item_id}/adjustments` | `billing:write` |
| POST | `/transfers` | `jobs:write` |
| GET | `/stock` (`?low_stock=true&location_id=`) | `jobs:read` |
| GET | `/reorder-report` | `jobs:read` |
| GET/POST/PUT/DELETE | `/locations` | `jobs:read` / `billing:write` |

Job materials (added to `backend/app/api/v1/jobs.py`, next to time-entries/expenses):
`GET/POST/DELETE /workspaces/{ws}/jobs/{job_id}/materials` — `jobs:write` to post,
`jobs:read` to list. Deleting a consumption posts a compensating `return_to_stock`
row; it never deletes ledger history.

Reports: `GET /workspaces/{ws}/reports/cogs` — `reports:view`.

**Cost redaction** mirrors `JobCostingService`: reads take `include_costs`, derived at
the route from `billing:read`. Without it, quantities are served and every money field
is 0 — a field tech sees "3 buckets left on the truck", not what they cost. Client
`unit_cost` on outbound is always discarded, never trusted.

## Low-stock nudge

`backend/app/services/nudges/strategies/inventory_low_stock.py` — workspace-level
(`contact_id=None`), `nudge_type="inventory_low_stock"`, priority `high`,
`dedup_key = f"{workspace_id}:inventory_low_stock:{item_id}:{today}"` (per item per
day, matching `approvals_waiting`). Registered in
`strategies/__init__.py`, `ALL_NUDGE_TYPES`, and `_STRATEGY_REGISTRY` so existing
per-workspace nudge settings can disable it.

## Frontend

- `/inventory` route + `loading.tsx`; nav entry in
  `frontend/src/components/layout/app-nav.ts` (icon `Package`, `requires: "jobs:read"`).
- `frontend/src/components/inventory/`: `inventory-list.tsx` (on-hand table, low-stock
  badge, filter toggle), `inventory-item-dialog.tsx` (CRUD + reorder settings with the
  suggested ROP shown inline), `receive-stock-dialog.tsx`, `adjust-stock-dialog.tsx`,
  `item-ledger-sheet.tsx`, `low-stock-banner.tsx`.
- `frontend/src/components/jobs/job-materials-panel.tsx`, mounted in
  `job-detail-dialog.tsx` beside `job-costing-panel.tsx`.
- COGS card added to `frontend/src/components/reports/reports-overview.tsx`.
- `frontend/src/lib/api/inventory.ts` via the spec-typed `apiClient` (like
  `reportingApi.salesPerformance`), query keys added to `frontend/src/lib/query-keys.ts`,
  page states from `@/components/ui/page-state`.

## Risks / verification

- **Cache drift** between ledger and levels → service test that replays a random
  movement sequence and asserts `levels == SUM(ledger)`; the `*_after` snapshot makes
  drift detectable in prod.
- **Concurrency** → test two overlapping sessions consuming the same item; assert no
  lost update and no negative on-hand.
- **Tenant isolation** → every query through `app.db.scope`; cross-workspace
  `item_id`/`location_id` must 404, not 403.
- **Migration** is purely additive (new tables + one enum); it touches no contact/lead
  table, so the prod-dump rule in CLAUDE.md is not triggered — but `make ci.migrations`
  (up→check→down→up) must pass.
- **Contract drift** → `make codegen`, commit `backend/openapi.json` +
  `frontend/src/lib/api/_generated.ts` in the same commit as the routes.
- Runtime proof via `.ezcoder/eyes/http.sh` against the new endpoints and
  `.ezcoder/eyes/logs.sh --service backend --grep "nudge_worker|inventory|Traceback"`.

## Steps

1. Add `backend/app/models/inventory.py` with `InventoryLocation`, `InventoryItem`, `InventoryLedgerEntry`, `InventoryStockLevel`, the `inventory_ledger_reason` enum (`create_type=False`), and all indexes/constraints described above; export them from `backend/app/models/__init__.py`.
2. Create the Alembic migration with `make migrate.new m="add inventory tracking"`, hand-write the enum creation/drop plus the four tables and partial unique indexes, then run `make migrate` locally and verify `make ci.migrations` (up→check→down→up) passes.
3. Add `backend/app/schemas/inventory.py`: item/location create+update+response, ledger entry response, stock-level response, receipt/adjustment/transfer/consumption requests, low-stock row, and paginated wrappers — following `backend/app/schemas/catalog.py` conventions.
4. Implement `backend/app/services/inventory/stock_service.py` with the `_post()` engine (row-lock via `SELECT ... FOR UPDATE`, WAC math, negative-stock guard reading `workspace.settings["inventory"]["allow_negative_stock"]`, ledger insert with `quantity_after`/`value_after`/`unit_cost_after`) and the `receive`/`consume`/`adjust`/`write_off`/`transfer` verbs, all workspace-scoped through `app.db.scope`.
5. Implement `backend/app/services/inventory/inventory_service.py` (item + location CRUD, lazy default `"Main"` location, `catalog_item_id` validated inside the workspace) and `backend/app/services/inventory/__init__.py` exports.
6. Implement `backend/app/services/inventory/reorder_service.py` with `low_stock()` (aggregated across locations, skips `reorder_point IS NULL`) and `suggest_reorder_point()` (90-day trailing usage × `lead_time_days` + `safety_stock`), returning `shortfall` and `days_of_cover`.
7. Implement `backend/app/services/inventory/cogs_service.py`: window-scoped COGS from `job_usage`/`sale` ledger rows, separate `shrinkage_cost`, `group_by=item|service_category|job`, `ending_inventory_value`, and the single-currency guard.
8. Add `backend/app/api/v1/inventory.py` with the items/ledger/receipts/adjustments/transfers/stock/reorder-report/locations routes, capability gates as tabled above, and the `include_costs` redaction derived from `billing:read`; register it in `backend/app/api/v1/router.py` under `/workspaces/{workspace_id}/inventory` with tag `Inventory`.
9. Add `GET/POST/DELETE /workspaces/{ws}/jobs/{job_id}/materials` to `backend/app/api/v1/jobs.py` (delete posts a compensating `return_to_stock` row, never a hard delete) wired to `StockService.consume`.
10. Extend `JobProfitability` in `backend/app/schemas/job_costing.py` and `backend/app/services/jobs/costing_service.py` with a `material_cost` field sourced from the inventory ledger, included in `total_cost` and kept distinct from `JobExpense` "materials".
11. Extend `backend/app/services/reporting/reporting_service.py` `job_pnl_summary` with the same `material_cost`, add `COGSReport` schemas to `backend/app/schemas/reporting.py`, and add `GET /reports/cogs` to `backend/app/api/v1/reporting.py` gated on `CanViewReports`.
12. Add `backend/app/services/nudges/strategies/inventory_low_stock.py` and register it in `strategies/__init__.py`, `ALL_NUDGE_TYPES`, and `_STRATEGY_REGISTRY` in `backend/app/services/nudges/nudge_generator.py`.
13. Write backend tests: `backend/tests/services/inventory/` (WAC math incl. zero-qty cost retention, negative-stock guard, ledger↔levels reconciliation, concurrent consumption, reorder flagging + suggestion, COGS grouping and shrinkage split, tenant isolation) and `backend/tests/api/` (capability gates, cost redaction without `billing:read`, job materials round-trip).
14. Run `make codegen` and commit `backend/openapi.json` + `frontend/src/lib/api/_generated.ts`, then add `frontend/src/lib/api/inventory.ts` using the spec-typed `apiClient` and inventory keys in `frontend/src/lib/query-keys.ts`.
15. Build the `/inventory` screen: `frontend/src/app/inventory/page.tsx` + `loading.tsx`, the `frontend/src/components/inventory/` components (list with low-stock badge, item dialog with suggested ROP, receive/adjust dialogs, ledger sheet), and the nav entry in `frontend/src/components/layout/app-nav.ts`.
16. Add `frontend/src/components/jobs/job-materials-panel.tsx`, mount it in `job-detail-dialog.tsx`, surface `material_cost` in `job-costing-panel.tsx`, and add the COGS card to `frontend/src/components/reports/reports-overview.tsx`; cover the new components with tests matching the existing `*.test.tsx` patterns.
17. Verify at runtime with the local stack: `.ezcoder/eyes/http.sh` against `/inventory/items`, `/inventory/stock?low_stock=true`, a job materials POST, and `/reports/cogs`; then `.ezcoder/eyes/logs.sh --service backend --grep "inventory|nudge_worker|Traceback"`.
18. Run `make ci.all` and fix everything it reports until it exits 0.
