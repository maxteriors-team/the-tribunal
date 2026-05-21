/** React Query hooks for CRM assistant chat. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useWorkspaceId } from "@/hooks/useWorkspaceId";
import { assistantApi } from "@/lib/api/assistant";
import { queryKeys } from "@/lib/query-keys";

export function useAssistantHistory() {
  const workspaceId = useWorkspaceId();

  return useQuery({
    queryKey: queryKeys.assistant.history(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return assistantApi.getHistory(workspaceId);
    },
    enabled: !!workspaceId,
    refetchOnWindowFocus: false,
  });
}

export function useAssistantConversations() {
  const workspaceId = useWorkspaceId();

  return useQuery({
    queryKey: queryKeys.assistant.conversations(workspaceId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      return assistantApi.listConversations(workspaceId);
    },
    enabled: !!workspaceId,
    refetchOnWindowFocus: false,
  });
}

export function useAssistantConversation(conversationId: string | null) {
  const workspaceId = useWorkspaceId();

  return useQuery({
    queryKey: queryKeys.assistant.conversation(workspaceId ?? "", conversationId ?? ""),
    queryFn: () => {
      if (!workspaceId) throw new Error("No workspace");
      if (!conversationId) throw new Error("No assistant conversation");
      return assistantApi.getConversation(workspaceId, conversationId);
    },
    enabled: !!workspaceId && !!conversationId,
    refetchOnWindowFocus: false,
  });
}

export function useDeleteAssistantConversation() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (conversationId: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return assistantApi.deleteConversation(workspaceId, conversationId);
    },
    onSuccess: (_data, conversationId) => {
      if (!workspaceId) return;
      queryClient.invalidateQueries({
        queryKey: queryKeys.assistant.conversations(workspaceId),
      });
      queryClient.removeQueries({
        queryKey: queryKeys.assistant.conversation(workspaceId, conversationId),
      });
      queryClient.invalidateQueries({
        queryKey: queryKeys.assistant.history(workspaceId),
      });
    },
  });
}

export function useAssistantChat() {
  const workspaceId = useWorkspaceId();
  const queryClient = useQueryClient();
  const historyKey = queryKeys.assistant.history(workspaceId ?? "");

  return useMutation({
    mutationFn: (message: string) => {
      if (!workspaceId) throw new Error("No workspace");
      return assistantApi.chat(workspaceId, message);
    },

    // Optimistically append the user message + a loading placeholder
    onMutate: async (message) => {
      await queryClient.cancelQueries({ queryKey: historyKey });

      const previous = queryClient.getQueryData(historyKey);

      queryClient.setQueryData(historyKey, (old: unknown) => {
        const conv = old as {
          id: string;
          messages: { id: string; role: string; content: string; created_at: string }[];
        } | null;
        if (!conv) {
          return {
            id: "temp",
            messages: [
              {
                id: "temp-user",
                role: "user",
                content: message,
                created_at: new Date().toISOString(),
              },
              {
                id: "temp-loading",
                role: "assistant",
                content: "…",
                created_at: new Date().toISOString(),
              },
            ],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };
        }
        return {
          ...conv,
          messages: [
            ...conv.messages,
            {
              id: "temp-user",
              role: "user",
              content: message,
              created_at: new Date().toISOString(),
            },
            {
              id: "temp-loading",
              role: "assistant",
              content: "…",
              created_at: new Date().toISOString(),
            },
          ],
        };
      });

      return { previous };
    },

    // On success, refetch real history from server
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: historyKey });
    },

    // On error, rollback optimistic update
    onError: (_err, _message, context) => {
      if (context?.previous) {
        queryClient.setQueryData(historyKey, context.previous);
      }
    },
  });
}
