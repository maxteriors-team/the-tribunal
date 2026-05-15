import { useMutation, useQueryClient } from "@tanstack/react-query";
import { createResourceHooks } from "@/lib/api/create-resource-hooks";
import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";
import type { Conversation } from "@/types";
import type { ApiClient } from "@/lib/api/create-api-client";

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
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.bare(workspaceId) });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.bare(workspaceId) });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.bare(workspaceId) });
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
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.bare(workspaceId) });
    },
  });
}
