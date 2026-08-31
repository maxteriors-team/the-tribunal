import { apiGet, apiPost } from "@/lib/api";
import type { PublicComparison } from "@/types/estimate";

export interface PublicComparisonDeclineResult {
  token: string;
  is_declined: boolean;
  message: string;
}

// Public permanent-vs-temporary comparison API (no auth — keyed on the share
// token). The payload never contains linear feet; the client sees prices only.
export const publicComparisonsApi = {
  get: (token: string): Promise<PublicComparison> =>
    apiGet<PublicComparison>(`/api/v1/p/compare/${token}`),

  /**
   * Record that the client is not moving forward. Idempotent: a repeat keeps
   * the first decline, so a double-tap cannot move when interest died.
   */
  decline: (token: string, reason?: string): Promise<PublicComparisonDeclineResult> =>
    apiPost<PublicComparisonDeclineResult>(`/api/v1/p/compare/${token}/decline`, {
      reason: reason?.trim() || null,
    }),
};
