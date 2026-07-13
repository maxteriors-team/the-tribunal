import { apiGet, apiPut } from "@/lib/api";

// Profile types
export interface UserProfile {
  id: number;
  email: string;
  full_name: string | null;
  phone_number: string | null;
  timezone: string;
  avatar_url: string | null;
  created_at: string;
}

export interface UpdateProfileRequest {
  full_name?: string | null;
  phone_number?: string | null;
  timezone?: string | null;
  avatar_url?: string | null;
}

// Notification types
export interface NotificationSettings {
  notification_email: boolean;
  notification_sms: boolean;
  notification_push: boolean;
  notification_push_calls: boolean;
  notification_push_messages: boolean;
  notification_push_voicemail: boolean;
  notification_push_appointments: boolean;
  notification_push_reviews: boolean;
  notification_push_deal_alerts: boolean;
  notification_push_missed_call_textback: boolean;
  notification_push_roleplay: boolean;
  notification_push_automations: boolean;
  notification_push_new_lead: boolean;
}

export interface UpdateNotificationRequest {
  notification_email?: boolean;
  notification_sms?: boolean;
  notification_push?: boolean;
  notification_push_calls?: boolean;
  notification_push_messages?: boolean;
  notification_push_voicemail?: boolean;
  notification_push_appointments?: boolean;
  notification_push_reviews?: boolean;
  notification_push_deal_alerts?: boolean;
  notification_push_missed_call_textback?: boolean;
  notification_push_roleplay?: boolean;
  notification_push_automations?: boolean;
  notification_push_new_lead?: boolean;
}

// Integration types
export interface IntegrationStatus {
  integration_type: string;
  is_connected: boolean;
  display_name: string;
  description: string;
}

export interface IntegrationsResponse {
  integrations: IntegrationStatus[];
}

// Team types
export interface TeamMember {
  id: number;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  role: string;
  created_at: string;
}

// Speed-to-lead SLA types
export interface SpeedToLeadSettings {
  enabled: boolean;
  sla_seconds: number;
  alert_enabled: boolean;
  badge_enabled: boolean;
  badge_window_days: number;
}

export interface UpdateSpeedToLeadRequest {
  enabled?: boolean;
  sla_seconds?: number;
  alert_enabled?: boolean;
  badge_enabled?: boolean;
  badge_window_days?: number;
}

export interface SpeedToLeadMetrics {
  window_days: number;
  sla_seconds: number;
  leads_measured: number;
  within_sla: number;
  pct_within_sla: number | null;
  avg_response_seconds: number | null;
  median_response_seconds: number | null;
  fastest_response_seconds: number | null;
}

// Missed-call text-back types
export interface MissedCallTextbackSettings {
  enabled: boolean;
  template: string;
  quiet_hours_start: string | null;
  quiet_hours_end: string | null;
  timezone: string | null;
}

export interface UpdateMissedCallTextbackRequest {
  enabled?: boolean;
  template?: string;
  quiet_hours_start?: string | null;
  quiet_hours_end?: string | null;
  timezone?: string | null;
}

export const settingsApi = {
  // Profile endpoints
  getProfile: async (): Promise<UserProfile> => {
    return apiGet<UserProfile>("/api/v1/settings/users/me/profile");
  },

  updateProfile: async (data: UpdateProfileRequest): Promise<UserProfile> => {
    return apiPut<UserProfile>("/api/v1/settings/users/me/profile", data);
  },

  // Notification endpoints
  getNotifications: async (): Promise<NotificationSettings> => {
    return apiGet<NotificationSettings>("/api/v1/settings/users/me/notifications");
  },

  updateNotifications: async (data: UpdateNotificationRequest): Promise<NotificationSettings> => {
    return apiPut<NotificationSettings>("/api/v1/settings/users/me/notifications", data);
  },

  // Workspace integrations
  getIntegrations: async (workspaceId: string): Promise<IntegrationsResponse> => {
    return apiGet<IntegrationsResponse>(
      `/api/v1/settings/workspaces/${workspaceId}/integrations`
    );
  },

  // Team members
  getTeamMembers: async (workspaceId: string): Promise<TeamMember[]> => {
    return apiGet<TeamMember[]>(
      `/api/v1/settings/workspaces/${workspaceId}/team`
    );
  },

  // Speed-to-lead SLA
  getSpeedToLead: async (workspaceId: string): Promise<SpeedToLeadSettings> => {
    return apiGet<SpeedToLeadSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/speed-to-lead`
    );
  },

  updateSpeedToLead: async (
    workspaceId: string,
    data: UpdateSpeedToLeadRequest
  ): Promise<SpeedToLeadSettings> => {
    return apiPut<SpeedToLeadSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/speed-to-lead`,
      data
    );
  },

  getSpeedToLeadMetrics: async (
    workspaceId: string
  ): Promise<SpeedToLeadMetrics> => {
    return apiGet<SpeedToLeadMetrics>(
      `/api/v1/settings/workspaces/${workspaceId}/speed-to-lead/metrics`
    );
  },

  // Missed-call text-back
  getMissedCallTextback: async (
    workspaceId: string
  ): Promise<MissedCallTextbackSettings> => {
    return apiGet<MissedCallTextbackSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/missed-call-textback`
    );
  },

  updateMissedCallTextback: async (
    workspaceId: string,
    data: UpdateMissedCallTextbackRequest
  ): Promise<MissedCallTextbackSettings> => {
    return apiPut<MissedCallTextbackSettings>(
      `/api/v1/settings/workspaces/${workspaceId}/missed-call-textback`,
      data
    );
  },
};
