import { createApiClient, type ResourceId } from "@/lib/api/create-api-client";
import type { PaginatedResponse } from "@/types/api";
import type { MessageTemplate } from "@/types";

// Request Types
export interface MessageTemplatesListParams {
  page?: number;
  page_size?: number;
  [key: string]: unknown;
}

export interface MessageTemplatesListResponse {
  items: MessageTemplate[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateMessageTemplateRequest {
  name: string;
  message_template: string;
}

export interface UpdateMessageTemplateRequest {
  name?: string;
  message_template?: string;
}

// API client type with only list, create, and delete methods
export interface MessageTemplatesApiClient {
  list: (workspaceId: string, params?: Record<string, unknown>) => Promise<PaginatedResponse<MessageTemplate>>;
  create: (workspaceId: string, data: CreateMessageTemplateRequest) => Promise<MessageTemplate>;
  delete: (workspaceId: string, id: ResourceId) => Promise<void>;
}

// Create base API client using factory (list, create, delete only - no get or update)
const baseMessageTemplatesApi = createApiClient<
  MessageTemplate,
  CreateMessageTemplateRequest,
  UpdateMessageTemplateRequest
>({
  resourcePath: "message-templates",
  includeGet: false,
  includeUpdate: false,
}) as MessageTemplatesApiClient;

// Message Templates API
export const messageTemplatesApi = baseMessageTemplatesApi;
