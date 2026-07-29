// Service plans — the persisted record of what a client signed up for.
// Mirrors the backend `app/schemas/recurring_job.py` (the API path stays
// `recurring-jobs`; only the product surface is called Service Plans).

export type RecurrenceFrequency =
  | "weekly"
  | "biweekly"
  | "monthly"
  | "quarterly"
  | "yearly";

/**
 * Which recurring service a plan covers.
 *
 * `lighting_care_plan` is the landscape-lighting maintenance subscription (the
 * tier lives in `care_plan_tier`); `christmas_lights` is the seasonal signup,
 * stored as an install plan plus a takedown plan; `maintenance` is the generic
 * hand-built contract.
 */
export type ServicePlanType =
  | "lighting_care_plan"
  | "christmas_lights"
  | "maintenance";

export interface ServicePlan {
  id: string;
  workspace_id: string;
  contact_id: number;
  service_location_id?: string | null;
  crew_id?: string | null;
  title: string;
  description?: string | null;
  plan_type: ServicePlanType;
  care_plan_tier?: string | null;
  /** The approved quote this plan was provisioned from, when auto-created. */
  source_quote_id?: string | null;
  frequency: RecurrenceFrequency;
  interval: number;
  duration_minutes: number;
  generate_days_ahead: number;
  default_technician_ids: string[];
  next_run_at: string;
  last_run_at?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CreateServicePlanRequest {
  contact_id: number;
  title: string;
  description?: string;
  plan_type?: ServicePlanType;
  care_plan_tier?: string | null;
  frequency: RecurrenceFrequency;
  interval?: number;
  duration_minutes?: number;
  generate_days_ahead?: number;
  service_location_id?: string;
  crew_id?: string;
  default_technician_ids?: string[];
  next_run_at: string;
  is_active?: boolean;
}

export interface UpdateServicePlanRequest {
  title?: string;
  description?: string;
  plan_type?: ServicePlanType;
  care_plan_tier?: string | null;
  frequency?: RecurrenceFrequency;
  interval?: number;
  duration_minutes?: number;
  generate_days_ahead?: number;
  service_location_id?: string | null;
  crew_id?: string | null;
  default_technician_ids?: string[];
  next_run_at?: string;
  is_active?: boolean;
}

export interface ServicePlanRunResult {
  created: number;
  template: ServicePlan;
}
