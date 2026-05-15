"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { appointmentsApi } from "@/lib/api/appointments";
import { callsApi, type InitiateCallRequest } from "@/lib/api/calls";
import { conversationsApi } from "@/lib/api/conversations";
import { phoneNumbersApi } from "@/lib/api/phone-numbers";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import {
  useContactTimeline,
  useToggleContactAI,
  useDeleteContact,
} from "@/hooks/useContacts";
import type { Contact } from "@/types";

interface UseContactSidebarDataArgs {
  workspaceId: string | null | undefined;
  contact: Contact | null;
}

/**
 * Aggregates all data + mutations the contact sidebar needs.
 * Keeps the orchestrating component thin and focused on layout.
 */
export function useContactSidebarData({
  workspaceId,
  contact,
}: UseContactSidebarDataArgs) {
  const { data: timelineData } = useContactTimeline(
    workspaceId ?? "",
    contact?.id ?? 0,
  );
  const timeline = timelineData ?? [];

  const { data: appointmentsData, isPending: appointmentsLoading } = useQuery({
    queryKey: queryKeys.appointments.byContact(workspaceId ?? "", contact?.id),
    queryFn: () =>
      appointmentsApi.list(workspaceId!, {
        page: 1,
        page_size: 50,
        contact_id: contact!.id,
      }),
    enabled: !!workspaceId && !!contact,
  });

  const { data: phoneNumbersData } = useQuery({
    queryKey: queryKeys.phoneNumbers.bare(workspaceId ?? ""),
    queryFn: () =>
      workspaceId
        ? phoneNumbersApi.list(workspaceId, { active_only: true })
        : Promise.resolve({
            items: [],
            total: 0,
            page: 1,
            page_size: 50,
            pages: 0,
          }),
    enabled: !!workspaceId,
  });

  const { data: conversationsData } = useQuery({
    queryKey: queryKeys.conversations.byContact(workspaceId ?? "", contact?.id),
    queryFn: () =>
      workspaceId
        ? conversationsApi.list(workspaceId, { page: 1, page_size: 100 })
        : Promise.resolve({
            items: [],
            total: 0,
            page: 1,
            page_size: 100,
            pages: 0,
          }),
    enabled: !!workspaceId && !!contact,
  });

  const contactConversation = conversationsData?.items?.find(
    (conv) => conv.contact_id === contact?.id,
  );

  // Derive AI state from server, with optimistic override during toggle.
  // Storing the last-seen server value lets us reset the override when the
  // server value changes — without an effect (per react-hooks/set-state-in-effect).
  const serverAiEnabled = contactConversation?.ai_enabled ?? false;
  const [aiState, setAiState] = useState<{
    optimistic: boolean | null;
    lastServer: boolean;
  }>({ optimistic: null, lastServer: serverAiEnabled });

  if (aiState.lastServer !== serverAiEnabled) {
    setAiState({ optimistic: null, lastServer: serverAiEnabled });
  }

  const aiEnabled = aiState.optimistic ?? serverAiEnabled;
  const setAiEnabled = (value: boolean) =>
    setAiState((prev) => ({ ...prev, optimistic: value }));

  const initiateCallMutation = useMutation({
    mutationFn: (data: InitiateCallRequest) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return callsApi.initiate(workspaceId, data);
    },
    onSuccess: () => {
      toast.success("Call initiated successfully!");
    },
    onError: (error) => {
      toast.error(
        getApiErrorMessage(error, "Failed to initiate call. Please try again."),
      );
    },
  });

  const toggleAIMutation = useToggleContactAI(workspaceId ?? "");
  const deleteContactMutation = useDeleteContact(workspaceId ?? "");

  return {
    timeline,
    appointments: appointmentsData?.items ?? [],
    appointmentsLoading,
    phoneNumbers: phoneNumbersData?.items ?? [],
    aiEnabled,
    setAiEnabled,
    initiateCallMutation,
    toggleAIMutation,
    deleteContactMutation,
  };
}
