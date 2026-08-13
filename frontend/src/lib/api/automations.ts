import { apiGet, apiPost } from "@/lib/api";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";
import type { Automation, AutomationActionType, AutomationTriggerType } from "@/types";

// Backend response types
export interface AutomationAction {
  /** Stable step id; omitted by the backend unless a branch targets the step. */
  id?: string;
  type: AutomationActionType;
  config: Record<string, unknown>;
}

export interface AutomationResponse {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  trigger_type: AutomationTriggerType;
  trigger_config: Record<string, unknown>;
  actions: AutomationAction[];
  is_active: boolean;
  last_triggered_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationsListParams {
  page?: number;
  page_size?: number;
  active_only?: boolean;
  [key: string]: unknown;
}

export interface AutomationsListResponse {
  items: AutomationResponse[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateAutomationRequest {
  name: string;
  description?: string;
  trigger_type?: AutomationTriggerType;
  trigger_config?: Record<string, unknown>;
  actions?: AutomationAction[];
  is_active?: boolean;
}

export interface UpdateAutomationRequest {
  name?: string;
  description?: string;
  trigger_type?: AutomationTriggerType;
  trigger_config?: Record<string, unknown>;
  actions?: AutomationAction[];
  is_active?: boolean;
}

// Transform backend response to frontend type
function transformAutomation(raw: unknown): Automation {
  const response = raw as AutomationResponse;
  return {
    id: response.id,
    name: response.name,
    description: response.description ?? undefined,
    trigger_type: response.trigger_type,
    trigger_config: response.trigger_config,
    // Step ids are load-bearing: a branch's then_goto/else_goto names one, and
    // dropping it here would make every saved branch dangle on the next edit.
    actions: response.actions.map((action) => ({
      ...(action.id ? { id: action.id } : {}),
      type: action.type,
      config: action.config,
    })),
    is_active: response.is_active,
    last_triggered_at: response.last_triggered_at ?? undefined,
    created_at: response.created_at,
    updated_at: response.updated_at,
  };
}

// Create base API client using factory
const baseAutomationsApi = createApiClient<
  Automation,
  CreateAutomationRequest,
  UpdateAutomationRequest
>({
  resourcePath: "automations",
  transform: transformAutomation,
}) as FullApiClient<Automation, CreateAutomationRequest, UpdateAutomationRequest>;

export interface AutomationStatsResponse {
  total: number;
  active: number;
  triggered_today: number;
}

// Automations API
export const automationsApi = {
  ...baseAutomationsApi,

  getStats: async (workspaceId: string): Promise<AutomationStatsResponse> => {
    return apiGet<AutomationStatsResponse>(
      `/api/v1/workspaces/${workspaceId}/automations/stats`
    );
  },

  toggle: async (workspaceId: string, automationId: string): Promise<Automation> => {
    const data = await apiPost<AutomationResponse>(
      `/api/v1/workspaces/${workspaceId}/automations/${automationId}/toggle`
    );
    return transformAutomation(data);
  },
};
