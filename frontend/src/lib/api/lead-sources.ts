import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";

/** Top-level attribution channel used to rank lead-source ROI. */
export type LeadSourceType =
  | "facebook_ads"
  | "google_ads"
  | "organic"
  | "phone_radio"
  | "other";

export type LeadSourceAction =
  | "collect"
  | "auto_text"
  | "auto_call"
  | "enroll_campaign";

export interface LeadSource {
  id: string;
  workspace_id: string;
  name: string;
  public_key: string;
  allowed_domains: string[];
  enabled: boolean;
  source_type: LeadSourceType;
  action: LeadSourceAction;
  action_config: Record<string, string>;
  created_at: string;
  updated_at: string;
  endpoint_url: string;
}

export interface LeadSourceCreateRequest {
  name: string;
  allowed_domains: string[];
  source_type?: LeadSourceType;
  action: LeadSourceAction;
  action_config?: Record<string, string>;
}

export interface LeadSourceUpdateRequest {
  name?: string;
  allowed_domains?: string[];
  enabled?: boolean;
  source_type?: LeadSourceType;
  action?: LeadSourceAction;
  action_config?: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Attribution campaigns nested under a lead source.
// ---------------------------------------------------------------------------

export interface LeadSourceCampaign {
  id: string;
  workspace_id: string;
  lead_source_id: string;
  name: string;
  platform_campaign_id: string | null;
  platform_campaign_name: string | null;
  utm_campaign: string | null;
  description: string | null;
  enabled: boolean;
  campaign_metadata: Record<string, unknown>;
  started_on: string | null;
  ended_on: string | null;
  created_at: string;
  updated_at: string;
}

export interface LeadSourceCampaignCreateRequest {
  lead_source_id: string;
  name: string;
  platform_campaign_id?: string | null;
  platform_campaign_name?: string | null;
  utm_campaign?: string | null;
  description?: string | null;
  enabled?: boolean;
  started_on?: string | null;
  ended_on?: string | null;
}

// ---------------------------------------------------------------------------
// Manual ad/source spend entries.
// ---------------------------------------------------------------------------

export interface LeadSourceSpendEntry {
  id: string;
  workspace_id: string;
  lead_source_id: string;
  lead_source_campaign_id: string | null;
  spend_starts_on: string;
  spend_ends_on: string;
  amount: number;
  currency: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface LeadSourceSpendEntryCreateRequest {
  lead_source_id: string;
  lead_source_campaign_id?: string | null;
  spend_starts_on: string;
  spend_ends_on: string;
  amount: number;
  currency?: string;
  notes?: string | null;
}

// ---------------------------------------------------------------------------
// Unknown-attribution cleanup queue: leads captured without a known source.
// ---------------------------------------------------------------------------

export interface UnattributedLead {
  contact_id: number;
  first_name: string;
  last_name: string | null;
  phone_number: string | null;
  email: string | null;
  source: string | null;
  created_at: string;
  suggested_source_type: LeadSourceType | null;
  suggested_lead_source_id: string | null;
}

export interface AssignLeadSourceRequest {
  lead_source_id: string;
  lead_source_campaign_id?: string | null;
  source_type?: LeadSourceType;
}

export const leadSourcesApi = {
  list: async (workspaceId: string): Promise<LeadSource[]> => {
    return apiGet<LeadSource[]>(
      `/api/v1/workspaces/${workspaceId}/lead-sources`
    );
  },

  get: async (workspaceId: string, id: string): Promise<LeadSource> => {
    return apiGet<LeadSource>(
      `/api/v1/workspaces/${workspaceId}/lead-sources/${id}`
    );
  },

  create: async (
    workspaceId: string,
    data: LeadSourceCreateRequest
  ): Promise<LeadSource> => {
    return apiPost<LeadSource>(
      `/api/v1/workspaces/${workspaceId}/lead-sources`,
      data
    );
  },

  update: async (
    workspaceId: string,
    id: string,
    data: LeadSourceUpdateRequest
  ): Promise<LeadSource> => {
    return apiPut<LeadSource>(
      `/api/v1/workspaces/${workspaceId}/lead-sources/${id}`,
      data
    );
  },

  delete: async (workspaceId: string, id: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/lead-sources/${id}`);
  },

  // --- Attribution campaigns ------------------------------------------------

  listCampaigns: async (
    workspaceId: string,
    leadSourceId: string
  ): Promise<LeadSourceCampaign[]> => {
    return apiGet<LeadSourceCampaign[]>(
      `/api/v1/workspaces/${workspaceId}/lead-sources/${leadSourceId}/campaigns`
    );
  },

  createCampaign: async (
    workspaceId: string,
    data: LeadSourceCampaignCreateRequest
  ): Promise<LeadSourceCampaign> => {
    return apiPost<LeadSourceCampaign>(
      `/api/v1/workspaces/${workspaceId}/lead-source-campaigns`,
      data
    );
  },

  deleteCampaign: async (workspaceId: string, id: string): Promise<void> => {
    await apiDelete(
      `/api/v1/workspaces/${workspaceId}/lead-source-campaigns/${id}`
    );
  },

  // --- Manual spend ---------------------------------------------------------

  listSpend: async (
    workspaceId: string,
    leadSourceId?: string
  ): Promise<LeadSourceSpendEntry[]> => {
    const query = leadSourceId ? `?lead_source_id=${leadSourceId}` : "";
    return apiGet<LeadSourceSpendEntry[]>(
      `/api/v1/workspaces/${workspaceId}/lead-source-spend${query}`
    );
  },

  createSpend: async (
    workspaceId: string,
    data: LeadSourceSpendEntryCreateRequest
  ): Promise<LeadSourceSpendEntry> => {
    return apiPost<LeadSourceSpendEntry>(
      `/api/v1/workspaces/${workspaceId}/lead-source-spend`,
      data
    );
  },

  deleteSpend: async (workspaceId: string, id: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/lead-source-spend/${id}`);
  },

  // --- Unknown-attribution cleanup queue ------------------------------------

  listUnattributed: async (
    workspaceId: string
  ): Promise<UnattributedLead[]> => {
    return apiGet<UnattributedLead[]>(
      `/api/v1/workspaces/${workspaceId}/lead-sources/unattributed`
    );
  },

  assignSource: async (
    workspaceId: string,
    contactId: number,
    data: AssignLeadSourceRequest
  ): Promise<void> => {
    await apiPost(
      `/api/v1/workspaces/${workspaceId}/contacts/${contactId}/lead-source`,
      data
    );
  },
};
