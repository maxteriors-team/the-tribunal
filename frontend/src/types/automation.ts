// Automation types

// Generic/legacy trigger kinds plus the concrete event/polling triggers the
// backend automation worker evaluates.
export type AutomationTriggerType =
  | "schedule"
  | "event"
  | "condition"
  // Polling triggers (contact-centric)
  | "appointment_booked"
  | "booking_created"
  | "no_show"
  | "contact_tagged"
  | "never_booked"
  // Event triggers (emitted by services)
  | "review_received"
  | "review_request_response"
  | "opportunity_created"
  | "deal_stage_changed"
  | "missed_call"
  | "roleplay_completed"
  | "knowledge_document_uploaded";

// Action types the backend automation worker can execute, plus UI-only kinds
// retained for backward compatibility with existing automations.
export type AutomationActionType =
  | "send_sms"
  | "send_email"
  | "make_call"
  | "enroll_campaign"
  | "apply_tag"
  | "add_tag"
  | "wait"
  | "delay"
  | "update_status";

export interface AutomationAction {
  type: AutomationActionType;
  config: Record<string, unknown>;
}

export interface Automation {
  id: string;
  name: string;
  description?: string;
  trigger_type: AutomationTriggerType;
  trigger_config?: Record<string, unknown>;
  actions: AutomationAction[];
  is_active: boolean;
  last_triggered_at?: string;
  created_at: string;
  updated_at: string;
}
