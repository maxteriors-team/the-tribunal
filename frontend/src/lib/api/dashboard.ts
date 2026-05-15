import { apiGet } from "@/lib/api";

export interface DashboardStats {
  total_contacts: number;
  active_campaigns: number;
  calls_today: number;
  messages_sent: number;
  contacts_change: string;
  campaigns_change: string;
  calls_change: string;
  messages_change: string;
}

export interface RecentActivity {
  id: string;
  type: "call" | "sms" | "campaign" | "booking";
  contact: string;
  initials: string;
  action: string;
  time: string;
  duration?: string;
}

export interface CampaignStat {
  id: string;
  name: string;
  type: string;
  progress: number;
  sent: number;
  total: number;
  status: string;
}

export interface AgentStat {
  id: string;
  name: string;
  calls: number;
  messages: number;
  success_rate: number;
}

export interface TodayOverview {
  completed: number;
  pending: number;
  failed: number;
}

export interface AppointmentStats {
  appointments_today: number;
  appointments_this_week: number;
  /** null when fewer than 5 completed+no_show appointments in last 30 days */
  show_up_rate_30d: number | null;
  no_shows_30d: number;
  completed_30d: number;
}

export interface DashboardResponse {
  stats: DashboardStats;
  recent_activity: RecentActivity[];
  campaign_stats: CampaignStat[];
  agent_stats: AgentStat[];
  today_overview: TodayOverview;
  appointment_stats: AppointmentStats;
}

export const dashboardApi = {
  getStats: async (workspaceId: string): Promise<DashboardResponse> => {
    return apiGet<DashboardResponse>(
      `/api/v1/workspaces/${workspaceId}/dashboard/stats`
    );
  },
};
