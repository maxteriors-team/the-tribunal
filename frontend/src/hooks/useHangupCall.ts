"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { callsApi } from "@/lib/api/calls";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

interface UseHangupCallOptions {
  workspaceId: string | null | undefined;
  /** Called with the dropped call's id after the backend confirms the hangup. */
  onSuccess?: (callId: string) => void;
}

/**
 * Shared "drop this call" mutation for every live-call surface.
 *
 * The backend has always exposed `POST /calls/{id}/hangup`, but no UI called
 * it — an operator watching a live call had no way to end it and had to wait
 * for the far end to hang up. Every surface that shows an in-progress call
 * routes through this hook so the roster and the supervisor panel cannot drift
 * apart on the invalidation or the error copy.
 *
 * Pass `mutation.variables` alongside `isPending` to render a per-row spinner:
 * one hook instance drives a whole roster, so `isPending` alone cannot say
 * *which* call is being dropped.
 */
export function useHangupCall({ workspaceId, onSuccess }: UseHangupCallOptions) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (callId: string) => {
      if (!workspaceId) throw new Error(messages.workspace.notLoaded);
      return callsApi.hangup(workspaceId, callId);
    },
    onSuccess: (_data, callId) => {
      // `calls.live()` is nested under `calls.all()`, so a single invalidation
      // refreshes the live roster, the call list, and the call detail together.
      queryClient.invalidateQueries({
        queryKey: queryKeys.calls.all(workspaceId ?? ""),
      });
      toast.success(messages.calls.ended);
      onSuccess?.(callId);
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, messages.calls.endFailed));
    },
  });
}
