import { useQuery } from "@tanstack/react-query";

import { dashboardApi, type DashboardResponse } from "@/lib/api/dashboard";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";

/**
 * Fetch dashboard statistics for a workspace
 */
export function useDashboard(workspaceId: string) {
  return useQuery<DashboardResponse>({
    queryKey: queryKeys.dashboard.all(workspaceId),
    queryFn: () => dashboardApi.getStats(workspaceId),
    enabled: !!workspaceId,
    ...REALTIME,
    // Keep previous data while refetching
    placeholderData: (previousData) => previousData,
  });
}
