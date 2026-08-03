// Inventory types. Sourced from the generated OpenAPI schema rather than
// hand-written, so the redaction contract stays in lockstep with the backend:
// every money field is present but served as `0` for callers without
// `billing:read`, and `reorder_point: null` means "not managed" (never alerts).

import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

export type InventoryItem = Schemas["InventoryItemResponse"];
export type InventoryItemCreate = Schemas["InventoryItemCreate"];
export type InventoryItemUpdate = Schemas["InventoryItemUpdate"];
export type PaginatedInventoryItems = Schemas["PaginatedInventoryItems"];

export type InventoryLocation = Schemas["InventoryLocationResponse"];
export type InventoryLocationCreate = Schemas["InventoryLocationCreate"];
export type InventoryLocationUpdate = Schemas["InventoryLocationUpdate"];
export type InventoryLocationKind = InventoryLocation["kind"];

export type InventoryLedgerEntry = Schemas["InventoryLedgerEntryResponse"];
export type InventoryLedgerPage = Schemas["InventoryLedgerPage"];
export type InventoryLedgerReason = InventoryLedgerEntry["reason"];

export type ReceiveStockRequest = Schemas["ReceiveStockRequest"];
export type AdjustStockRequest = Schemas["AdjustStockRequest"];
export type TransferStockRequest = Schemas["TransferStockRequest"];

export type StockLevelRow = Schemas["StockLevelRow"];
export type StockLevelList = Schemas["StockLevelListResponse"];

export type ReorderRow = Schemas["ReorderRow"];
export type ReorderReport = Schemas["ReorderReport"];
export type ReorderSuggestion = Schemas["ReorderSuggestion"];

export type JobMaterialCreate = Schemas["JobMaterialCreate"];
export type JobMaterials = Schemas["JobMaterialsResponse"];

export type COGSReport = Schemas["COGSReport"];
export type COGSBreakdownRow = Schemas["COGSBreakdownRow"];
export type COGSGroupBy = COGSReport["group_by"];

/** Human labels for ledger reasons, shared by the ledger sheet and job panel. */
export const LEDGER_REASON_LABELS: Record<InventoryLedgerReason, string> = {
  receipt: "Received",
  job_usage: "Used on job",
  sale: "Sold",
  adjustment: "Count adjustment",
  shrinkage: "Written off",
  return_to_stock: "Returned",
  transfer_in: "Transferred in",
  transfer_out: "Transferred out",
  opening_balance: "Opening balance",
};
