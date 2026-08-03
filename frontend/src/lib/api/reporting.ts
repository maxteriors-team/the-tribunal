import api from "@/lib/api";
import { apiClient } from "@/lib/api/_client";
import type {
  ARAgingReport,
  AttributionGapReport,
  COGSGroupBy,
  COGSReport,
  JobPnLSummary,
  SalesPerformanceReport,
} from "@/types";

// Read-only reporting roll-ups (not CRUD), so a small hand-written client.
export const reportingApi = {
  arAging: async (
    workspaceId: string,
    params: { as_of?: string } = {}
  ): Promise<ARAgingReport> => {
    const response = await api.get(
      `/api/v1/workspaces/${workspaceId}/reports/ar-aging`,
      { params }
    );
    return response.data as ARAgingReport;
  },

  jobPnl: async (
    workspaceId: string,
    params: { date_from?: string; date_to?: string } = {}
  ): Promise<JobPnLSummary> => {
    const response = await api.get(
      `/api/v1/workspaces/${workspaceId}/reports/job-pnl`,
      { params }
    );
    return response.data as JobPnLSummary;
  },

  attributionGap: (
    workspaceId: string,
    params: { date_from?: string; date_to?: string } = {},
  ): Promise<AttributionGapReport> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/reports/attribution-gap", {
      path: { workspace_id: workspaceId },
      query: params,
    }),

  // Goes through the spec-typed client so the params and the response are both
  // checked against `_generated.ts` instead of re-declared by hand here.
  salesPerformance: (
    workspaceId: string,
    params: { date_from?: string; date_to?: string } = {}
  ): Promise<SalesPerformanceReport> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/reports/sales-performance", {
      path: { workspace_id: workspaceId },
      query: params,
    }),

  // Cost of goods sold from the inventory ledger. Shrinkage comes back on its
  // own field, deliberately outside `total_cogs`.
  cogs: (
    workspaceId: string,
    params: { date_from?: string; date_to?: string; group_by?: COGSGroupBy } = {}
  ): Promise<COGSReport> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/reports/cogs", {
      path: { workspace_id: workspaceId },
      query: params,
    }),
};
