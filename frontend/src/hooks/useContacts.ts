import { useQuery, useMutation, useQueryClient, keepPreviousData } from "@tanstack/react-query";

import {
  contactsApi,
  type ContactsListParams,
  type ContactIdsParams,
  type CreateContactRequest,
  type UpdateContactRequest,
} from "@/lib/api/contacts";
import type { ApiClient } from "@/lib/api/create-api-client";
import { createResourceHooks } from "@/lib/api/create-resource-hooks";
import { queryKeys } from "@/lib/query-keys";
import { REALTIME } from "@/lib/query-options";
import type { Contact, ContactStatus } from "@/types";

const {
  queryKeys: contactQueryKeys,
  useList: useContacts,
  useGet: useContact,
  useCreate: useCreateContact,
  useUpdate: useUpdateContact,
  useDelete: useDeleteContact,
} = createResourceHooks({
  resourceKey: "contacts",
  apiClient: contactsApi as unknown as ApiClient<Contact, CreateContactRequest, UpdateContactRequest>,
});

export { contactQueryKeys, useContacts, useContact, useCreateContact, useUpdateContact, useDeleteContact };

/**
 * Fetch a single page of contacts with server-side filtering/sorting/pagination
 */
export function useContactsPaginated(workspaceId: string, params: ContactsListParams) {
  return useQuery({
    queryKey: queryKeys.contacts.listWith(workspaceId, params),
    queryFn: () => contactsApi.list(workspaceId, params),
    enabled: !!workspaceId,
    placeholderData: keepPreviousData,
  });
}

/**
 * Bulk delete contacts
 */
export function useBulkDeleteContacts(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (ids: number[]) => contactsApi.bulkDelete(workspaceId, ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.bare(workspaceId) });
    },
  });
}

/**
 * Fetch the timeline for a contact with live polling
 */
export function useContactTimeline(workspaceId: string, contactId: number, limit: number = 100) {
  return useQuery({
    queryKey: queryKeys.contacts.timelineLegacy(workspaceId, contactId, limit),
    queryFn: () => contactsApi.getTimeline(workspaceId, contactId, limit),
    enabled: !!workspaceId && !!contactId,
    ...REALTIME,
    // Don't poll when the tab is not active
    refetchIntervalInBackground: false,
  });
}

/**
 * Bulk update contact status
 */
export function useBulkUpdateStatus(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (variables: { ids: number[]; status: ContactStatus }) =>
      contactsApi.bulkUpdateStatus(workspaceId, variables.ids, variables.status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.contacts.bare(workspaceId) });
    },
  });
}

/**
 * Fetch all contact IDs matching current filters (for select-all)
 */
export function useContactIds(
  workspaceId: string,
  params: ContactIdsParams,
  enabled: boolean,
  onSuccess?: (data: Awaited<ReturnType<typeof contactsApi.listIds>>) => void
) {
  return useQuery({
    queryKey: queryKeys.contacts.ids(workspaceId, params),
    queryFn: async () => {
      const data = await contactsApi.listIds(workspaceId, params);
      onSuccess?.(data);
      return data;
    },
    enabled: !!workspaceId && enabled,
  });
}

/**
 * Toggle AI for a contact's conversation
 */
export function useToggleContactAI(workspaceId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (variables: { contactId: number; enabled: boolean }) =>
      contactsApi.toggleAI(workspaceId, variables.contactId, variables.enabled),
    onSuccess: (_, variables) => {
      // Invalidate conversations to refresh AI state
      queryClient.invalidateQueries({ queryKey: queryKeys.conversations.bare(workspaceId) });
      queryClient.invalidateQueries({
        queryKey: queryKeys.contacts.aiState(workspaceId, variables.contactId),
      });
    },
  });
}
