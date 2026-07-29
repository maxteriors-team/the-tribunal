import { useQuery } from "@tanstack/react-query";

import { appointmentsApi } from "@/lib/api/appointments";
import { quotesApi } from "@/lib/api/quotes";
import { queryKeys } from "@/lib/query-keys";

/** How many related records a single contact view loads at once. */
const PAGE_SIZE = 50;

/**
 * Appointments booked for one contact. Shared by the contact rail and the
 * contact detail page so both read the same cache entry.
 */
export function useContactAppointments(
  workspaceId: string | null | undefined,
  contactId: number | null | undefined,
) {
  return useQuery({
    queryKey: queryKeys.appointments.byContact(workspaceId ?? "", contactId ?? undefined),
    queryFn: () =>
      appointmentsApi.list(workspaceId!, {
        page: 1,
        page_size: PAGE_SIZE,
        contact_id: contactId!,
      }),
    enabled: !!workspaceId && !!contactId,
  });
}

/** Quotes issued to one contact. */
export function useContactQuotes(
  workspaceId: string | null | undefined,
  contactId: number | null | undefined,
) {
  return useQuery({
    queryKey: queryKeys.quotes.byContact(workspaceId ?? "", contactId ?? undefined),
    queryFn: () =>
      quotesApi.list(workspaceId!, {
        page: 1,
        page_size: PAGE_SIZE,
        contact_id: contactId!,
      }),
    enabled: !!workspaceId && !!contactId,
  });
}
