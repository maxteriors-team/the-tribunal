import { apiGet, apiPut } from "@/lib/api";

// Profile types
export interface UserProfile {
  id: number;
  email: string;
  full_name: string | null;
  phone_number: string | null;
  timezone: string;
  created_at: string;
}

export interface UpdateProfileRequest {
  full_name?: string | null;
  phone_number?: string | null;
  timezone?: string | null;
}

// Notification types
export interface NotificationSettings {
  notification_email: boolean;
  notification_sms: boolean;
  notification_push: boolean;
}

export interface UpdateNotificationRequest {
  notification_email?: boolean;
  notification_sms?: boolean;
  notification_push?: boolean;
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
  role: string;
  created_at: string;
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
};
