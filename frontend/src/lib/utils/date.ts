// Date formatting helpers. Thin wrappers over date-fns so the rest of the app
// imports from one place — easier to swap libraries, change locale defaults,
// or harden bad-input handling later.

import { format, formatDistanceToNow } from "date-fns";

export type DateInput = Date | string | number;

function toDate(value: DateInput): Date {
  return value instanceof Date ? value : new Date(value);
}

export interface FormatDateOptions {
  /** date-fns format pattern. Defaults to "MMM d, yyyy" (e.g. "Jan 5, 2026"). */
  pattern?: string;
}

/** Short date, e.g. "Jan 5, 2026". Pass `pattern` to override. */
export function formatDate(date: DateInput, options: FormatDateOptions = {}): string {
  return format(toDate(date), options.pattern ?? "MMM d, yyyy");
}

/** Full timestamp, e.g. "Jan 5, 2026, 3:04 PM". */
export function formatDateTime(date: DateInput): string {
  return format(toDate(date), "MMM d, yyyy, h:mm a");
}

/** Clock time only, e.g. "3:04 PM". */
export function formatTime(date: DateInput): string {
  return format(toDate(date), "h:mm a");
}

/** Relative phrase, e.g. "about 2 hours ago" / "in 3 minutes". */
export function formatRelative(date: DateInput): string {
  return formatDistanceToNow(toDate(date), { addSuffix: true });
}

/** Day + month only, e.g. "Jan 5". Useful for compact lists. */
export function formatDayMonth(date: DateInput): string {
  return format(toDate(date), "MMM d");
}

/** Long form, e.g. "January 5, 2026". */
export function formatLongDate(date: DateInput): string {
  return format(toDate(date), "MMMM d, yyyy");
}
