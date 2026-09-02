import { useQuery } from "@tanstack/react-query";

import { contactsApi, type ContactJobTimeSummary } from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";

export function useContactJobTime(workspaceId: string, contactId: number) {
  return useQuery<ContactJobTimeSummary>({
    queryKey: queryKeys.contacts.jobTime(workspaceId, contactId),
    queryFn: () => contactsApi.getJobTime(workspaceId, contactId),
    enabled: Boolean(workspaceId && contactId),
  });
}
