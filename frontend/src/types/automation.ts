// Automation types

import type { FilterDefinition, FilterRule } from "./filter";

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
  // Condition triggers (workspace state, no contact matching)
  | "backlog_below_threshold"
  // Event triggers (emitted by services)
  | "review_received"
  | "review_request_response"
  | "opportunity_created"
  | "deal_stage_changed"
  | "missed_call"
  | "roleplay_completed"
  | "knowledge_document_uploaded"
  // Lead capture trigger (emitted by the public lead-form ingestion path)
  | "lead_created"
  // Quote/invoice/job lifecycle events (emitted by quote, invoice and job services)
  | "quote_sent"
  | "quote_approved"
  | "quote_declined"
  | "quote_converted"
  | "invoice_sent"
  | "invoice_paid"
  | "job_scheduled"
  | "job_completed";

// Action types the backend automation worker can execute, plus UI-only kinds
// retained for backward compatibility with existing automations.
export type AutomationActionType =
  | "send_sms"
  | "send_email"
  | "make_call"
  | "enroll_campaign"
  | "start_drip_campaign"
  | "apply_tag"
  | "add_tag"
  | "move_to_stage"
  | "wait"
  | "delay"
  | "branch"
  | "update_status";

export interface AutomationAction {
  /**
   * Stable step id. Only steps a branch jumps to need one, so the key is
   * absent on everything else — the backend omits it from serialization when
   * unset rather than writing `"id": null` into every stored step.
   */
  id?: string;
  type: AutomationActionType;
  config: Record<string, unknown>;
}

/**
 * Where a branch sends the run:
 * - a step `id` present in the workflow -> jump to that step;
 * - `"__end__"` -> finish the run;
 * - `null` -> fall through to the following step.
 *
 * An id matching no step ends the run (the backend refuses to fall through
 * after a typo'd target), so the builder must never leave one dangling.
 */
export type AutomationGotoTarget = string | null;

/**
 * Config of a `wait`/`delay` step. Every unit present is summed, so
 * `{ days: 1, hours: 12 }` is 36 hours; `hours` is the legacy key older
 * automations were written with.
 */
export interface AutomationWaitConfig {
  minutes?: number;
  hours?: number;
  days?: number;
}

/**
 * Config of a `branch` step. `conditions` is the same JSON rule shape as the
 * contacts list / saved segments (`FilterRule`), which is why branches can be
 * authored with the existing `ContactFilterBuilder`.
 */
export interface AutomationBranchConfig {
  conditions: FilterRule[];
  logic: FilterDefinition["logic"];
  then_goto: AutomationGotoTarget;
  else_goto: AutomationGotoTarget;
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
