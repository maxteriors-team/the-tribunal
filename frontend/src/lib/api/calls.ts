import { apiGet, apiPost } from "@/lib/api";
import type { CallRecord } from "@/types";

export interface CallsListParams {
  page?: number;
  page_size?: number;
  direction?: "inbound" | "outbound";
  status?: string;
  search?: string;
}

/** Who talks to the contact on an outbound call. */
export type CallMode = "ai" | "user";

export interface InitiateCallRequest {
  to_number: string;
  from_phone_number: string;
  contact_phone?: string;
  /** Voice agent for mode="ai". Ignored when mode="user". */
  agent_id?: string;
  /** "ai" (default) hands the call to a voice agent; "user" rings your phone first. */
  mode?: CallMode;
  /**
   * Number to ring for mode="user". Must be your profile phone, the workspace
   * transfer destination, or a workspace number — anything else is rejected.
   */
  user_phone_number?: string;
}

export interface InitiateCallResponse {
  id: string;
  conversation_id: string;
  direction: string;
  channel: string;
  status: string;
  duration_seconds: number | null;
  recording_url: string | null;
  transcript: string | null;
  created_at: string;
}

export interface CallsListResponse {
  items: CallRecord[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  completed_count: number;
  total_duration_seconds: number;
}

export interface LiveCall {
  call_id: string;
  workspace_id: string;
  direction: string;
  agent_name: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  started_at: string;
  duration_seconds: number;
  supervisor_count: number;
  barged: boolean;
}

export interface LiveCallsResponse {
  items: LiveCall[];
}

export interface CallStatsResponse {
  total_calls: number;
  completed_calls: number;
  inbound_calls: number;
  outbound_calls: number;
  total_duration_seconds: number;
  average_duration_seconds: number;
}

export const callsApi = {
  list: async (workspaceId: string, params: CallsListParams = {}): Promise<CallsListResponse> => {
    return apiGet<CallsListResponse>(
      `/api/v1/workspaces/${workspaceId}/calls`,
      { params }
    );
  },

  get: async (workspaceId: string, id: string): Promise<CallRecord> => {
    return apiGet<CallRecord>(
      `/api/v1/workspaces/${workspaceId}/calls/${id}`
    );
  },

  initiate: async (
    workspaceId: string,
    data: InitiateCallRequest
  ): Promise<InitiateCallResponse> => {
    return apiPost<InitiateCallResponse>(
      `/api/v1/workspaces/${workspaceId}/calls`,
      data
    );
  },

  hangup: async (workspaceId: string, callId: string): Promise<{ success: boolean }> => {
    return apiPost<{ success: boolean }>(
      `/api/v1/workspaces/${workspaceId}/calls/${callId}/hangup`
    );
  },

  listLive: async (workspaceId: string): Promise<LiveCallsResponse> => {
    return apiGet<LiveCallsResponse>(
      `/api/v1/workspaces/${workspaceId}/calls/live`
    );
  },
};
