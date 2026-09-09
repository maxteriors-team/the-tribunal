import { apiGet, apiPost } from "@/lib/api";
import type { components } from "@/lib/api/_generated";

/** One house lit in an earlier season, with the quote a renewal would copy. */
export type RenewalCandidate = components["schemas"]["RenewalCandidateResponse"];
export type RenewalCandidateList = components["schemas"]["RenewalCandidateList"];
/** The draft produced by renewing — the same shape as any other quote detail. */
export type RenewalQuote = components["schemas"]["QuoteDetailResponse"];

export const christmasRenewalsApi = {
  list: async (
    workspaceId: string,
    params: { search?: string; limit?: number; offset?: number } = {},
  ): Promise<RenewalCandidateList> => {
    const query = new URLSearchParams();
    if (params.search) query.set("search", params.search);
    if (params.limit != null) query.set("limit", String(params.limit));
    if (params.offset != null) query.set("offset", String(params.offset));
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return apiGet<RenewalCandidateList>(
      `/api/v1/workspaces/${workspaceId}/christmas/renewals${suffix}`,
    );
  },

  /** Draft this season's quote from the customer's last holiday quote. */
  createQuote: async (workspaceId: string, contactId: number): Promise<RenewalQuote> =>
    apiPost<RenewalQuote>(
      `/api/v1/workspaces/${workspaceId}/christmas/renewals/${contactId}/quote`,
      {},
    ),
};
