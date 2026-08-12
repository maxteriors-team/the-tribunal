import { useQuery } from "@tanstack/react-query";

import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";
import { POLL_15S } from "@/lib/query-options";

export const RECENT_CHATS_LIMIT = 12;
export const RECENT_CHATS_PARAMS = {
  page: 1,
  page_size: RECENT_CHATS_LIMIT,
} as const;

/**
 * The freshest conversation threads, ordered newest-first by the API.
 *
 * Both the header chat menu and the new-message notifier call this with the
 * same params, so React Query dedupes them into a single polled request: the
 * notifier keeps it warm, and opening the menu renders already-fetched data
 * instead of a spinner.
 */
export function useRecentChats(workspaceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.conversations.list(workspaceId ?? "", RECENT_CHATS_PARAMS),
    queryFn: () => conversationsApi.list(workspaceId!, RECENT_CHATS_PARAMS),
    enabled: !!workspaceId,
    ...POLL_15S,
  });
}
