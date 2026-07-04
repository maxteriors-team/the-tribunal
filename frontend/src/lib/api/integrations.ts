import { apiDelete, apiGet, apiPost } from "@/lib/api";

import { createApiClient } from "./create-api-client";

export interface IntegrationWithMaskedCredentials {
  id: string;
  workspace_id: string;
  integration_type:
    | "calcom"
    | "telnyx"
    | "openai"
    | "sendgrid"
    | "resend"
    | "lob"
    | "companycam";
  is_active: boolean;
  created_at: string;
  updated_at: string;
  masked_credentials: Record<string, string>;
}

export interface CreateIntegrationRequest {
  integration_type:
    | "calcom"
    | "telnyx"
    | "openai"
    | "sendgrid"
    | "resend"
    | "lob"
    | "companycam";
  credentials: Record<string, string>;
  is_active?: boolean;
}

export interface UpdateIntegrationRequest {
  credentials?: Record<string, string>;
  is_active?: boolean;
}

export interface IntegrationTestResult {
  success: boolean;
  message: string;
  details?: Record<string, unknown>;
}

export interface OpenAIOAuthStatus {
  connected: boolean;
  account_id?: string | null;
  email?: string | null;
  expires_at?: number | null;
  saved_at?: string | null;
  auth_method?: string | null;
  plan_type?: string | null;
  api_key_configured: boolean;
  realtime_model: string;
}

export interface OpenAIOAuthStartResponse {
  method: "browser" | "device_code";
  expires_at: number;
  authorization_url?: string | null;
  redirect_uri?: string | null;
  verification_url?: string | null;
  user_code?: string | null;
  poll_token?: string | null;
  poll_interval_seconds: number;
}

export interface OpenAIOAuthDevicePollResponse {
  pending: boolean;
  status: OpenAIOAuthStatus;
}

// Base API client using the factory for standard CRUD operations
const baseIntegrationsApi = createApiClient<
  IntegrationWithMaskedCredentials,
  CreateIntegrationRequest,
  UpdateIntegrationRequest
>({
  resourcePath: "integrations",
  // Integrations list returns an array, not paginated response
  transformList: (raw) => {
    const items = raw as IntegrationWithMaskedCredentials[];
    return {
      items,
      total: items.length,
      page: 1,
      page_size: items.length,
      pages: 1,
    };
  },
});

export const integrationsApi = {
  // Standard CRUD from factory - re-export list as array to match existing API
  list: async (workspaceId: string): Promise<IntegrationWithMaskedCredentials[]> => {
    const result = await baseIntegrationsApi.list(workspaceId);
    return result.items;
  },

  get: baseIntegrationsApi.get!,
  create: baseIntegrationsApi.create!,
  update: baseIntegrationsApi.update!,
  delete: baseIntegrationsApi.delete!,

  // Custom method for testing integrations.
  // Pass `credentials` to validate candidate values from the form before they
  // are persisted; omit them to test the workspace's stored credentials.
  test: async (
    workspaceId: string,
    integrationType: string,
    credentials?: Record<string, string>
  ): Promise<IntegrationTestResult> => {
    return apiPost<IntegrationTestResult>(
      `/api/v1/workspaces/${workspaceId}/integrations/${integrationType}/test`,
      credentials ? { credentials } : undefined
    );
  },

  getOpenAIOAuthStatus: async (workspaceId: string): Promise<OpenAIOAuthStatus> => {
    return apiGet<OpenAIOAuthStatus>(
      `/api/v1/workspaces/${workspaceId}/integrations/openai/oauth/status`
    );
  },

  startOpenAIOAuth: async (workspaceId: string): Promise<OpenAIOAuthStartResponse> => {
    return apiPost<OpenAIOAuthStartResponse>(
      `/api/v1/workspaces/${workspaceId}/integrations/openai/oauth/start`
    );
  },

  pollOpenAIOAuthDeviceCode: async (
    workspaceId: string,
    pollToken: string
  ): Promise<OpenAIOAuthDevicePollResponse> => {
    return apiPost<OpenAIOAuthDevicePollResponse>(
      `/api/v1/workspaces/${workspaceId}/integrations/openai/oauth/device/poll`,
      { poll_token: pollToken }
    );
  },

  disconnectOpenAIOAuth: async (workspaceId: string): Promise<OpenAIOAuthStatus> => {
    return apiDelete<OpenAIOAuthStatus>(
      `/api/v1/workspaces/${workspaceId}/integrations/openai/oauth`
    );
  },
};
