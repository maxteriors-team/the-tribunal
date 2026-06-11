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

export interface RevenueAttributionStat {
  id: string;
  name: string;
  won_value: number;
  pipeline_value: number;
  won_count: number;
}

export interface RevenueStats {
  currency: string;
  won_value: number;
  won_value_this_month: number;
  won_count: number;
  pipeline_value: number;
  open_count: number;
  lost_value: number;
  lost_count: number;
  appointments_booked_this_month: number;
  estimated_ai_cost_this_month: number;
  /** null when estimated AI cost this month is 0 */
  roi_multiple: number | null;
  by_agent: RevenueAttributionStat[];
  by_campaign: RevenueAttributionStat[];
  by_prompt_version: RevenueAttributionStat[];
}

export interface SpeedToLeadStats {
  window_days: number;
  sla_seconds: number;
  leads_measured: number;
  within_sla: number;
  /** null when no leads measured in window */
  pct_within_sla: number | null;
  avg_response_seconds: number | null;
  median_response_seconds: number | null;
  fastest_response_seconds: number | null;
}

export interface ReviewsStats {
  average_rating: number;
  total_reviews: number;
  reputation_score: number;
  new_count: number;
  public_reviews: number;
  private_feedback: number;
  requests_sent: number;
  requests_rated: number;
  response_rate: number;
}

export interface DealCoachDealStat {
  opportunity_id: string;
  name: string;
  deal_health: string;
  top_risk: string;
  amount_at_risk: number;
  currency: string;
}

export interface DealCoachStats {
  open_deals: number;
  at_risk_count: number;
  critical_count: number;
  watch_count: number;
  next_best_action_count: number;
  total_amount_at_risk: number;
  currency: string;
  top_deals: DealCoachDealStat[];
}

export interface RoleplayStats {
  total_runs: number;
  runs_this_week: number;
  completed_runs: number;
  /** null when no completed runs */
  avg_overall_score: number | null;
  /** relative time of the most recent run, null when none */
  last_run_at: string | null;
}

export interface KnowledgeBaseStats {
  total_documents: number;
  active_documents: number;
  total_chunks: number;
  total_tokens: number;
  agents_with_knowledge: number;
}

export interface DashboardResponse {
  stats: DashboardStats;
  recent_activity: RecentActivity[];
  campaign_stats: CampaignStat[];
  agent_stats: AgentStat[];
  today_overview: TodayOverview;
  appointment_stats: AppointmentStats;
  revenue_stats: RevenueStats;
  speed_to_lead_stats: SpeedToLeadStats;
  reviews_stats: ReviewsStats;
  deal_coach_stats: DealCoachStats;
  roleplay_stats: RoleplayStats;
  knowledge_base_stats: KnowledgeBaseStats;
}

export type TodayQueueKind =
  | "replies_waiting"
  | "appointments_today"
  | "approvals"
  | "hot_nudges"
  | "prospect_batch"
  | "draft_campaign"
  | "setup_gap";

export interface TodayQueueItem {
  id: string;
  kind: TodayQueueKind;
  priority: number;
  title: string;
  body: string;
  count: number;
  cta_label: string;
  href: string;
  payload: Record<string, unknown>;
}

export interface TodayQueueResponse {
  items: TodayQueueItem[];
  generated_at: string;
}

export const dashboardApi = {
  getStats: async (workspaceId: string): Promise<DashboardResponse> => {
    return apiGet<DashboardResponse>(
      `/api/v1/workspaces/${workspaceId}/dashboard/stats`
    );
  },
  getTodayQueue: async (workspaceId: string): Promise<TodayQueueResponse> => {
    return apiGet<TodayQueueResponse>(
      `/api/v1/workspaces/${workspaceId}/dashboard/today-queue`
    );
  },
};
