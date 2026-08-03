"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  useContactAppointments,
  useContactQuotes,
} from "@/hooks/useContactRecords";
import {
  useContactTimeline,
  useToggleContactAI,
  useDeleteContact,
} from "@/hooks/useContacts";
import { useOutboundCall } from "@/hooks/useOutboundCall";
import { conversationsApi } from "@/lib/api/conversations";
import { queryKeys } from "@/lib/query-keys";
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

  const { data: appointmentsData, isPending: appointmentsLoading } =
    useContactAppointments(workspaceId, contact?.id);

  const { data: quotesData, isPending: quotesLoading } = useContactQuotes(
    workspaceId,
    contact?.id,
  );

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

  const toggleAIMutation = useToggleContactAI(workspaceId ?? "");
  const deleteContactMutation = useDeleteContact(workspaceId ?? "");

  const {
    phoneNumbers,
    callDialogOpen,
    setCallDialogOpen,
    startCall,
    submitCall,
    initiateCallMutation,
  } = useOutboundCall(workspaceId);

  /**
   * Open the outbound-call dialog for this contact. The dialog picks who talks
   * (AI agent or the operator's own phone); see :func:`useOutboundCall` for why
   * no surface may skip it.
   */
  const callContact = () => {
    startCall({
      name:
        [contact?.first_name, contact?.last_name].filter(Boolean).join(" ") ||
        "contact",
      phone: contact?.phone_number,
    });
  };

  return {
    timeline,
    appointments: appointmentsData?.items ?? [],
    appointmentsLoading,
    quotes: quotesData?.items ?? [],
    quotesLoading,
    phoneNumbers,
    aiEnabled,
    setAiEnabled,
    callContact,
    callDialogOpen,
    setCallDialogOpen,
    submitCall,
    initiateCallMutation,
    toggleAIMutation,
    deleteContactMutation,
  };
}
