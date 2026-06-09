import { apiGet, apiPut } from "@/lib/api";
import { createApiClient, type FullApiClient } from "@/lib/api/create-api-client";
import type { Agent } from "@/types/agent";

export type { Agent };

export interface AgentsListParams {
  page?: number;
  page_size?: number;
  active_only?: boolean;
}

export interface AgentsListResponse {
  items: Agent[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface CreateAgentRequest {
  name: string;
  description?: string;
  channel_mode?: string;
  voice_provider?: string;
  voice_id?: string;
  language?: string;
  system_prompt: string;
  temperature?: number;
  text_response_delay_ms?: number;
  text_max_context_messages?: number;
  calcom_event_type_id?: number;
  assignment_strategy?: string;
  enabled_tools?: string[];
  tool_settings?: Record<string, string[]>;
  // IVR navigation settings
  enable_ivr_navigation?: boolean;
  ivr_navigation_goal?: string;
  ivr_loop_threshold?: number;
  ivr_silence_duration_ms?: number;
  ivr_post_dtmf_cooldown_ms?: number;
  ivr_menu_buffer_silence_ms?: number;
  enable_recording?: boolean;
  // Live human transfer / handoff
  transfer_destination_number?: string | null;
  transfer_mode?: string;
  transfer_briefing_template?: string | null;
  reminder_enabled?: boolean;
  reminder_minutes_before?: number;
  reminder_offsets?: number[];
  reminder_template?: string | null;
  auto_evaluate?: boolean;
}

export interface UpdateAgentRequest {
  name?: string;
  description?: string;
  channel_mode?: string;
  voice_provider?: string;
  voice_id?: string;
  language?: string;
  system_prompt?: string;
  temperature?: number;
  text_response_delay_ms?: number;
  text_max_context_messages?: number;
  calcom_event_type_id?: number;
  assignment_strategy?: string;
  is_active?: boolean;
  enabled_tools?: string[];
  tool_settings?: Record<string, string[]>;
  // IVR navigation settings
  enable_ivr_navigation?: boolean;
  ivr_navigation_goal?: string;
  ivr_loop_threshold?: number;
  ivr_silence_duration_ms?: number;
  ivr_post_dtmf_cooldown_ms?: number;
  ivr_menu_buffer_silence_ms?: number;
  enable_recording?: boolean;
  // Live human transfer / handoff
  transfer_destination_number?: string | null;
  transfer_mode?: string;
  transfer_briefing_template?: string | null;
  reminder_enabled?: boolean;
  reminder_minutes_before?: number;
  reminder_offsets?: number[];
  reminder_template?: string | null;
  noshow_sms_enabled?: boolean;
  // No-show multi-day re-engagement sequence
  noshow_reengagement_enabled?: boolean;
  noshow_day3_template?: string | null;
  noshow_day7_template?: string | null;
  // Never-booked re-engagement
  never_booked_reengagement_enabled?: boolean;
  never_booked_delay_days?: number;
  never_booked_max_attempts?: number;
  never_booked_template?: string | null;
  value_reinforcement_enabled?: boolean;
  value_reinforcement_offset_minutes?: number;
  value_reinforcement_template?: string | null;
  // Post-meeting SMS
  post_meeting_sms_enabled?: boolean;
  post_meeting_template?: string | null;
  auto_evaluate?: boolean;
}

// Embed settings types
export interface EmbedSettings {
  button_text: string;
  theme: string;
  position: string;
  primary_color: string;
  mode: string;
  display: string;
}

export interface EmbedSettingsResponse {
  public_id: string | null;
  embed_enabled: boolean;
  allowed_domains: string[];
  embed_settings: EmbedSettings;
  embed_code: string | null;
}

export interface EmbedSettingsUpdate {
  embed_enabled?: boolean;
  allowed_domains?: string[];
  embed_settings?: Partial<EmbedSettings>;
}

// Agents API
const baseApi = createApiClient<Agent, CreateAgentRequest, UpdateAgentRequest>({
  resourcePath: "agents",
}) as FullApiClient<Agent, CreateAgentRequest, UpdateAgentRequest>;

export const agentsApi = {
  ...baseApi,

  getEmbedSettings: async (
    workspaceId: string,
    agentId: string,
  ): Promise<EmbedSettingsResponse> => {
    return apiGet<EmbedSettingsResponse>(
      `/api/v1/workspaces/${workspaceId}/agents/${agentId}/embed`,
    );
  },

  updateEmbedSettings: async (
    workspaceId: string,
    agentId: string,
    data: EmbedSettingsUpdate,
  ): Promise<EmbedSettingsResponse> => {
    return apiPut<EmbedSettingsResponse>(
      `/api/v1/workspaces/${workspaceId}/agents/${agentId}/embed`,
      data,
    );
  },
};
