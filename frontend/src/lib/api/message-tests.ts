import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  MessageTest,
  MessageTestAnalytics,
  TestContact,
  TestVariant,
} from "@/types";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";

// Request Types
export interface MessageTestsListParams {
  page?: number;
  page_size?: number;
  status_filter?: string;
}

export interface MessageTestsListResponse {
  items: MessageTest[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateMessageTestRequest {
  name: string;
  description?: string;
  from_phone_number: string;
  use_number_pool?: boolean;
  agent_id?: string;
  ai_enabled?: boolean;
  qualification_criteria?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone?: string;
  messages_per_minute?: number;
  variants?: CreateVariantRequest[];
}

export interface UpdateMessageTestRequest {
  name?: string;
  description?: string;
  from_phone_number?: string;
  use_number_pool?: boolean;
  agent_id?: string;
  ai_enabled?: boolean;
  qualification_criteria?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone?: string;
  messages_per_minute?: number;
}

export interface CreateVariantRequest {
  name: string;
  message_template: string;
  is_control?: boolean;
  sort_order?: number;
}

export interface UpdateVariantRequest {
  name?: string;
  message_template?: string;
  is_control?: boolean;
  sort_order?: number;
}

export interface AddContactsRequest {
  contact_ids: number[];
}

export interface SelectWinnerRequest {
  variant_id: string;
}

export interface ConvertToCampaignRequest {
  campaign_name: string;
  use_winning_message?: boolean;
  include_remaining_contacts?: boolean;
}

const baseApi = createApiClient<MessageTest, CreateMessageTestRequest, UpdateMessageTestRequest>({
  resourcePath: "message-tests",
}) as FullApiClient<MessageTest, CreateMessageTestRequest, UpdateMessageTestRequest>;

// Message Tests API
export const messageTestsApi = {
  ...baseApi,

  // List variants for a test
  listVariants: async (
    workspaceId: string,
    testId: string
  ): Promise<TestVariant[]> => {
    return apiGet<TestVariant[]>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/variants`
    );
  },

  // Create a variant
  createVariant: async (
    workspaceId: string,
    testId: string,
    data: CreateVariantRequest
  ): Promise<TestVariant> => {
    return apiPost<TestVariant>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/variants`,
      data
    );
  },

  // Update a variant
  updateVariant: async (
    workspaceId: string,
    testId: string,
    variantId: string,
    data: UpdateVariantRequest
  ): Promise<TestVariant> => {
    return apiPut<TestVariant>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/variants/${variantId}`,
      data
    );
  },

  // Delete a variant
  deleteVariant: async (
    workspaceId: string,
    testId: string,
    variantId: string
  ): Promise<void> => {
    await apiDelete(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/variants/${variantId}`
    );
  },

  // Add contacts to test
  addContacts: async (
    workspaceId: string,
    testId: string,
    data: AddContactsRequest
  ): Promise<{ added: number }> => {
    return apiPost<{ added: number }>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/contacts`,
      data
    );
  },

  // List test contacts
  listContacts: async (
    workspaceId: string,
    testId: string,
    statusFilter?: string,
    limit?: number
  ): Promise<TestContact[]> => {
    return apiGet<TestContact[]>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/contacts`,
      { params: { status_filter: statusFilter, limit } }
    );
  },

  // Start a test
  start: async (
    workspaceId: string,
    testId: string
  ): Promise<{ status: string; message: string }> => {
    return apiPost<{ status: string; message: string }>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/start`
    );
  },

  // Pause a test
  pause: async (
    workspaceId: string,
    testId: string
  ): Promise<{ status: string }> => {
    return apiPost<{ status: string }>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/pause`
    );
  },

  // Complete a test
  complete: async (
    workspaceId: string,
    testId: string
  ): Promise<{ status: string }> => {
    return apiPost<{ status: string }>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/complete`
    );
  },

  // Get analytics
  getAnalytics: async (
    workspaceId: string,
    testId: string
  ): Promise<MessageTestAnalytics> => {
    return apiGet<MessageTestAnalytics>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/analytics`
    );
  },

  // Select winner
  selectWinner: async (
    workspaceId: string,
    testId: string,
    data: SelectWinnerRequest
  ): Promise<MessageTest> => {
    return apiPost<MessageTest>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/select-winner`,
      data
    );
  },

  // Convert to campaign
  convertToCampaign: async (
    workspaceId: string,
    testId: string,
    data: ConvertToCampaignRequest
  ): Promise<{ campaign_id: string; message: string }> => {
    return apiPost<{ campaign_id: string; message: string }>(
      `/api/v1/workspaces/${workspaceId}/message-tests/${testId}/convert-to-campaign`,
      data
    );
  },
};
