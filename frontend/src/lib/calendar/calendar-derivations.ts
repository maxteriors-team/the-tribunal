/**
 * Pure derivation helpers for the calendar page.
 *
 * Splitting these out of `calendar-page.tsx` keeps the week/agenda grouping and
 * the small formatting helpers unit-testable without rendering the component.
 */

import {
  addDays,
  isSameDay,
  startOfWeek,
  endOfWeek,
  startOfMonth,
  endOfMonth,
} from "@/lib/utils/date";
import type { Appointment, Contact } from "@/types";

export type StatusFilter = "" | "scheduled" | "no_show" | "completed" | "cancelled";

export interface StatusOption {
  value: StatusFilter;
  label: string;
}

export const STATUS_OPTIONS: readonly StatusOption[] = [
  { value: "", label: "All" },
  { value: "scheduled", label: "Scheduled" },
  { value: "no_show", label: "No-Show" },
  { value: "completed", label: "Completed" },
  { value: "cancelled", label: "Cancelled" },
] as const;

/** Contact initials for an avatar fallback, e.g. "Ava Rivera" → "AR". */
export function getInitials(firstName: string, lastName?: string): string {
  const first = firstName?.[0] ?? "";
  const last = lastName?.[0] ?? "";
  return (first + last).toUpperCase() || "?";
}

/** Human-readable contact name, falling back to "Unknown". */
export function getContactName(contact: Contact | null | undefined): string {
  if (!contact) return "Unknown";
  return [contact.first_name, contact.last_name].filter(Boolean).join(" ");
}

/** Convert a minutes offset to a compact reminder label (e.g. 1440 → "1d"). */
export function offsetToLabel(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440}d`;
  if (minutes >= 60 && minutes % 60 === 0) return `${minutes / 60}h`;
  return `${minutes}m`;
}

export interface WeekRange {
  weekStart: Date;
  weekEnd: Date;
  weekStartIso: string;
  weekEndIso: string;
  weekDays: Date[];
}

/** Monday-based week window (start/end ISO + the seven day dates) for `date`. */
export function getWeekRange(date: Date): WeekRange {
  const weekStart = startOfWeek(date, { weekStartsOn: 1 });
  const weekEnd = endOfWeek(date, { weekStartsOn: 1 });
  return {
    weekStart,
    weekEnd,
    weekStartIso: weekStart.toISOString(),
    weekEndIso: weekEnd.toISOString(),
    weekDays: Array.from({ length: 7 }, (_, index) => addDays(weekStart, index)),
  };
}

export interface MonthRange {
  /** First day of the active month (drives the header label + outside-day dimming). */
  monthDate: Date;
  /** Sunday on or before the 1st — the top-left cell of the grid. */
  gridStart: Date;
  /** Saturday on or after the month end — the bottom-right cell of the grid. */
  gridEnd: Date;
  gridStartIso: string;
  gridEndIso: string;
  /** Whole weeks (Sun→Sat rows) covering the month, 4–6 rows. */
  weeks: Date[][];
}

/**
 * Sunday-based month grid (matches Jobber's Schedule): the visible cells span
 * from the Sunday on/before the 1st to the Saturday on/after the month's end,
 * so every row is a full week. Bounds are returned as ISO for the range fetch.
 */
export function getMonthRange(date: Date): MonthRange {
  const monthDate = startOfMonth(date);
  const gridStart = startOfWeek(monthDate, { weekStartsOn: 0 });
  const gridEnd = endOfWeek(endOfMonth(date), { weekStartsOn: 0 });
  const weeks: Date[][] = [];
  let cursor = gridStart;
  while (cursor <= gridEnd) {
    weeks.push(Array.from({ length: 7 }, (_, index) => addDays(cursor, index)));
    cursor = addDays(cursor, 7);
  }
  return {
    monthDate,
    gridStart,
    gridEnd,
    gridStartIso: gridStart.toISOString(),
    gridEndIso: gridEnd.toISOString(),
    weeks,
  };
}

/** Appointments scheduled on the given calendar day. */
export function appointmentsForDay(
  appointments: Appointment[],
  day: Date,
): Appointment[] {
  return appointments.filter((appointment) =>
    isSameDay(new Date(appointment.scheduled_at), day),
  );
}

/** Appointments scheduled for "today" relative to `now`. */
export function todaysAppointments(
  appointments: Appointment[],
  now: Date = new Date(),
): Appointment[] {
  return appointments.filter((appointment) =>
    isSameDay(new Date(appointment.scheduled_at), now),
  );
}

/** Future appointments, preserving the source array order (matches the API order). */
export function upcomingAppointments(
  appointments: Appointment[],
  now: Date = new Date(),
): Appointment[] {
  return appointments.filter(
    (appointment) => new Date(appointment.scheduled_at) > now,
  );
}

/** Count of appointments currently in the "scheduled" status. */
export function scheduledCount(appointments: Appointment[]): number {
  return appointments.filter((appointment) => appointment.status === "scheduled")
    .length;
}

/** Label for the status filter pill / stat tile. */
export function statusFilterLabel(statusFilter: StatusFilter): string {
  if (!statusFilter) return "Total";
  return STATUS_OPTIONS.find((option) => option.value === statusFilter)?.label ?? "Filtered";
}

/** Build the appointments list query params for the active week + filter. */
export function buildAppointmentsQueryParams(
  weekStartIso: string,
  weekEndIso: string,
  statusFilter: StatusFilter,
): {
  page: number;
  page_size: number;
  date_from: string;
  date_to: string;
  status_filter?: StatusFilter;
} {
  return {
    page: 1,
    page_size: 100,
    date_from: weekStartIso,
    date_to: weekEndIso,
    ...(statusFilter ? { status_filter: statusFilter } : {}),
  };
}
