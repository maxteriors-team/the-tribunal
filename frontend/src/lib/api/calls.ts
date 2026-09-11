import { api, apiGet, apiPost } from "@/lib/api";
import type { CallRecord } from "@/types";

export interface CallsListParams {
  page?: number;
  page_size?: number;
  direction?: "inbound" | "outbound";
  status?: string;
  search?: string;
}

/** Who talks to the contact on an outbound call. */
export type CallMode = "ai" | "user" | "browser";

export interface WebRTCTokenResponse {
  token: string;
}

export interface InitiateCallRequest {
  to_number: string;
  from_phone_number: string;
  contact_phone?: string;
  /** Voice agent for mode="ai". Ignored for human modes. */
  agent_id?: string;
  /** AI, phone callback, or authenticated browser headset. */
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

function presencePath(workspaceId: string): string {
  return `/api/v1/workspaces/${workspaceId}/calls/presence`;
}

export const callsApi = {
  list: async (workspaceId: string, params: CallsListParams = {}): Promise<CallsListResponse> => {
    return apiGet<CallsListResponse>(`/api/v1/workspaces/${workspaceId}/calls`, { params });
  },

  get: async (workspaceId: string, id: string): Promise<CallRecord> => {
    return apiGet<CallRecord>(`/api/v1/workspaces/${workspaceId}/calls/${id}`);
  },

  getWebRTCToken: async (workspaceId: string): Promise<WebRTCTokenResponse> => {
    return apiPost<WebRTCTokenResponse>(`/api/v1/workspaces/${workspaceId}/calls/webrtc/token`);
  },

  initiate: async (
    workspaceId: string,
    data: InitiateCallRequest,
  ): Promise<InitiateCallResponse> => {
    return apiPost<InitiateCallResponse>(`/api/v1/workspaces/${workspaceId}/calls`, data);
  },

  hangup: async (workspaceId: string, callId: string): Promise<{ success: boolean }> => {
    return apiPost<{ success: boolean }>(
      `/api/v1/workspaces/${workspaceId}/calls/${callId}/hangup`,
    );
  },

  listLive: async (workspaceId: string): Promise<LiveCallsResponse> => {
    return apiGet<LiveCallsResponse>(`/api/v1/workspaces/${workspaceId}/calls/live`);
  },

  /**
   * Tell the backend whether this browser can take an inbound call right now.
   *
   * Presence expires server-side after 75s, so a registered dashboard
   * re-publishes well inside that window. A failed beat is deliberately not
   * fatal — dropping the operator out of the ring group on one flaky request
   * would silently stop customer calls from reaching a human.
   */
  publishPresence: async (workspaceId: string, available: boolean): Promise<void> => {
    await apiPost<void>(presencePath(workspaceId), { available });
  },

  /**
   * Best-effort presence clear while the page is going away.
   *
   * An in-flight XHR is cancelled when the document unloads, which would leave
   * the operator advertised as available until the TTL expires and ring a tab
   * that no longer exists. `sendBeacon` is queued by the browser and survives
   * teardown; where it is missing we still try a normal post.
   */
  publishPresenceBeacon: (workspaceId: string, available: boolean): void => {
    const path = presencePath(workspaceId);
    const body = JSON.stringify({ available });
    if (typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
      // Same-origin (requests are proxied through Next), so the auth cookies ride along.
      const url = `${api.defaults.baseURL ?? ""}${path}`;
      const queued = navigator.sendBeacon(url, new Blob([body], { type: "application/json" }));
      if (queued) return;
    }
    void apiPost<void>(path, { available }).catch(() => undefined);
  },
};
