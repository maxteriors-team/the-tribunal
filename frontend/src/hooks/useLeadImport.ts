"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

/**
 * Shared mutation hook for importing leads. Handles workspace guard, contact
 * cache invalidation, success/error toasts, and exposes the response via
 * onSuccess for page-specific UI state (banners, detail lists).
 *
 * Pages pass:
 * - importFn: the actual API call (e.g. scrapingApi.importLeads(workspaceId, request))
 * - onSuccess: page-level callback to stash the response for banners
 * - successToast: optional builder for a custom success/error toast message
 */
export function useLeadImport<TRequest, TResponse extends { imported: number }>(opts: {
  importFn: (workspaceId: string, request: TRequest) => Promise<TResponse>;
  onSuccess?: (data: TResponse) => void;
  /**
   * Build the toast to show after a successful import. Return null to skip the
   * toast entirely. Default: "Successfully imported N leads" when imported > 0.
   */
  successToast?: (data: TResponse) => { type: "success" | "error"; message: string } | null;
  onError?: (error: unknown) => void;
  errorFallback?: string;
}) {
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();

  return useMutation({
    mutationFn: async (request: TRequest) => {
      if (!workspaceId) throw new Error("No workspace");
      return opts.importFn(workspaceId, request);
    },
    onSuccess: (data) => {
      opts.onSuccess?.(data);
      queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.bare(workspaceId ?? ""),
      });
      const message =
        opts.successToast?.(data) ??
        (data.imported > 0
          ? { type: "success" as const, message: `Successfully imported ${data.imported} leads` }
          : null);
      if (message) {
        if (message.type === "success") toast.success(message.message);
        else toast.error(message.message);
      }
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, opts.errorFallback ?? "Failed to import leads"));
      opts.onError?.(error);
    },
  });
}
