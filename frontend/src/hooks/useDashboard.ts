import { useQuery } from "@tanstack/react-query";
import { dashboardApi, type DashboardResponse } from "@/lib/api/dashboard";
import { queryKeys } from "@/lib/query-keys";

/**
 * Fetch dashboard statistics for a workspace
 */
export function useDashboard(workspaceId: string) {
  return useQuery<DashboardResponse>({
    queryKey: queryKeys.dashboard.all(workspaceId),
    queryFn: () => dashboardApi.getStats(workspaceId),
    enabled: !!workspaceId,
    // Refetch every 30 seconds to keep data fresh
    refetchInterval: 30000,
    // Keep previous data while refetching
    placeholderData: (previousData) => previousData,
  });
}
