// Operational reporting types. Mirrors the backend `app/schemas/reporting.py`.

export interface ARAgingBucket {
  label: string;
  amount: number;
  count: number;
}

export interface ARAgingReport {
  as_of: string;
  currency: string;
  total_outstanding: number;
  total_invoices: number;
  buckets: ARAgingBucket[];
}

export interface JobPnLSummary {
  date_from?: string | null;
  date_to?: string | null;
  currency: string;
  job_count: number;
  billable_job_count: number;
  revenue: number;
  labor_cost: number;
  expense_cost: number;
  total_cost: number;
  profit: number;
  margin?: number | null;
  total_hours: number;
}
