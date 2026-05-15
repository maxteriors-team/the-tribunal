import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { contactsApi, type ContactsListParams } from "@/lib/api/contacts";
import { queryKeys } from "@/lib/query-keys";
import type { Contact, ContactStatus } from "@/types";

const PAGE_SIZE = 50;

interface UseInfiniteContactsParams {
  workspaceId: string | null;
  search?: string;
  status?: ContactStatus | "all";
  // Advanced filters
  tags?: string;
  tags_match?: "any" | "all" | "none";
  lead_score_min?: number;
  lead_score_max?: number;
  is_qualified?: boolean;
  source?: string;
  company_name?: string;
  created_after?: string;
  created_before?: string;
  enrichment_status?: string;
  filters?: string;
}

interface UseInfiniteContactsReturn {
  contacts: Contact[];
  total: number;
  isPending: boolean;
  isFetchingNextPage: boolean;
  hasNextPage: boolean;
  fetchNextPage: () => void;
  error: Error | null;
}

export function useInfiniteContacts({
  workspaceId,
  search,
  status,
  tags,
  tags_match,
  lead_score_min,
  lead_score_max,
  is_qualified,
  source,
  company_name,
  created_after,
  created_before,
  enrichment_status,
  filters,
}: UseInfiniteContactsParams): UseInfiniteContactsReturn {
  const query = useInfiniteQuery({
    queryKey: queryKeys.contacts.infinite(workspaceId, {
      search,
      status,
      tags,
      tags_match,
      lead_score_min,
      lead_score_max,
      is_qualified,
      source,
      company_name,
      created_after,
      created_before,
      enrichment_status,
      filters,
    }),
    queryFn: async ({ pageParam = 1 }) => {
      if (!workspaceId) {
        return { items: [], total: 0, page: 1, page_size: PAGE_SIZE, pages: 0 };
      }

      const params: ContactsListParams = {
        page: pageParam,
        page_size: PAGE_SIZE,
      };

      if (search && search.trim()) {
        params.search = search.trim();
      }

      if (status && status !== "all") {
        params.status = status;
      }

      // Advanced filters
      if (tags) params.tags = tags;
      if (tags_match) params.tags_match = tags_match;
      if (lead_score_min !== undefined) params.lead_score_min = lead_score_min;
      if (lead_score_max !== undefined) params.lead_score_max = lead_score_max;
      if (is_qualified !== undefined) params.is_qualified = is_qualified;
      if (source) params.source = source;
      if (company_name) params.company_name = company_name;
      if (created_after) params.created_after = created_after;
      if (created_before) params.created_before = created_before;
      if (enrichment_status) params.enrichment_status = enrichment_status;
      if (filters) params.filters = filters;

      return contactsApi.list(workspaceId, params);
    },
    initialPageParam: 1,
    getNextPageParam: (lastPage) => {
      if (lastPage.page < lastPage.pages) {
        return lastPage.page + 1;
      }
      return undefined;
    },
    enabled: !!workspaceId,
  });

  const contacts = useMemo(() => {
    return query.data?.pages.flatMap((page) => page.items) ?? [];
  }, [query.data?.pages]);

  const total = query.data?.pages[0]?.total ?? 0;

  return {
    contacts,
    total,
    isPending: query.isPending,
    isFetchingNextPage: query.isFetchingNextPage,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    error: query.error,
  };
}
