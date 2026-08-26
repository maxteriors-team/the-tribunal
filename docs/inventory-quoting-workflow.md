# Inventory quoting workflow

Tribunal's append-only inventory ledger is the stock source of truth. Intake workbooks and Google Sheets CSVs are import/count tools only; they are not synchronized stock systems.

Catalog fulfillment components and inventory items meet on exact workspace-scoped SKUs. Availability and fulfillment data are staff-only: customer proposal payloads never include supplier SKUs, costs, reservations, deployments, availability, or COGS.

## Bistro aggregate inventory units

Create and physically count these workspace inventory items before mapping them in **Settings → Bistro pricing**. They are operator-managed business data and are not seeded automatically.

| Recommended SKU | Unit | Lifecycle | Cost basis |
|---|---:|---|---|
| `BISTRO-PERM-FT` | `ft` | Consumable permanent installed footage | Weighted-average installable cost per foot |
| `BISTRO-PERM-POLE` | `each` | Consumable permanent pole/support | Weighted-average cost per pole |
| `BISTRO-TEMP-200FT` | `set` | Reusable temporary light set | Owned asset cost; no job COGS in v1 |
| `BISTRO-TEMP-POLE` | `each` | Reusable temporary pole/support | Owned asset cost; no job COGS in v1 |

The permanent-foot receipt cost should blend the socket line, bulbs, support cable, connectors, and a normal small-parts allowance. Tiny components stay outside CRM. Receive permanent footage in installable feet, not package or reel counts.

Set **Feet covered by one temporary set** to the actual stocked set size (normally `200`). Permanent footage is always one stock unit per measured foot.

A SKU may not be mapped to both permanent consumable stock and temporary reusable equipment. The settings API accepts only active inventory SKUs from the same workspace.

## Quote and reservation lifecycle

1. The server measures grouped permanent/temporary Bistro runs and counts their marked anchors as poles/supports.
2. Private fulfillment requirements use exact permanent feet, permanent pole count, `ceil(temporary feet / set coverage)` temporary sets, and temporary pole count.
3. Quote availability shows **owned**, **reserved**, **deployed**, and **available to promise**. Available to promise is `owned on hand - reserved - deployed`.
4. Converting an accepted quote into a job reserves every mapped active SKU in the same transaction. A shortage blocks conversion; no partial reservation or job conversion is committed.
5. Canceling a reserved job releases its promise. Existing quotes/jobs are not backfilled, and a quote without mappings continues pricing with inventory clearly marked not connected.

Christmas inventory and its kit/COGS behavior are unchanged.

## Completing a Bistro job

Selecting **Completed** on a job with active allocations opens inventory confirmation instead of patching the status directly. The operator confirms actual quantity and an optional source location for every line.

The completion transaction locks job, allocation, and stock rows before writing anything. Any global or source-location shortage returns `409` with exact shortage quantities and leaves the job, stock, ledger, and allocations unchanged.

### Permanent work

- Actual permanent footage/poles are consumed from physical on-hand stock.
- The immutable inventory ledger snapshots current weighted-average unit cost as job COGS.
- Unused planned quantity is released automatically.
- Example: reserve `180 ft / 4 poles`; confirm `165 ft / 4 poles`; consume only `165 / 4` and free the remaining `15 ft` promise.

Correct a posting mistake with a job-material return entry. Do not delete ledger history.

### Temporary work

- Actual temporary sets/poles move from **reserved** to **deployed**.
- Owned on-hand quantity and stock valuation do not change.
- No purchase price or depreciation COGS posts to the job in v1.
- The job materials panel lists **Temporary Bistro equipment out** until each allocation is returned.
- Return changes only allocation state from **deployed** to **returned**, restoring available-to-promise without creating stock.

A future cycle-based amortization ledger can add per-deployment cost without changing owned-stock behavior.

## Retry, deletion, and audit rules

- Repeating the same completion or reusable return is idempotent; conflicting completion quantities return `409`.
- Concurrent reservations/completions serialize on stock rows, so they cannot overpromise or consume the same availability twice.
- Jobs with consumed inventory history or equipment still deployed cannot be deleted. Return reusable equipment first; consumed ledger history remains attached permanently.
- Every route and service query is scoped by `workspace_id`; foreign workspace job, allocation, item, or location identifiers return tenant-safe not-found responses.

## Accounting for current physical inventory

1. Import verified catalog/inventory rows with zero opening quantity and cost.
2. Perform a physical count by location in **CRM → Inventory → Count / write off**; the resulting opening-balance/adjustment entries establish current stock.
3. Resolve **Not tracked** quote rows by matching the fulfillment and active inventory SKU; resolve **Not counted** with an opening count.
4. Record every receipt and job completion in Tribunal, then review available-to-promise low-stock items weekly.

Never treat supplier order quantities or workbook rows as current on-hand stock.
