import api, { apiGet, apiPost } from "@/lib/api";

// ---- Request / Response Types ----

export interface RealtorOnboardRequest {
  calcom_api_key: string;
  calcom_event_type_id: number;
  area_code?: string;
}

export interface RealtorOnboardResponse {
  workspace_id: string;
  agent_id: string;
  phone_number_id: string | null;
  phone_number: string | null;
  /** False when no SMS number was auto-provisioned — campaigns can't launch yet. */
  phone_provisioned: boolean;
  calcom_connected: boolean;
  message: string;
}

export interface RealtorCampaignResponse {
  campaign_id: string;
  campaign_name: string;
  campaign_status: string;
  contacts_imported: number;
  contacts_skipped: number;
  contacts_failed: number;
  phone_number_used: string;
  agent_id: string;
  started_at: string | null;
}

export interface VerifyCalcomResponse {
  valid: boolean;
  username?: string;
}

export interface ParseCalcomUrlResponse {
  event_type_id: number;
  slug: string;
}

export interface RealtorStats {
  leads_uploaded: number;
  texts_sent: number;
  replies_received: number;
  appointments_booked: number;
}

// ---- API Functions ----

export function getRealtorStats(workspaceId: string): Promise<RealtorStats> {
  return apiGet<RealtorStats>(`/api/v1/workspaces/${workspaceId}/realtor/stats`);
}

export function verifyCalcom(apiKey: string): Promise<VerifyCalcomResponse> {
  return apiGet<VerifyCalcomResponse>("/api/v1/realtor/verify-calcom", {
    params: { api_key: apiKey },
  });
}

export function parseCalcomUrl(
  url: string,
  apiKey?: string
): Promise<ParseCalcomUrlResponse> {
  return apiPost<ParseCalcomUrlResponse>("/api/v1/realtor/parse-calcom-url", {
    url,
    api_key: apiKey,
  });
}

export function onboard(data: RealtorOnboardRequest): Promise<RealtorOnboardResponse> {
  return apiPost<RealtorOnboardResponse>("/api/v1/realtor/onboard", data);
}

export function createCampaignFromCsv(
  workspaceId: string,
  file: File,
  options: {
    skipDuplicates?: boolean;
    campaignName?: string;
    areaCode?: string;
  } = {}
): Promise<RealtorCampaignResponse> {
  const formData = new FormData();
  formData.append("file", file);
  if (options.skipDuplicates !== undefined) {
    formData.append("skip_duplicates", String(options.skipDuplicates));
  }
  if (options.campaignName) {
    formData.append("campaign_name", options.campaignName);
  }
  if (options.areaCode) {
    formData.append("area_code", options.areaCode);
  }

  return api
    .post<RealtorCampaignResponse>(
      `/api/v1/workspaces/${workspaceId}/realtor/campaigns`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    )
    .then((r) => r.data);
}
