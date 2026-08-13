import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { conversationsApi } from "@/lib/api/conversations";
import type { ApiClient } from "@/lib/api/create-api-client";
import { createResourceHooks } from "@/lib/api/create-resource-hooks";
import { queryKeys } from "@/lib/query-keys";
import { POLL_15S } from "@/lib/query-options";
import type { Conversation } from "@/types";

export type { ConversationsListParams } from "@/lib/api/conversations";

// Standard list/get operations via the resource hooks factory
const {
  queryKeys: conversationQueryKeys,
  useList: useConversations,
  useGet: useConversation,
} = createResourceHooks<Conversation, never, never>({
  resourceKey: "conversations",
  apiClient: conversationsApi as ApiClient<Conversation, never, never>,
  includeCreate: false,
  includeUpdate: false,
  includeDelete: false,
});

export { conversationQueryKeys, useConversations, useConversation };

/**
 * Send a message in a conversation
 */
export function useSendMessage(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { conversationId: string; body: string }) =>
      conversationsApi.sendMessage(workspaceId, data.conversationId, data.body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all(workspaceId) });
    },
  });
}

/**
 * Workspace-wide unread rollup, polled for the header chat badge.
 *
 * Deliberately its own endpoint rather than summing a conversations page: the
 * badge renders on every screen, and a page only sees the threads it fetched.
 */
export function useUnreadSummary(workspaceId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.conversations.unreadSummary(workspaceId ?? ""),
    queryFn: () => conversationsApi.getUnreadSummary(workspaceId!),
    enabled: !!workspaceId,
    ...POLL_15S,
  });
}

/**
 * Mark a single conversation as read.
 *
 * Patches the unread badge to 0 immediately so the count doesn't linger for a
 * poll cycle, then reconciles against the server.
 */
export function useMarkConversationRead(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (conversationId: string) =>
      conversationsApi.markRead(workspaceId, conversationId),
    onSuccess: (updated) => {
      queryClient.setQueriesData<{ items: Conversation[] } | undefined>(
        { queryKey: queryKeys.conversations.all(workspaceId) },
        (previous) => {
          if (!previous?.items) return previous;
          return {
            ...previous,
            items: previous.items.map((conversation) =>
              conversation.id === updated.id
                ? { ...conversation, unread_count: 0 }
                : conversation,
            ),
          };
        },
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.all(workspaceId),
      });
    },
  });
}

/**
 * Mark every conversation in the workspace as read.
 */
export function useMarkAllConversationsRead(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => conversationsApi.markAllRead(workspaceId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.all(workspaceId),
      });
    },
  });
}

/**
 * Toggle AI for a conversation
 */
export function useToggleConversationAI(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { conversationId: string; enabled: boolean }) =>
      conversationsApi.toggleAI(workspaceId, data.conversationId, data.enabled),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all(workspaceId) });
    },
  });
}

/**
 * Assign an agent to a conversation
 */
export function useAssignAgent(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { conversationId: string; agentId: string | null }) =>
      conversationsApi.assignAgent(workspaceId, data.conversationId, data.agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all(workspaceId) });
    },
  });
}

/**
 * Clear conversation history (delete all messages)
 */
export function useClearConversationHistory(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (conversationId: string) =>
      conversationsApi.clearHistory(workspaceId, conversationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.all(workspaceId) });
    },
  });
}
