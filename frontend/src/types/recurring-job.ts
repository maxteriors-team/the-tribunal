// Recurring job templates (maintenance contracts).
// Mirrors the backend `app/schemas/recurring_job.py`.

export type RecurrenceFrequency =
  | "weekly"
  | "biweekly"
  | "monthly"
  | "quarterly"
  | "yearly";

export interface RecurringJobTemplate {
  id: string;
  workspace_id: string;
  contact_id: number;
  service_location_id?: string | null;
  crew_id?: string | null;
  title: string;
  description?: string | null;
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

export interface CreateRecurringJobRequest {
  contact_id: number;
  title: string;
  description?: string;
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

export interface UpdateRecurringJobRequest {
  title?: string;
  description?: string;
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

export interface RecurringJobRunResult {
  created: number;
  template: RecurringJobTemplate;
}
