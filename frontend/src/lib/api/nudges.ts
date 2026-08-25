import { apiGet, apiPut } from "@/lib/api";
import type {
  HumanNudge,
  NudgeClearAllResponse,
  NudgeListResponse,
  NudgeStats,
  NudgeSettings,
  UpdateNudgeSettings,
  NudgeStatus,
  NudgeType,
  NudgePriority,
} from "@/types/nudge";

export interface NudgeListParams {
  page?: number;
  page_size?: number;
  status?: NudgeStatus;
  nudge_type?: NudgeType;
  priority?: NudgePriority;
}

export const nudgesApi = {
  list: async (workspaceId: string, params: NudgeListParams = {}): Promise<NudgeListResponse> => {
    return apiGet<NudgeListResponse>(`/api/v1/workspaces/${workspaceId}/nudges`, { params });
  },

  getStats: async (workspaceId: string): Promise<NudgeStats> => {
    return apiGet<NudgeStats>(`/api/v1/workspaces/${workspaceId}/nudges/stats`);
  },

  clearAll: async (workspaceId: string): Promise<NudgeClearAllResponse> => {
    return apiPut<NudgeClearAllResponse>(`/api/v1/workspaces/${workspaceId}/nudges/clear-all`);
  },

  act: async (workspaceId: string, nudgeId: string, actionTaken?: string): Promise<HumanNudge> => {
    return apiPut<HumanNudge>(
      `/api/v1/workspaces/${workspaceId}/nudges/${nudgeId}/act`,
      actionTaken ? { action_taken: actionTaken } : undefined,
    );
  },

  dismiss: async (workspaceId: string, nudgeId: string): Promise<HumanNudge> => {
    return apiPut<HumanNudge>(`/api/v1/workspaces/${workspaceId}/nudges/${nudgeId}/dismiss`);
  },

  snooze: async (
    workspaceId: string,
    nudgeId: string,
    snoozeUntil: string,
  ): Promise<HumanNudge> => {
    return apiPut<HumanNudge>(`/api/v1/workspaces/${workspaceId}/nudges/${nudgeId}/snooze`, {
      snooze_until: snoozeUntil,
    });
  },

  getSettings: async (workspaceId: string): Promise<NudgeSettings> => {
    return apiGet<NudgeSettings>(`/api/v1/workspaces/${workspaceId}/nudge-settings`);
  },

  updateSettings: async (
    workspaceId: string,
    data: UpdateNudgeSettings,
  ): Promise<NudgeSettings> => {
    return apiPut<NudgeSettings>(`/api/v1/workspaces/${workspaceId}/nudge-settings`, data);
  },
};
