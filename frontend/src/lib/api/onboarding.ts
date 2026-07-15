import api, { apiGet, apiPost } from "@/lib/api";

// ---- Request / Response Types ----

export interface OnboardRequest {
  calcom_api_key: string;
  calcom_event_type_id: number;
  area_code?: string;
}

export interface OnboardResponse {
  workspace_id: string;
  agent_id: string;
  phone_number_id: string | null;
  phone_number: string | null;
  /** False when no SMS number was auto-provisioned — campaigns can't launch yet. */
  phone_provisioned: boolean;
  calcom_connected: boolean;
  message: string;
}

export interface LaunchCampaignResponse {
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

// ---- API Functions ----

export function verifyCalcom(apiKey: string): Promise<VerifyCalcomResponse> {
  return apiGet<VerifyCalcomResponse>("/api/v1/onboarding/verify-calcom", {
    params: { api_key: apiKey },
  });
}

export function parseCalcomUrl(
  url: string,
  apiKey?: string
): Promise<ParseCalcomUrlResponse> {
  return apiPost<ParseCalcomUrlResponse>("/api/v1/onboarding/parse-calcom-url", {
    url,
    api_key: apiKey,
  });
}

export function onboard(data: OnboardRequest): Promise<OnboardResponse> {
  return apiPost<OnboardResponse>("/api/v1/onboarding/onboard", data);
}

export function createCampaignFromCsv(
  workspaceId: string,
  file: File,
  options: {
    skipDuplicates?: boolean;
    campaignName?: string;
    areaCode?: string;
  } = {}
): Promise<LaunchCampaignResponse> {
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
    .post<LaunchCampaignResponse>(
      `/api/v1/onboarding/campaigns`,
      formData,
      { headers: { "Content-Type": "multipart/form-data" } }
    )
    .then((r) => r.data);
}
