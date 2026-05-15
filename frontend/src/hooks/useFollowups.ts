import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";

/**
 * Fetch follow-up settings for a conversation
 */
export function useFollowupSettings(workspaceId: string, conversationId: string) {
  return useQuery({
    queryKey: queryKeys.conversations.followupSettings(workspaceId, conversationId),
    queryFn: () => conversationsApi.getFollowupSettings(workspaceId, conversationId),
    enabled: !!workspaceId && !!conversationId,
    refetchInterval: 30000, // Refresh every 30 seconds to update next_followup_at
  });
}

/**
 * Update follow-up settings for a conversation
 */
export function useUpdateFollowupSettings(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      conversationId: string;
      settings: Partial<{
        enabled: boolean;
        delay_hours: number;
        max_count: number;
      }>;
    }) => conversationsApi.updateFollowupSettings(workspaceId, data.conversationId, data.settings),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.followupSettings(workspaceId, variables.conversationId),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.detailAll() });
    },
  });
}

/**
 * Generate a follow-up message (preview, not send)
 */
export function useGenerateFollowup(workspaceId: string) {
  return useMutation({
    mutationFn: (data: { conversationId: string; customInstructions?: string }) =>
      conversationsApi.generateFollowup(
        workspaceId,
        data.conversationId,
        data.customInstructions
      ),
  });
}

/**
 * Send a follow-up message
 */
export function useSendFollowup(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: {
      conversationId: string;
      message?: string;
      customInstructions?: string;
    }) =>
      conversationsApi.sendFollowup(
        workspaceId,
        data.conversationId,
        data.message,
        data.customInstructions
      ),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.followupSettings(workspaceId, variables.conversationId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.detail(workspaceId, variables.conversationId),
      });
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.bare(workspaceId) });
    },
  });
}

/**
 * Reset follow-up counter for a conversation
 */
export function useResetFollowupCounter(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (conversationId: string) =>
      conversationsApi.resetFollowupCounter(workspaceId, conversationId),
    onSuccess: (_, conversationId) => {
      queryClient.invalidateQueries({
        queryKey: queryKeys.conversations.followupSettings(workspaceId, conversationId),
      });
    },
  });
}
