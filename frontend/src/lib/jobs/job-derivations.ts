/**
 * Pure derivation helpers for the jobs calendar.
 *
 * Mirrors `lib/calendar/calendar-derivations.ts`: week grouping, status options,
 * and the list query params live here so the week-grid component stays thin and
 * these helpers stay unit-testable without rendering.
 */

import type { Job, JobListParams, JobStatus } from "@/lib/api/jobs";
import { isSameDay } from "@/lib/utils/date";

export type JobStatusFilter = "" | JobStatus;

export interface JobStatusOption {
  value: JobStatusFilter;
  label: string;
}

export const JOB_STATUS_OPTIONS: readonly JobStatusOption[] = [
  { value: "", label: "All" },
  { value: "unscheduled", label: "Unscheduled" },
  { value: "scheduled", label: "Scheduled" },
  { value: "in_progress", label: "In progress" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
] as const;

/** Tailwind classes per job status, matching the appointment badge palette. */
export const jobStatusColors: Record<JobStatus, string> = {
  unscheduled: "bg-gray-500/10 text-gray-500 border-gray-500/20",
  scheduled: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  in_progress: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  completed: "bg-green-500/10 text-green-500 border-green-500/20",
  cancelled: "bg-red-500/10 text-red-500 border-red-500/20",
};

/** Human label for a status value (falls back to the raw value). */
export function jobStatusLabel(status: JobStatus): string {
  return JOB_STATUS_OPTIONS.find((option) => option.value === status)?.label ?? status;
}

/** Jobs whose scheduled start falls on the given calendar day. */
export function jobsForDay(jobs: Job[], day: Date): Job[] {
  return jobs.filter(
    (job) => job.scheduled_start !== null && isSameDay(new Date(job.scheduled_start), day),
  );
}

/** Jobs with no time window yet — the dispatch queue. */
export function unscheduledJobs(jobs: Job[]): Job[] {
  return jobs.filter((job) => job.scheduled_start === null);
}

/** Initials for a technician avatar fallback, e.g. "Ada Lovelace" → "AL". */
export function technicianInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

/** The real lifecycle statuses, excluding the "All" filter sentinel. */
export const JOB_STATUS_VALUES: readonly JobStatus[] = JOB_STATUS_OPTIONS.filter(
  (option): option is JobStatusOption & { value: JobStatus } => option.value !== "",
).map((option) => option.value);

/**
 * Validation message for a (possibly partial) time window; "" when valid.
 * Both bounds must be set together and ordered. Shared by the create and detail
 * dialogs so the rule lives in one place.
 */
export function jobWindowError(start: string, end: string): string {
  if (Boolean(start) !== Boolean(end)) return "Set both start and end, or neither.";
  if (start && end && new Date(end) <= new Date(start)) return "End must be after start.";
  return "";
}

/** A `datetime-local` input value → ISO 8601, or null when empty. */
export function localToIso(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

/** ISO 8601 → a value for an `<input type="datetime-local">` (local, minutes). */
export function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const localMs = date.getTime() - date.getTimezoneOffset() * 60_000;
  return new Date(localMs).toISOString().slice(0, 16);
}

/** Build the jobs list query params for the active week + status filter. */
export function buildJobsQueryParams(
  weekStartIso: string,
  weekEndIso: string,
  statusFilter: JobStatusFilter,
): JobListParams {
  return {
    date_from: weekStartIso,
    date_to: weekEndIso,
    ...(statusFilter ? { status: statusFilter } : {}),
  };
}
