export interface HumanNudge {
  id: string;
  workspace_id: string;
  /** null for workspace-level operator nudges (not tied to a contact) */
  contact_id: number | null;
  nudge_type: NudgeType;
  title: string;
  message: string;
  suggested_action: SuggestedAction | null;
  priority: NudgePriority;
  due_date: string;
  source_date_field: string | null;
  status: NudgeStatus;
  snoozed_until: string | null;
  delivered_via: string | null;
  delivered_at: string | null;
  acted_at: string | null;
  assigned_to_user_id: number | null;
  created_at: string;
  // Populated from backend
  contact_name: string | null;
  contact_phone: string | null;
  contact_company: string | null;
}

export type NudgeType =
  | "birthday"
  | "anniversary"
  | "follow_up"
  | "cooling"
  | "deal_milestone"
  | "custom"
  | "noshow_recovery"
  | "unresponsive"
  | "hot_lead"
  | "referral_ask"
  // Workspace-level operator nudges (contact_id is null)
  | "outbound_batch_ready"
  | "approvals_waiting"
  | "monitor_idle";
export type NudgeStatus = "pending" | "sent" | "acted" | "dismissed" | "snoozed";
export type NudgePriority = "low" | "medium" | "high";
export type SuggestedAction = "send_card" | "call" | "text" | "email";

export interface NudgeListResponse {
  items: HumanNudge[];
  total: number;
  page: number;
  page_size: number;
}

export interface NudgeStats {
  pending: number;
  sent: number;
  acted: number;
  dismissed: number;
  snoozed: number;
  total: number;
}

export interface NudgeSettings {
  enabled: boolean;
  lead_days: number;
  nudge_types: NudgeType[];
  delivery_channels: string[];
  cooling_days: number;
  quiet_hours_start: string;
  quiet_hours_end: string;
}

export interface UpdateNudgeSettings {
  enabled?: boolean;
  lead_days?: number;
  nudge_types?: NudgeType[];
  delivery_channels?: string[];
  cooling_days?: number;
  quiet_hours_start?: string;
  quiet_hours_end?: string;
}
