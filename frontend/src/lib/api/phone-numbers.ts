import { apiDelete, apiGet, apiPost, apiPut } from "@/lib/api";
import { createApiClient } from "@/lib/api/create-api-client";
import type { PhoneNumber } from "@/types";

// Request/Response Types
export interface PhoneNumbersListParams {
  page?: number;
  page_size?: number;
  sms_enabled?: boolean;
  voice_enabled?: boolean;
  active_only?: boolean;
  [key: string]: unknown;
}

export interface PhoneNumbersListResponse {
  items: PhoneNumber[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface SearchPhoneNumbersRequest {
  country: string;
  area_code?: string;
  contains?: string;
  limit?: number;
}

export interface PhoneNumberSearchResult {
  id: string;
  phone_number: string;
  friendly_name: string | null;
  capabilities: {
    sms?: boolean;
    voice?: boolean;
    mms?: boolean;
  } | null;
}

export interface PurchasePhoneNumberRequest {
  phone_number: string;
}

export interface PhoneNumberUpdateRequest {
  lead_source_id?: string | null;
  lead_source_campaign_id?: string | null;
  tracking_label?: string | null;
}

export interface InboundReadinessCheck {
  code: string;
  ready: boolean;
  message: string;
}

export interface InboundCallReadiness {
  phone_number_id: string;
  ready: boolean;
  enabled: boolean;
  assigned_agent_id: string | null;
  fallback_configured: boolean;
  transfer_destination_configured: boolean;
  checks: InboundReadinessCheck[];
}

export interface InboundCallConfigRequest {
  enabled: boolean;
  assigned_agent_id?: string | null;
  fallback_number?: string | null;
  transfer_destination_number?: string | null;
}

// Create base API client with standard methods (list, get only - no create/update)
// Note: release uses a different endpoint and return type than standard delete
const basePhoneNumbersApi = createApiClient<PhoneNumber, never, never>({
  resourcePath: "phone-numbers",
  includeCreate: false,
  includeUpdate: false,
  includeDelete: false,
});

// Type assertion to ensure get is non-optional since we enabled it
const basePhoneNumbersApiWithGet = basePhoneNumbersApi as {
  list: typeof basePhoneNumbersApi.list;
  get: NonNullable<typeof basePhoneNumbersApi.get>;
};

// Phone Numbers API
export const phoneNumbersApi = {
  ...basePhoneNumbersApiWithGet,

  update: async (
    workspaceId: string,
    phoneNumberId: string,
    data: PhoneNumberUpdateRequest,
  ): Promise<PhoneNumber> => {
    return apiPut<PhoneNumber>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/${phoneNumberId}`,
      data,
    );
  },

  search: async (
    workspaceId: string,
    params: SearchPhoneNumbersRequest,
  ): Promise<PhoneNumberSearchResult[]> => {
    return apiPost<PhoneNumberSearchResult[]>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/search`,
      params,
    );
  },

  purchase: async (workspaceId: string, data: PurchasePhoneNumberRequest): Promise<PhoneNumber> => {
    return apiPost<PhoneNumber>(`/api/v1/workspaces/${workspaceId}/phone-numbers/purchase`, data);
  },

  release: async (workspaceId: string, phoneNumberId: string): Promise<{ success: boolean }> => {
    return apiDelete<{ success: boolean }>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/${phoneNumberId}`,
    );
  },

  sync: async (workspaceId: string): Promise<{ synced: number }> => {
    return apiPost<{ synced: number }>(`/api/v1/workspaces/${workspaceId}/phone-numbers/sync`, {});
  },

  inboundReadiness: async (
    workspaceId: string,
    phoneNumberId: string,
  ): Promise<InboundCallReadiness> => {
    return apiGet<InboundCallReadiness>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/${phoneNumberId}/inbound-readiness`,
    );
  },

  configureInbound: async (
    workspaceId: string,
    phoneNumberId: string,
    data: InboundCallConfigRequest,
  ): Promise<InboundCallReadiness> => {
    return apiPut<InboundCallReadiness>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/${phoneNumberId}/inbound-config`,
      data,
    );
  },
};
