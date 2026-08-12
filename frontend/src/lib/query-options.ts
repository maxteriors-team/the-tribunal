/**
 * Shared React Query option presets.
 *
 * Spread these into `useQuery` options to get consistent polling/staleness
 * behavior across the app instead of hand-tuning numbers per call site.
 *
 * @example
 * ```ts
 * import { POLL_30S } from "@/lib/query-options";
 * import { queryKeys } from "@/lib/query-keys";
 *
 * useQuery({
 *   queryKey: queryKeys.pendingActions.count(workspaceId),
 *   queryFn: () => fetchPendingCount(workspaceId),
 *   ...POLL_30S,
 * });
 * ```
 *
 * NOTE: migration of inline keys is incremental — see follow-up PRs. New code
 * should prefer these presets; existing components will be migrated over time.
 */

export const REALTIME = {
  staleTime: 0,
  refetchInterval: 5_000,
} as const;

export const POLL_15S = {
  staleTime: 10_000,
  refetchInterval: 15_000,
} as const;

export const POLL_30S = {
  staleTime: 25_000,
  refetchInterval: 30_000,
} as const;

export const POLL_60S = {
  staleTime: 50_000,
  refetchInterval: 60_000,
} as const;

export const STATIC = {
  staleTime: 5 * 60_000,
  gcTime: 10 * 60_000,
} as const;
