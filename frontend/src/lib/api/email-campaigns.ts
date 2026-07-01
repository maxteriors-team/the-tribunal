import { apiPost } from "@/lib/api";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";
import type { Campaign } from "@/types";

/**
 * Email campaigns reuse the shared `campaigns` resource on the backend; the
 * `campaign_type: "email"` discriminator selects the email send path (Resend
 * with a compliant unsubscribe footer) instead of SMS/voice.
 */
export interface CreateEmailCampaignRequest {
  name: string;
  campaign_type: "email";
  description?: string;
  email_subject: string;
  initial_message: string; // the email body
  scheduled_start?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone?: string;
}

export type UpdateEmailCampaignRequest = Partial<CreateEmailCampaignRequest>;

const baseApi = createApiClient<
  Campaign,
  CreateEmailCampaignRequest,
  UpdateEmailCampaignRequest
>({
  resourcePath: "campaigns",
}) as FullApiClient<Campaign, CreateEmailCampaignRequest, UpdateEmailCampaignRequest>;

export const emailCampaignsApi = {
  ...baseApi,

  start: async (
    workspaceId: string,
    campaignId: string
  ): Promise<{ status: string; message: string }> => {
    return apiPost<{ status: string; message: string }>(
      `/api/v1/workspaces/${workspaceId}/campaigns/${campaignId}/start`
    );
  },

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
};
