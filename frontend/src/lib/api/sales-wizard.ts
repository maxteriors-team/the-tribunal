/**
 * Sales-wizard API client.
 *
 * The wizard runs entirely server-authoritative: it loads the workspace pricing
 * config + fixture catalog, then POSTs a raw *selection* to `preview` (live
 * totals) and `save` (persist a draft quote + snapshot). No money is ever
 * computed on the client, matching `QuoteService`.
 */
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type {
  CatalogItemResponse,
  PricingSettings,
  PricingSettingsUpdate,
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

  /** Update the pricing config (shallow top-level block merge). Each provided
   *  block replaces that whole block, so callers send a full sub-config. */
  updatePricing: (
    workspaceId: string,
    data: PricingSettingsUpdate,
  ): Promise<PricingSettings> =>
    apiPut<PricingSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/pricing`,
      data,
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

  /** Load the authenticated quote detail used to hydrate an existing builder. */
  getQuote: (workspaceId: string, quoteId: string): Promise<QuoteDetail> =>
    apiGet<QuoteDetail>(`${base(workspaceId)}/quotes/${quoteId}`),

  /** Save a new proposal as a draft quote + snapshot. */
  save: (
    workspaceId: string,
    payload: ProposalWizardPayload,
  ): Promise<QuoteDetail> =>
    apiPost<QuoteDetail>(`${base(workspaceId)}/quotes/wizard`, payload),

  /** Reprice an unpaid draft/sent quote in place, preserving its public link. */
  update: (
    workspaceId: string,
    quoteId: string,
    payload: ProposalWizardPayload,
  ): Promise<QuoteDetail> =>
    apiPut<QuoteDetail>(`${base(workspaceId)}/quotes/${quoteId}/wizard`, payload),

  /** Fork protected customer/payment terms into a separately numbered draft. */
  revise: (
    workspaceId: string,
    quoteId: string,
    payload: ProposalWizardPayload,
  ): Promise<QuoteDetail> =>
    apiPost<QuoteDetail>(
      `${base(workspaceId)}/quotes/${quoteId}/revisions`,
      payload,
    ),

  /** Mark a new saved quote sent (allocates a public token) so it can be shared. */
  send: (workspaceId: string, quoteId: string): Promise<QuoteDetail> =>
    apiPost<QuoteDetail>(`${base(workspaceId)}/quotes/${quoteId}/send`),

  /** Deliver the client proposal link by email or SMS (server sends it). */
  deliver: (
    workspaceId: string,
    quoteId: string,
    channel: "email" | "sms",
    to?: string,
  ): Promise<{ ok: boolean; channel: string; to: string }> =>
    apiPost<{ ok: boolean; channel: string; to: string }>(
      `${base(workspaceId)}/quotes/${quoteId}/deliver`,
      { channel, to: to || null },
    ),
};
