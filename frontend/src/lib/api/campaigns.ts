import { apiGet, apiPost } from "@/lib/api";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";
import type { Campaign, CampaignStatus, CampaignType, GuaranteeProgress } from "@/types";

// Request/Response Types
export interface CampaignsListParams {
  page?: number;
  page_size?: number;
  search?: string;
  status?: CampaignStatus;
  type?: CampaignType;
}

export interface CampaignsListResponse {
  items: Campaign[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateCampaignRequest {
  name: string;
  description?: string;
  type: CampaignType;
  agent_id?: string;
  scheduled_start?: string;
  scheduled_end?: string;
}

export interface UpdateCampaignRequest {
  name?: string;
  description?: string;
  type?: CampaignType;
  status?: CampaignStatus;
  agent_id?: string;
  scheduled_start?: string;
  scheduled_end?: string;
}

export interface CampaignAnalytics {
  total_contacts: number;
  messages_sent: number;
  messages_delivered: number;
  messages_failed: number;
  replies_received: number;
  contacts_qualified: number;
  contacts_opted_out: number;
  reply_rate?: number;
  delivery_rate?: number;
  qualification_rate?: number;
}

export interface CampaignActionResponse {
  success: boolean;
  message: string;
  campaign: Campaign;
}

const baseApi = createApiClient<Campaign, CreateCampaignRequest, UpdateCampaignRequest>({
  resourcePath: "campaigns",
}) as FullApiClient<Campaign, CreateCampaignRequest, UpdateCampaignRequest>;

// Campaign CRUD API
export const campaignsApi = {
  ...baseApi,

  // Get campaign analytics (computed rates)
  getAnalytics: async (workspaceId: string, id: string): Promise<CampaignAnalytics> => {
    return apiGet<CampaignAnalytics>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${id}/analytics`
    );
  },

  // Campaign lifecycle actions
  start: async (workspaceId: string, id: string): Promise<CampaignActionResponse> => {
    return apiPost<CampaignActionResponse>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${id}/start`
    );
  },

  pause: async (workspaceId: string, id: string): Promise<CampaignActionResponse> => {
    return apiPost<CampaignActionResponse>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${id}/pause`
    );
  },

  resume: async (workspaceId: string, id: string): Promise<CampaignActionResponse> => {
    return apiPost<CampaignActionResponse>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${id}/resume`
    );
  },

  cancel: async (workspaceId: string, id: string): Promise<CampaignActionResponse> => {
    return apiPost<CampaignActionResponse>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${id}/cancel`
    );
  },

  // Duplicate a campaign
  duplicate: async (workspaceId: string, id: string, name?: string): Promise<Campaign> => {
    return apiPost<Campaign>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${id}/duplicate`,
      { name }
    );
  },

  // Get campaign guarantee progress
  getGuaranteeProgress: async (workspaceId: string, campaignId: string): Promise<GuaranteeProgress> => {
    return apiGet<GuaranteeProgress>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/guarantee`
    );
  },
};
