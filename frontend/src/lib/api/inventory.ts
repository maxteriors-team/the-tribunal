import { apiClient } from "@/lib/api/_client";
import type {
  AdjustStockRequest,
  InventoryItem,
  InventoryItemCreate,
  InventoryItemUpdate,
  InventoryLedgerEntry,
  InventoryLedgerPage,
  InventoryLocation,
  InventoryLocationCreate,
  InventoryLocationUpdate,
  JobMaterialCreate,
  JobMaterials,
  PaginatedInventoryItems,
  ReceiveStockRequest,
  ReorderReport,
  ReorderSuggestion,
  StockLevelList,
  TransferStockRequest,
} from "@/types/inventory";

/**
 * Inventory API, routed through the spec-typed `apiClient` so every path,
 * query param, and response is checked against `_generated.ts` rather than
 * re-declared here (same approach as `reportingApi.salesPerformance`).
 *
 * Cost fields come back as `0` for callers without `billing:read` — the
 * backend redacts them rather than omitting them, so the shapes below are the
 * same for every tier and the UI decides whether to show a money column.
 */
export const inventoryApi = {
  listItems: (
    workspaceId: string,
    params: {
      search?: string;
      low_stock?: boolean;
      include_inactive?: boolean;
      page?: number;
      page_size?: number;
    } = {},
  ): Promise<PaginatedInventoryItems> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/inventory/items", {
      path: { workspace_id: workspaceId },
      query: params,
    }),

  getItem: (workspaceId: string, itemId: string): Promise<InventoryItem> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}", {
      path: { workspace_id: workspaceId, item_id: itemId },
    }),

  createItem: (
    workspaceId: string,
    body: InventoryItemCreate,
  ): Promise<InventoryItem> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/inventory/items", {
      path: { workspace_id: workspaceId },
      body,
    }),

  updateItem: (
    workspaceId: string,
    itemId: string,
    body: InventoryItemUpdate,
  ): Promise<InventoryItem> =>
    apiClient.put("/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}", {
      path: { workspace_id: workspaceId, item_id: itemId },
      body,
    }),

  deleteItem: (workspaceId: string, itemId: string): Promise<void> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}", {
      path: { workspace_id: workspaceId, item_id: itemId },
    }),

  listLedger: (
    workspaceId: string,
    itemId: string,
    params: { page?: number; page_size?: number } = {},
  ): Promise<InventoryLedgerPage> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}/ledger", {
      path: { workspace_id: workspaceId, item_id: itemId },
      query: params,
    }),

  /** Suggested reorder point from trailing usage. Applying it stays manual. */
  reorderSuggestion: (
    workspaceId: string,
    itemId: string,
  ): Promise<ReorderSuggestion> =>
    apiClient.get(
      "/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}/reorder-suggestion",
      { path: { workspace_id: workspaceId, item_id: itemId } },
    ),

  receive: (
    workspaceId: string,
    itemId: string,
    body: ReceiveStockRequest,
  ): Promise<InventoryLedgerEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}/receipts", {
      path: { workspace_id: workspaceId, item_id: itemId },
      body,
    }),

  adjust: (
    workspaceId: string,
    itemId: string,
    body: AdjustStockRequest,
  ): Promise<InventoryLedgerEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/inventory/items/{item_id}/adjustments", {
      path: { workspace_id: workspaceId, item_id: itemId },
      body,
    }),

  transfer: (
    workspaceId: string,
    body: TransferStockRequest,
  ): Promise<InventoryLedgerEntry[]> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/inventory/transfers", {
      path: { workspace_id: workspaceId },
      body,
    }),

  listStock: (
    workspaceId: string,
    params: { location_id?: string; low_stock?: boolean } = {},
  ): Promise<StockLevelList> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/inventory/stock", {
      path: { workspace_id: workspaceId },
      query: params,
    }),

  reorderReport: (
    workspaceId: string,
    params: { lookback_days?: number } = {},
  ): Promise<ReorderReport> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/inventory/reorder-report", {
      path: { workspace_id: workspaceId },
      query: params,
    }),

  listLocations: (
    workspaceId: string,
    params: { include_inactive?: boolean } = {},
  ): Promise<InventoryLocation[]> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/inventory/locations", {
      path: { workspace_id: workspaceId },
      query: params,
    }),

  createLocation: (
    workspaceId: string,
    body: InventoryLocationCreate,
  ): Promise<InventoryLocation> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/inventory/locations", {
      path: { workspace_id: workspaceId },
      body,
    }),

  updateLocation: (
    workspaceId: string,
    locationId: string,
    body: InventoryLocationUpdate,
  ): Promise<InventoryLocation> =>
    apiClient.put("/api/v1/workspaces/{workspace_id}/inventory/locations/{location_id}", {
      path: { workspace_id: workspaceId, location_id: locationId },
      body,
    }),

  deleteLocation: (workspaceId: string, locationId: string): Promise<void> =>
    apiClient.del("/api/v1/workspaces/{workspace_id}/inventory/locations/{location_id}", {
      path: { workspace_id: workspaceId, location_id: locationId },
    }),

  // Job materials live under /jobs but are inventory movements, so they are
  // grouped with the rest of the ledger surface rather than in `jobsApi`.
  listJobMaterials: (workspaceId: string, jobId: string): Promise<JobMaterials> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/materials", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  addJobMaterial: (
    workspaceId: string,
    jobId: string,
    body: JobMaterialCreate,
  ): Promise<InventoryLedgerEntry> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/jobs/{job_id}/materials", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  /** Undo a material line. Posts a return to stock; never deletes history. */
  removeJobMaterial: (
    workspaceId: string,
    jobId: string,
    entryId: string,
  ): Promise<InventoryLedgerEntry> =>
    apiClient.del(
      "/api/v1/workspaces/{workspace_id}/jobs/{job_id}/materials/{entry_id}",
      { path: { workspace_id: workspaceId, job_id: jobId, entry_id: entryId } },
    ),
};
