import { apiGet, apiPost, apiPatch, apiDelete } from "@/lib/api";
import { createApiClient } from "@/lib/api/create-api-client";
import type {
  Conversation,
  FollowupGenerateResponse,
  FollowupSendResponse,
  FollowupSettings,
  Message,
} from "@/types";

export interface ConversationsListParams {
  page?: number;
  page_size?: number;
  status?: "active" | "archived" | "blocked";
  channel?: string;
  unread_only?: boolean;
  [key: string]: unknown;
}

export interface ConversationsListResponse {
  items: Conversation[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** Workspace-wide unread rollup that backs the header chat badge. */
export interface UnreadSummary {
  unread_conversations: number;
  unread_messages: number;
}

export interface MarkAllReadResponse {
  conversations_marked: number;
}

export interface TeachAIRequest {
  source_message_id: string;
  ideal_response: string;
  note?: string;
}

export interface TeachAIResponse {
  id: string;
  workspace_id: string;
  agent_id: string;
  conversation_id: string | null;
  source_message_id: string | null;
  ideal_response: string;
  note: string | null;
  is_active: boolean;
  agent_name: string;
  created_at: string;
  updated_at: string;
}

export interface SendMessageRequest {
  contact_id: number;
  body: string;
  channel: "sms" | "email";
  from_number?: string;
  to_number?: string;
}

// Create base API client with standard CRUD methods (list, get only - no create/update/delete)
const baseConversationsApi = createApiClient<Conversation, never, never>({
  resourcePath: "conversations",
  includeCreate: false,
  includeUpdate: false,
  includeDelete: false,
});

// Type assertion to ensure get is non-optional since we enabled it
const baseConversationsApiWithGet = baseConversationsApi as {
  list: typeof baseConversationsApi.list;
  get: NonNullable<typeof baseConversationsApi.get>;
};

export const conversationsApi = {
  ...baseConversationsApiWithGet,

  getMessages: async (workspaceId: string, conversationId: string): Promise<Message[]> => {
    return apiGet<Message[]>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
    );
  },

  sendMessage: async (
    workspaceId: string,
    conversationId: string,
    body: string,
  ): Promise<Message> => {
    return apiPost<Message>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`,
      { body },
    );
  },

  teachAI: async (
    workspaceId: string,
    conversationId: string,
    request: TeachAIRequest,
  ): Promise<TeachAIResponse> => {
    return apiPost<TeachAIResponse>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/teach-ai`,
      request,
    );
  },

  /** Unread rollup for the whole workspace (one aggregate query server-side). */
  getUnreadSummary: async (workspaceId: string): Promise<UnreadSummary> => {
    return apiGet<UnreadSummary>(`/api/v1/workspaces/${workspaceId}/conversations/unread`);
  },

  /** Clear one thread's unread counter. Returns the updated thread. */
  markRead: async (workspaceId: string, conversationId: string): Promise<Conversation> => {
    return apiPost<Conversation>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/read`,
    );
  },

  /** Clear every unread thread in the workspace. */
  markAllRead: async (workspaceId: string): Promise<MarkAllReadResponse> => {
    return apiPost<MarkAllReadResponse>(`/api/v1/workspaces/${workspaceId}/conversations/read`);
  },

  toggleAI: async (
    workspaceId: string,
    conversationId: string,
    enabled: boolean,
  ): Promise<{ ai_enabled: boolean }> => {
    return apiPost<{ ai_enabled: boolean }>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/ai/toggle`,
      { enabled },
    );
  },

  /**
   * Send a message to a contact (creates/gets conversation automatically)
   * This is the recommended way to send messages from the conversation feed.
   */
  sendMessageToContact: async (
    workspaceId: string,
    contactId: number,
    body: string,
    fromNumber?: string,
    imageDataUrl?: string,
  ): Promise<Message> => {
    return apiPost<Message>(`/api/v1/workspaces/${workspaceId}/contacts/${contactId}/messages`, {
      body,
      from_number: fromNumber,
      image_data_url: imageDataUrl,
    });
  },

  assignAgent: async (
    workspaceId: string,
    conversationId: string,
    agentId: string | null,
  ): Promise<{ assigned_agent_id: string | null }> => {
    return apiPost<{ assigned_agent_id: string | null }>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/assign`,
      { agent_id: agentId },
    );
  },

  clearHistory: async (workspaceId: string, conversationId: string): Promise<void> => {
    await apiDelete(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`);
  },

  // Follow-up methods
  getFollowupSettings: async (
    workspaceId: string,
    conversationId: string,
  ): Promise<FollowupSettings> => {
    return apiGet<FollowupSettings>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/followup/status`,
    );
  },

  updateFollowupSettings: async (
    workspaceId: string,
    conversationId: string,
    settings: Partial<{
      enabled: boolean;
      delay_hours: number;
      max_count: number;
    }>,
  ): Promise<FollowupSettings> => {
    return apiPatch<FollowupSettings>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/followup/settings`,
      settings,
    );
  },

  generateFollowup: async (
    workspaceId: string,
    conversationId: string,
    customInstructions?: string,
  ): Promise<FollowupGenerateResponse> => {
    return apiPost<FollowupGenerateResponse>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/followup/generate`,
      { custom_instructions: customInstructions },
    );
  },

  sendFollowup: async (
    workspaceId: string,
    conversationId: string,
    message?: string,
    customInstructions?: string,
  ): Promise<FollowupSendResponse> => {
    return apiPost<FollowupSendResponse>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/followup/send`,
      { message, custom_instructions: customInstructions },
    );
  },

  resetFollowupCounter: async (
    workspaceId: string,
    conversationId: string,
  ): Promise<{ count_sent: number }> => {
    return apiPost<{ count_sent: number }>(
      `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/followup/reset`,
    );
  },
};
