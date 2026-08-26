/**
 * Shared proposal-pricing API client.
 *
 * Editors load workspace pricing and the fixture catalog, then send raw selections
 * to server-authoritative preview/save endpoints. No money is computed here.
 */
import { apiGet, apiPost, apiPut } from "@/lib/api";
import type { QuoteInventoryAvailability } from "@/types/inventory";
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
    apiGet<PricingSettings>(`/api/v1/settings/workspaces/${workspaceId}/pricing`),

  /** Update the pricing config (shallow top-level block merge). Each provided
   *  block replaces that whole block, so callers send a full sub-config. */
  updatePricing: (workspaceId: string, data: PricingSettingsUpdate): Promise<PricingSettings> =>
    apiPut<PricingSettings>(`/api/v1/settings/workspaces/${workspaceId}/pricing`, data),

  /** Active catalog items (the fixture library) for the workspace. */
  listCatalog: (workspaceId: string): Promise<CatalogItemResponse[]> =>
    apiGet<PaginatedCatalog>(
      `${base(workspaceId)}/catalog-items?page_size=500&include_inactive=false`,
    ).then((r) => r.items),

  /** Compute the full multi-tier document without persisting (live preview). */
  preview: (workspaceId: string, payload: ProposalWizardPayload): Promise<ProposalDocument> =>
    apiPost<ProposalDocument>(`${base(workspaceId)}/quotes/wizard/preview`, payload),

  inventoryAvailability: (
    workspaceId: string,
    payload: ProposalWizardPayload,
  ): Promise<QuoteInventoryAvailability> =>
    apiPost<QuoteInventoryAvailability>(
      `${base(workspaceId)}/quotes/wizard/inventory-availability`,
      payload,
    ),

  /** Save a new proposal as a draft quote + snapshot. */
  save: (workspaceId: string, payload: ProposalWizardPayload): Promise<QuoteDetail> =>
    apiPost<QuoteDetail>(`${base(workspaceId)}/quotes/wizard`, payload),

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
