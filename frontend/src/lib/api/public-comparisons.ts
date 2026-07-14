import { apiGet } from "@/lib/api";
import type { PublicComparison } from "@/types/estimate";

// Public permanent-vs-temporary comparison API (no auth — keyed on the share
// token). The payload never contains linear feet; the client sees prices only.
export const publicComparisonsApi = {
  get: (token: string): Promise<PublicComparison> =>
    apiGet<PublicComparison>(`/api/v1/p/compare/${token}`),
};
