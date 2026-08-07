/**
 * On-site upsell API, typed straight from the OpenAPI spec.
 *
 * The narrow surface a field technician sells add-ons through while at the
 * customer's house. Every route is scoped server-side to the jobs the caller is
 * assigned to and to catalog items flagged attachable, so these clients cannot
 * reach the contact book or the full price book even if called with other ids.
 *
 * See `backend/app/api/v1/upsell.py` for the enforcement.
 */

import { apiClient, type Schemas } from "@/lib/api/_client";

export type UpsellJob = Schemas["UpsellJob"];
export type UpsellJobList = Schemas["UpsellJobListResponse"];
export type UpsellCustomer = Schemas["UpsellCustomer"];
export type UpsellCatalogItem = Schemas["UpsellCatalogItem"];
export type UpsellCatalog = Schemas["UpsellCatalogResponse"];
export type UpsellCarePlan = Schemas["UpsellCarePlanResponse"];
export type UpsellCarePlanOption = Schemas["CarePlanPricing"];
export type UpsellMyStats = Schemas["UpsellMyStats"];
export type UpsellQuoteRequest = Schemas["UpsellQuoteRequest"];
export type UpsellDeliverRequest = Schemas["UpsellDeliverRequest"];
export type UpsellQuote = Schemas["QuoteDetailResponse"];
export type UpsellDeliverResult = Schemas["QuoteDeliverResult"];

export const upsellApi = {
  /** Jobs the caller may sell an add-on on. Empty when they aren't a field worker. */
  listJobs: (workspaceId: string): Promise<UpsellJobList> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/upsell/jobs", {
      path: { workspace_id: workspaceId },
    }),

  /** The customer on a job the caller is assigned to. 404 when it isn't theirs. */
  getCustomer: (workspaceId: string, jobId: string): Promise<UpsellCustomer> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/upsell/jobs/{job_id}/customer", {
      path: { workspace_id: workspaceId, job_id: jobId },
    }),

  /** The add-on menu, optionally narrowed to what attaches to a service category. */
  listCatalog: (workspaceId: string, attachTarget?: string): Promise<UpsellCatalog> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/upsell/catalog", {
      path: { workspace_id: workspaceId },
      query: attachTarget ? { attach_target: attachTarget } : {},
    }),

  /**
   * Price the workspace's Care Plan tiers for a fixture count counted on site.
   * Returns `configured: false` when the workspace sells no maintenance plans.
   */
  listCarePlans: (workspaceId: string, fixtureCount: number): Promise<UpsellCarePlan> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/upsell/care-plans", {
      path: { workspace_id: workspaceId },
      query: { fixture_count: fixtureCount },
    }),

  /**
   * The caller's own selling numbers for the current month. Always self-scoped —
   * there is no user parameter, so this cannot be pointed at a colleague.
   */
  myStats: (workspaceId: string): Promise<UpsellMyStats> =>
    apiClient.get("/api/v1/workspaces/{workspace_id}/upsell/my-stats", {
      path: { workspace_id: workspaceId },
    }),

  /** Build a draft proposal. Prices are resolved server-side from the price book. */
  createQuote: (
    workspaceId: string,
    jobId: string,
    body: UpsellQuoteRequest,
  ): Promise<UpsellQuote> =>
    apiClient.post("/api/v1/workspaces/{workspace_id}/upsell/jobs/{job_id}/quote", {
      path: { workspace_id: workspaceId, job_id: jobId },
      body,
    }),

  /** Text or email the proposal to the customer on this job. */
  deliverQuote: (
    workspaceId: string,
    jobId: string,
    quoteId: string,
    body: UpsellDeliverRequest,
  ): Promise<UpsellDeliverResult> =>
    apiClient.post(
      "/api/v1/workspaces/{workspace_id}/upsell/jobs/{job_id}/quote/{quote_id}/deliver",
      {
        path: { workspace_id: workspaceId, job_id: jobId, quote_id: quoteId },
        body,
      },
    ),
};
