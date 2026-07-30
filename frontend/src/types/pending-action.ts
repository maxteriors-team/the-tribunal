export type PendingActionStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "expired"
  | "executed"
  | "failed";

export interface PendingAction {
  id: string;
  workspace_id: string;
  agent_id: string | null;
  action_type: string;
  action_payload: Record<string, unknown>;
  description: string;
  context: Record<string, unknown>;
  status: PendingActionStatus;
  urgency: string;
  reviewed_by_id: number | null;
  reviewed_at: string | null;
  review_channel: string | null;
  rejection_reason: string | null;
  executed_at: string | null;
  execution_result: Record<string, unknown> | null;
  expires_at: string | null;
  notification_sent: boolean;
  notification_sent_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PendingActionListResponse {
  items: PendingAction[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface PendingActionStats {
  pending: number;
  approved: number;
  rejected: number;
  expired: number;
  executed: number;
}
