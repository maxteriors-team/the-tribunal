/**
 * Roofline estimator API client (authenticated).
 *
 * The rep measures a roofline in linear feet on a photo and asks the server what
 * we'd charge for permanent vs seasonal lighting. Feet is the only input the
 * client sends; every dollar is computed server-side, matching the sales wizard.
 * `share` persists the estimate behind a token and returns the client-facing URL.
 */
import { apiPost } from "@/lib/api";
import type {
  ComparisonDeliverResult,
  ComparisonShareRequest,
  ComparisonShareResult,
  EstimateQuoteRequest,
  EstimateRenderRequest,
  EstimateRenderResult,
  LinearFeetEstimateRequest,
  LinearFeetEstimateResult,
  QuoteDetailResponse,
} from "@/types/estimate";

const base = (workspaceId: string) => `/api/v1/workspaces/${workspaceId}`;

export const estimatorApi = {
  /** Price permanent vs temporary for a measured roofline (no persistence). */
  estimate: (
    workspaceId: string,
    payload: LinearFeetEstimateRequest,
  ): Promise<LinearFeetEstimateResult> =>
    apiPost<LinearFeetEstimateResult>(
      `${base(workspaceId)}/quotes/estimate`,
      payload,
    ),

  /**
   * Turn a drawn design (composited over the photo) into a photorealistic night
   * render. Server-side OpenAI edit using the workspace credential — no browser
   * key; the client only sends the flattened image.
   */
  render: (
    workspaceId: string,
    payload: EstimateRenderRequest,
  ): Promise<EstimateRenderResult> =>
    apiPost<EstimateRenderResult>(
      `${base(workspaceId)}/quotes/estimate/render`,
      payload,
    ),

  /** Persist the comparison and get a shareable client link. */
  share: (
    workspaceId: string,
    payload: ComparisonShareRequest,
  ): Promise<ComparisonShareResult> =>
    apiPost<ComparisonShareResult>(
      `${base(workspaceId)}/quotes/estimate/share`,
      payload,
    ),

  /** Email a saved estimate's client link to the customer. */
  deliver: (
    workspaceId: string,
    token: string,
    to?: string | null,
  ): Promise<ComparisonDeliverResult> =>
    apiPost<ComparisonDeliverResult>(
      `${base(workspaceId)}/quotes/estimate/comparison/${token}/send`,
      { to: to ?? null },
    ),

  /**
   * Convert the measured design into a real draft quote. ``side`` picks the
   * permanent install or the seasonal job; every line is priced server-side.
   */
  createQuote: (
    workspaceId: string,
    payload: EstimateQuoteRequest,
  ): Promise<QuoteDetailResponse> =>
    apiPost<QuoteDetailResponse>(
      `${base(workspaceId)}/quotes/estimate/quote`,
      payload,
    ),
};
