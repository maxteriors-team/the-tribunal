import api from "@/lib/api";
import type { ARAgingReport, JobPnLSummary } from "@/types";

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
};
