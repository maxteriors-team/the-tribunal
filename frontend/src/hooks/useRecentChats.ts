import { useQuery } from "@tanstack/react-query";

import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";

export const RECENT_CHATS_LIMIT = 12;
export const RECENT_CHATS_PARAMS = {
  page: 1,
  page_size: RECENT_CHATS_LIMIT,
} as const;

/**
 * Shared query definition for the freshest conversation threads, ordered
 * newest-first by the API.
 *
 * Exported so the notifier can `fetchQuery` the exact same key the menu reads
 * from: an on-demand fetch warms the menu's cache rather than racing it.
 */
export function recentChatsQueryOptions(workspaceId: string) {
  return {
    queryKey: queryKeys.conversations.list(workspaceId, RECENT_CHATS_PARAMS),
    queryFn: () => conversationsApi.list(workspaceId, RECENT_CHATS_PARAMS),
  };
}

/**
 * The freshest conversation threads.
 *
 * Deliberately not polled: this list is only needed once the operator opens the
 * chat menu, and polling it would put a request on every page for every
 * operator. The unread badge polls a cheap aggregate instead, and the notifier
 * fetches this list only when that aggregate says something actually arrived.
 */
export function useRecentChats(
  workspaceId: string | null | undefined,
  { enabled = true }: { enabled?: boolean } = {},
) {
  return useQuery({
    ...recentChatsQueryOptions(workspaceId ?? ""),
    enabled: enabled && !!workspaceId,
  });
}
