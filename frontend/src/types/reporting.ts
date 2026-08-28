// Operational reporting types. Mirrors the backend `app/schemas/reporting.py`.

import type { components } from "@/lib/api/_generated";

type Schemas = components["schemas"];

/**
 * Sales performance (average job value, attach rate, close rate) over a quote
 * cohort. Sourced from the generated OpenAPI schema rather than hand-written so
 * the null-vs-zero contract on every rate stays in lockstep with the backend:
 * a rate is `null` when its denominator is empty, never `0`.
 */
export type SalesPerformanceReport = Schemas["SalesPerformanceReport"];

/** Contact intake coverage for structured first-touch attribution. */
export type AttributionGapReport = Schemas["AttributionGapReport"];

/**
 * One grouped slice of sales performance. The backend reuses this exact shape
 * for closer, lead-source, and primary-service breakdowns, so the UI renders
 * all three with one table component.
 */
export type SalesPerformanceBreakdownRow = Schemas["SalesPerformanceBreakdownRow"];

/**
 * A closer's slice, plus the same metrics split across that rep's own service
 * lines. Structurally a breakdown row, so the shared table renders it unchanged
 * and only the expandable variant reads `by_service`.
 */
export type SalesPerformanceCloserRow = Schemas["SalesPerformanceCloserRow"];

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
  /** Stock consumed from inventory. Never overlaps `expense_cost`. */
  material_cost: number;
  total_cost: number;
  profit: number;
  margin?: number | null;
  total_hours: number;
}
