import { apiGet, apiPost } from "@/lib/api";
import type { SMSCampaign, CampaignStatus } from "@/types";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";

// Request/Response Types
export interface SMSCampaignsListParams {
  page?: number;
  page_size?: number;
  status_filter?: CampaignStatus;
}

export interface SMSCampaignsListResponse {
  items: SMSCampaign[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateSMSCampaignRequest {
  name: string;
  description?: string;
  agent_id?: string;
  offer_id?: string;
  from_phone_number: string;
  initial_message: string;
  ai_enabled?: boolean;
  qualification_criteria?: string;
  // Scheduling
  scheduled_start?: string;
  scheduled_end?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone?: string;
  // Rate limiting
  messages_per_minute?: number;
  max_messages_per_contact?: number;
  // Follow-ups
  follow_up_enabled?: boolean;
  follow_up_delay_hours?: number;
  follow_up_message?: string;
  max_follow_ups?: number;
}

export type UpdateSMSCampaignRequest = Partial<CreateSMSCampaignRequest>;

export interface CampaignContactsResponse {
  id: string;
  campaign_id: string;
  contact_id: number;
  conversation_id?: string;
  status: string;
  messages_sent: number;
  messages_received: number;
  follow_ups_sent: number;
  first_sent_at?: string;
  last_sent_at?: string;
  last_reply_at?: string;
  is_qualified: boolean;
  opted_out: boolean;
  created_at: string;
}

export interface CampaignAnalytics {
  total_contacts: number;
  messages_sent: number;
  messages_delivered: number;
  messages_failed: number;
  replies_received: number;
  contacts_qualified: number;
  contacts_opted_out: number;
  reply_rate: number;
  qualification_rate: number;
}

const baseApi = createApiClient<SMSCampaign, CreateSMSCampaignRequest, UpdateSMSCampaignRequest>({
  resourcePath: "campaigns",
}) as FullApiClient<SMSCampaign, CreateSMSCampaignRequest, UpdateSMSCampaignRequest>;

// SMS Campaigns API
export const smsCampaignsApi = {
  ...baseApi,

  // Campaign actions
  start: async (
    workspaceId: string,
    campaignId: string
  ): Promise<{ status: string; message: string }> => {
    return apiPost<{ status: string; message: string }>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/start`
    );
  },

  pause: async (
    workspaceId: string,
    campaignId: string
  ): Promise<{ status: string }> => {
    return apiPost<{ status: string }>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/pause`
    );
  },

  // Campaign contacts
  addContacts: async (
    workspaceId: string,
    campaignId: string,
    contactIds: number[]
  ): Promise<{ added: number }> => {
    return apiPost<{ added: number }>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/contacts`,
      { contact_ids: contactIds }
    );
  },

  getContacts: async (
    workspaceId: string,
    campaignId: string,
    params: { status_filter?: string; limit?: number } = {}
  ): Promise<CampaignContactsResponse[]> => {
    return apiGet<CampaignContactsResponse[]>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/contacts`,
      { params }
    );
  },

  // Analytics
  getAnalytics: async (
    workspaceId: string,
    campaignId: string
  ): Promise<CampaignAnalytics> => {
    return apiGet<CampaignAnalytics>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/analytics`
    );
  },
};
