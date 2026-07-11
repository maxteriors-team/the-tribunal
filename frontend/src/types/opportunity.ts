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
