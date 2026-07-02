/**
 * Sales-wizard API client.
 *
 * The wizard runs entirely server-authoritative: it loads the workspace pricing
 * config + fixture catalog, then POSTs a raw *selection* to `preview` (live
 * totals) and `save` (persist a draft quote + snapshot). No money is ever
 * computed on the client, matching `QuoteService`.
 */
import { apiGet, apiPost } from "@/lib/api";
import type {
  CatalogItemResponse,
  PricingSettings,
  ProposalDocument,
  ProposalWizardPayload,
  QuoteDetail,
} from "@/types/sales-wizard";

interface PaginatedCatalog {
  items: CatalogItemResponse[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

const base = (workspaceId: string) => `/api/v1/workspaces/${workspaceId}`;

export const salesWizardApi = {
  /** The proposal engine config (tiers, financing, care plan, bistro, tax…). */
  getPricing: (workspaceId: string): Promise<PricingSettings> =>
    apiGet<PricingSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/pricing`,
    ),

  /** Active catalog items (the fixture library) for the workspace. */
  listCatalog: (workspaceId: string): Promise<CatalogItemResponse[]> =>
    apiGet<PaginatedCatalog>(
      `${base(workspaceId)}/catalog-items?page_size=500&include_inactive=false`,
    ).then((r) => r.items),

  /** Compute the full multi-tier document without persisting (live preview). */
  preview: (
    workspaceId: string,
    payload: ProposalWizardPayload,
  ): Promise<ProposalDocument> =>
    apiPost<ProposalDocument>(
      `${base(workspaceId)}/quotes/wizard/preview`,
      payload,
    ),

  /** Save the proposal as a draft quote + snapshot; returns the quote (token). */
  save: (
    workspaceId: string,
    payload: ProposalWizardPayload,
  ): Promise<QuoteDetail> =>
    apiPost<QuoteDetail>(`${base(workspaceId)}/quotes/wizard`, payload),

  /** Mark the saved quote sent (allocates the public token) so it can be shared. */
  send: (workspaceId: string, quoteId: string): Promise<QuoteDetail> =>
    apiPost<QuoteDetail>(`${base(workspaceId)}/quotes/${quoteId}/send`),
};
