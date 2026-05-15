import { apiPost } from "@/lib/api";
import { createApiClient } from "./create-api-client";

export interface IntegrationWithMaskedCredentials {
  id: string;
  workspace_id: string;
  integration_type: "calcom" | "telnyx" | "openai" | "sendgrid" | "resend" | "lob";
  is_active: boolean;
  created_at: string;
  updated_at: string;
  masked_credentials: Record<string, string>;
}

export interface CreateIntegrationRequest {
  integration_type: "calcom" | "telnyx" | "openai" | "sendgrid" | "resend" | "lob";
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

  // Custom method for testing integrations
  test: async (
    workspaceId: string,
    integrationType: string
  ): Promise<IntegrationTestResult> => {
    return apiPost<IntegrationTestResult>(
      `/api/v1/workspaces/${workspaceId}/integrations/${integrationType}/test`
    );
  },
};
