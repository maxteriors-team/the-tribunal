import { apiPost, apiDelete } from "@/lib/api";
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

  search: async (
    workspaceId: string,
    params: SearchPhoneNumbersRequest
  ): Promise<PhoneNumberSearchResult[]> => {
    return apiPost<PhoneNumberSearchResult[]>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/search`,
      params
    );
  },

  purchase: async (
    workspaceId: string,
    data: PurchasePhoneNumberRequest
  ): Promise<PhoneNumber> => {
    return apiPost<PhoneNumber>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/purchase`,
      data
    );
  },

  release: async (
    workspaceId: string,
    phoneNumberId: string
  ): Promise<{ success: boolean }> => {
    return apiDelete<{ success: boolean }>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/${phoneNumberId}`
    );
  },

  sync: async (workspaceId: string): Promise<{ synced: number }> => {
    return apiPost<{ synced: number }>(
      `/api/v1/workspaces/${workspaceId}/phone-numbers/sync`,
      {}
    );
  },
};
