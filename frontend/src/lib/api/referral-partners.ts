import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";

/** Relationship kind, mirroring `ReferralPartnerType` on the backend. */
export type ReferralPartnerType =
  | "realtor"
  | "insurance"
  | "trade"
  | "bni"
  | "customer"
  | "other";

export interface ReferralPartner {
  id: string;
  workspace_id: string;
  name: string;
  company: string | null;
  partner_type: ReferralPartnerType;
  email: string | null;
  phone: string | null;
  notes: string | null;
  contact_id: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ReferralPartnerListResponse {
  items: ReferralPartner[];
  total: number;
}

export interface ReferralPartnerCreateRequest {
  name: string;
  company?: string | null;
  partner_type?: ReferralPartnerType;
  email?: string | null;
  phone?: string | null;
  notes?: string | null;
  contact_id?: number | null;
  is_active?: boolean;
}

export type ReferralPartnerUpdateRequest = Partial<ReferralPartnerCreateRequest>;

/**
 * One partner's production.
 *
 * `close_rate` and `average_job_value` are `null` — never `0` — when their
 * denominator is empty. The UI must not coerce with `?? 0`: that would render a
 * partner nobody has asked for a referral yet as a 0% failure.
 */
export interface ReferralPartnerScoreboardRow {
  partner_id: string;
  name: string;
  company: string | null;
  partner_type: ReferralPartnerType;
  is_active: boolean;
  referrals_sent: number;
  jobs_closed: number;
  close_rate: number | null;
  total_revenue: number;
  average_job_value: number | null;
  last_referral_at: string | null;
  days_since_last_referral: number | null;
  is_gone_quiet: boolean;
}

export interface ReferralPartnerScoreboard {
  items: ReferralPartnerScoreboardRow[];
  total: number;
  quiet_after_days: number;
  gone_quiet_only: boolean;
  currency: string;
  total_referrals_sent: number;
  total_jobs_closed: number;
  total_revenue: number;
}

export interface ReferralPartnerScoreboardParams {
  /** Days of silence after which a partner counts as gone quiet. */
  quiet_after_days?: number;
  /** Narrow to partners with history and nothing inside the window. */
  gone_quiet_only?: boolean;
  is_active?: boolean;
  partner_type?: ReferralPartnerType;
}

/** Serialize defined params only, so an absent filter never sends `undefined`. */
function toQuery(params: object | undefined): string {
  if (!params) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export const referralPartnersApi = {
  list: async (
    workspaceId: string,
    params?: { is_active?: boolean; partner_type?: ReferralPartnerType },
  ): Promise<ReferralPartnerListResponse> => {
    return apiGet<ReferralPartnerListResponse>(
      `/api/v1/workspaces/${workspaceId}/referral-partners${toQuery(params)}`,
    );
  },

  get: async (workspaceId: string, id: string): Promise<ReferralPartner> => {
    return apiGet<ReferralPartner>(
      `/api/v1/workspaces/${workspaceId}/referral-partners/${id}`,
    );
  },

  create: async (
    workspaceId: string,
    data: ReferralPartnerCreateRequest,
  ): Promise<ReferralPartner> => {
    return apiPost<ReferralPartner>(
      `/api/v1/workspaces/${workspaceId}/referral-partners`,
      data,
    );
  },

  update: async (
    workspaceId: string,
    id: string,
    data: ReferralPartnerUpdateRequest,
  ): Promise<ReferralPartner> => {
    return apiPut<ReferralPartner>(
      `/api/v1/workspaces/${workspaceId}/referral-partners/${id}`,
      data,
    );
  },

  delete: async (workspaceId: string, id: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/referral-partners/${id}`);
  },

  scoreboard: async (
    workspaceId: string,
    params?: ReferralPartnerScoreboardParams,
  ): Promise<ReferralPartnerScoreboard> => {
    return apiGet<ReferralPartnerScoreboard>(
      `/api/v1/workspaces/${workspaceId}/referral-partners/scoreboard${toQuery(params)}`,
    );
  },
};
