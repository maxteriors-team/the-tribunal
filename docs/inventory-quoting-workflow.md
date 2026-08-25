# Inventory and quoting workflow

## Source of truth

Tribunal's inventory ledger is the stock source of truth. The intake workbook and
Google Sheets CSVs are import/count tools only; they are not synchronized stock
systems.

Catalog package components and inventory items meet on exact workspace-scoped
SKUs. A quote's selected package already produces an internal fulfillment list,
so quote preview/save now compares each required SKU with the sum on hand across
that workspace's active inventory locations.

## What the quote shows internally

- **In stock** — counted on-hand quantity covers the selected package.
- **Short** — shows required, on hand, and confirmed shortfall.
- **Not counted** — the SKU is tracked but has no opening stock count yet.
- **Not tracked** — the package component SKU is not linked to an active inventory item.

The availability block is staff-only. It and supplier SKUs are stripped from the
public proposal payload.

Quote creation snapshots this check for auditability but does not reserve or
consume stock. Inventory moves only through the append-only ledger when materials
are received, counted/adjusted, issued to accepted work, returned, or written off.
This avoids reducing stock for drafts customers may never approve. If concurrent
accepted jobs later require guaranteed allocation, add a reservation ledger rather
than overloading on-hand quantity.

## Accounting for current physical inventory

1. Review and approve the unresolved rows in the inventory reconciliation manifest.
2. Import verified catalog/inventory rows with zero opening quantity and cost.
3. Perform a physical count by location in **CRM → Inventory → Count / write off**;
   the resulting opening-balance/adjustment ledger entries establish current stock.
4. Confirm every quote component reports **In stock**, **Short**, or **Not counted**;
   resolve **Not tracked** rows by matching the package component and inventory SKU.
5. Record every receipt and job issue in Tribunal, then review low-stock items weekly.

Never treat supplier order quantities or workbook rows as current on-hand stock.
