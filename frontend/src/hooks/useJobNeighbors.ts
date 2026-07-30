import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  jobsApi,
  type NeighborBatch,
  type NeighborCampaignRequest,
  type NeighborEntryUpdate,
  type NeighborGenerateRequest,
} from "@/lib/api/jobs";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorStatus } from "@/lib/utils/errors";

/**
 * A job's neighbour list.
 *
 * The endpoint 404s until a list has been generated, which is a normal state —
 * not an error worth retrying or surfacing as a failure. `retry` therefore stops
 * dead on a 404 so the panel renders its "generate" empty state immediately,
 * instead of spending React Query's default three backoff rounds re-asking a
 * question the server already answered. Other failures get one retry.
 */
export function useJobNeighbors(workspaceId: string, jobId: string, enabled = true) {
  return useQuery<NeighborBatch>({
    queryKey: queryKeys.jobs.neighbors(workspaceId, jobId),
    queryFn: () => jobsApi.neighbors(workspaceId, jobId),
    enabled: enabled && Boolean(workspaceId && jobId),
    retry: (failureCount, error) =>
      getApiErrorStatus(error) !== 404 && failureCount < 1,
  });
}

function useNeighborInvalidation(workspaceId: string, jobId: string) {
  const queryClient = useQueryClient();
  return () =>
    void queryClient.invalidateQueries({
      queryKey: queryKeys.jobs.neighbors(workspaceId, jobId),
    });
}

/** Generate or top up the list. Safe to call repeatedly — the API is idempotent. */
export function useGenerateNeighbors(workspaceId: string, jobId: string) {
  const invalidate = useNeighborInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (body: NeighborGenerateRequest = {}) =>
      jobsApi.generateNeighbors(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}

export function useUpdateNeighborEntry(workspaceId: string, jobId: string) {
  const invalidate = useNeighborInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: string; body: NeighborEntryUpdate }) =>
      jobsApi.updateNeighborEntry(workspaceId, jobId, entryId, body),
    onSuccess: invalidate,
  });
}

export function useEnrollNeighbors(workspaceId: string, jobId: string) {
  const invalidate = useNeighborInvalidation(workspaceId, jobId);
  return useMutation({
    mutationFn: (body: NeighborCampaignRequest) =>
      jobsApi.enrollNeighbors(workspaceId, jobId, body),
    onSuccess: invalidate,
  });
}
