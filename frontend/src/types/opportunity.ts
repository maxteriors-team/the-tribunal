// Pipeline & Opportunity types

export type PipelineStageType = "active" | "won" | "lost";
export type OpportunityStatus = "open" | "won" | "lost" | "abandoned";

export interface PipelineStage {
  id: string;
  pipeline_id: string;
  name: string;
  description?: string;
  order: number;
  probability: number; // 0-100
  stage_type: PipelineStageType;
  created_at: string;
  updated_at: string;
}

export interface Pipeline {
  id: string;
  workspace_id: string;
  name: string;
  description?: string;
  is_active: boolean;
  stages: PipelineStage[];
  created_at: string;
  updated_at: string;
}

export interface OpportunityLineItem {
  id: string;
  opportunity_id: string;
  name: string;
  description?: string;
  quantity: number;
  unit_price: number;
  discount: number;
  total: number;
  created_at: string;
  updated_at: string;
}

export interface OpportunityActivity {
  id: string;
  opportunity_id: string;
  activity_type: string;
  old_value?: string;
  new_value?: string;
  description?: string;
  created_at: string;
}

// Deal Coach types
export type DealHealthStatus = "healthy" | "watch" | "at_risk" | "critical";
export type CoachActionChannel = "sms" | "call" | "email" | "offer" | "task";
export type CoachGeneratedBy = "llm" | "heuristic";

export interface NextBestAction {
  title: string;
  rationale: string;
  channel: CoachActionChannel;
  timing: string;
}

export interface DraftedAction {
  action_type: string;
  channel: CoachActionChannel;
  description: string;
  body: string;
  payload: Record<string, unknown>;
}

export interface DealSignals {
  days_since_last_contact?: number | null;
  days_in_stage?: number | null;
  lead_score: number;
  engagement_score: number;
  stage_name?: string | null;
  probability: number;
  call_count: number;
  sms_count: number;
  last_call_sentiment?: string | null;
  sentiment_trend: "improving" | "declining" | "flat" | "unknown";
  objections: string[];
  open_next_steps: string[];
  awaiting_reply: boolean;
  expected_close_overdue: boolean;
}

export interface DealCoachCard {
  opportunity_id: string;
  workspace_id: string;
  name: string;
  amount?: number | null;
  currency: string;
  primary_contact_id?: number | null;
  contact_name?: string | null;
  deal_health: DealHealthStatus;
  health_score: number;
  health_summary: string;
  top_risk: string;
  risk_factors: string[];
  next_best_action: NextBestAction;
  drafted_action: DraftedAction;
  signals: DealSignals;
  generated_by: CoachGeneratedBy;
  generated_at: string;
}

export interface AtRiskDeal {
  opportunity_id: string;
  name: string;
  amount?: number | null;
  currency: string;
  primary_contact_id?: number | null;
  contact_name?: string | null;
  stage_name?: string | null;
  deal_health: DealHealthStatus;
  health_score: number;
  risk_score: number;
  top_risk: string;
  days_since_last_contact?: number | null;
  amount_at_risk: number;
}

export interface AtRiskDealsResponse {
  items: AtRiskDeal[];
  total: number;
  total_amount_at_risk: number;
}

export interface DraftActionRequest {
  channel?: CoachActionChannel;
  body?: string;
  description?: string;
}

export interface DraftActionResponse {
  decision: "pending" | "auto" | "blocked";
  pending_action_id?: string | null;
  action_type: string;
  description: string;
}

export interface Opportunity {
  id: string;
  workspace_id: string;
  pipeline_id: string;
  stage_id?: string;
  primary_contact_id?: number;
  assigned_user_id?: string;
  name: string;
  description?: string;
  amount?: number;
  currency: string;
  probability: number; // 0-100
  status: OpportunityStatus;
  lost_reason?: string;
  expected_close_date?: string;
  closed_date?: string;
  closed_by_id?: number;
  stage_changed_at?: string;
  source?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  line_items?: OpportunityLineItem[];
  activities?: OpportunityActivity[];
}
