import { apiGet, apiPost } from "@/lib/api";
import type { ValueStackItem, LeadMagnet } from "@/types";

// Public Offer Types
export interface PublicOffer {
  name: string;
  headline?: string;
  subheadline?: string;
  description?: string;
  regular_price?: number;
  offer_price?: number;
  savings_amount?: number;
  guarantee_type?: string;
  guarantee_days?: number;
  guarantee_text?: string;
  urgency_type?: string;
  urgency_text?: string;
  scarcity_count?: number;
  value_stack_items?: ValueStackItem[];
  cta_text?: string;
  cta_subtext?: string;
  lead_magnets: LeadMagnet[];
  total_value?: number;
  require_email: boolean;
  require_phone: boolean;
  require_name: boolean;
  business_name?: string;
}

export interface OptInRequest {
  email?: string;
  phone_number?: string;
  name?: string;
  /** Optional, unchecked-by-default SMS consent checkbox (10DLC/TCR). */
  sms_consent?: boolean;
}

export interface OptInResponse {
  success: boolean;
  message: string;
  contact_id?: number;
  lead_magnet_lead_id?: string;
}

// Public Offers API (no auth required)
export const publicOffersApi = {
  get: async (slug: string): Promise<PublicOffer> => {
    return apiGet<PublicOffer>(`/api/v1/p/offers/${slug}`);
  },

  optIn: async (slug: string, data: OptInRequest): Promise<OptInResponse> => {
    return apiPost<OptInResponse>(
      `/api/v1/p/offers/${slug}/opt-in`,
      data
    );
  },
};
