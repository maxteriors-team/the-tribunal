import { apiGet, apiPost } from "@/lib/api";

// ---- Types ----

export interface BillingStatus {
  subscribed: boolean;
  plan: string | null;
  status: string | null;
  current_period_end: string | null;
}

// ---- API Functions ----

export function createCheckout(priceId?: string): Promise<{ checkout_url: string }> {
  return apiPost<{ checkout_url: string }>("/api/v1/billing/checkout", {
    price_id: priceId ?? null,
  });
}

export function createPortal(): Promise<{ portal_url: string }> {
  return apiPost<{ portal_url: string }>("/api/v1/billing/portal");
}

export function getBillingStatus(): Promise<BillingStatus> {
  return apiGet<BillingStatus>("/api/v1/billing/status");
}
