"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { callsApi, type InitiateCallRequest } from "@/lib/api/calls";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import { messages } from "@/lib/messages";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";

/** Whoever the operator is about to dial, from any surface. */
export interface OutboundCallTarget {
  name: string;
  phone: string | null | undefined;
}

/**
 * Shared click-to-call flow: the preflight guard, the dialog gate, and the
 * initiate mutation.
 *
 * Dialing straight from a button used to connect the contact to nobody, which
 * customers experienced as dead air — so every entry point must go through the
 * dialog that picks who actually talks (AI agent or the operator's phone).
 * Keeping that rule in one hook is why the contact rail, the contact detail
 * page, and the pipeline board cannot drift apart on it.
 */
export function useOutboundCall(workspaceId: string | null | undefined) {
  const [callDialogOpen, setCallDialogOpen] = useState(false);
  const [callTarget, setCallTarget] = useState<OutboundCallTarget | null>(null);

  const { data: phoneNumbersData } = useQuery({
    queryKey: queryKeys.phoneNumbers.all(workspaceId ?? ""),
    queryFn: () =>
      workspaceId
        ? phoneNumbersApi.list(workspaceId, { active_only: true })
        : Promise.resolve({ items: [], total: 0, page: 1, page_size: 50, pages: 0 }),
    enabled: !!workspaceId,
  });

  const phoneNumbers = phoneNumbersData?.items ?? [];

  const initiateCallMutation = useMutation({
    mutationFn: (data: InitiateCallRequest) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return callsApi.initiate(workspaceId, data);
    },
    onSuccess: (_data, variables) => {
      setCallDialogOpen(false);
      toast.success(
        variables.mode === "user"
          ? "Calling your phone — answer to connect the contact."
          : "Call initiated successfully!",
      );
    },
    onError: (error) => {
      toast.error(
        getApiErrorMessage(error, "Failed to initiate call. Please try again."),
      );
    },
  });

  /**
   * Preflight, then open the dialog. Fails loudly on the two states that would
   * otherwise produce a silently broken call: no number to dial, and no
   * voice-enabled workspace number to dial it from.
   */
  const startCall = (target: OutboundCallTarget) => {
    if (!target.phone) {
      toast.error(messages.contacts.noPhoneNumber);
      return;
    }
    if (phoneNumbers.filter((p) => p.voice_enabled).length === 0) {
      toast.error(messages.phoneNumbers.noneVoiceEnabled);
      return;
    }
    setCallTarget(target);
    setCallDialogOpen(true);
  };

  const submitCall = (request: InitiateCallRequest) => {
    initiateCallMutation.mutate(request);
  };

  return {
    phoneNumbers,
    callTarget,
    callDialogOpen,
    setCallDialogOpen,
    startCall,
    submitCall,
    initiateCallMutation,
  };
}
