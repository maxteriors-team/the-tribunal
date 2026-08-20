import { apiPost } from "@/lib/api";
import type { Schemas } from "@/lib/api/_client";

export type PublicPaymentVerification = Schemas["PublicPaymentVerification"];
export type PublicPaymentStatus = PublicPaymentVerification["status"];

export const publicPaymentsApi = {
  verify: (sessionId: string, signal?: AbortSignal): Promise<PublicPaymentVerification> =>
    apiPost<PublicPaymentVerification>(
      `/api/v1/p/payments/checkout-sessions/${encodeURIComponent(sessionId)}/verify`,
      undefined,
      { signal },
    ),
};
