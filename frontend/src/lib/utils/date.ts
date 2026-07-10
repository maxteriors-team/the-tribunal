// Date formatting helpers. Thin wrappers over date-fns so the rest of the app
// imports from one place — easier to swap libraries, change locale defaults,
// or harden bad-input handling later.

import {
  format,
  formatDistanceToNow,
  addDays as dfAddDays,
  addMonths as dfAddMonths,
  startOfWeek as dfStartOfWeek,
  endOfWeek as dfEndOfWeek,
  startOfMonth as dfStartOfMonth,
  endOfMonth as dfEndOfMonth,
  isSameDay as dfIsSameDay,
  isSameMonth as dfIsSameMonth,
  isToday as dfIsToday,
  isYesterday as dfIsYesterday,
} from "date-fns";

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

/** Add (or subtract, with negatives) calendar days. */
export function addDays(date: DateInput, days: number): Date {
  return dfAddDays(toDate(date), days);
}

/** Add (or subtract, with negatives) calendar months. */
export function addMonths(date: DateInput, months: number): Date {
  return dfAddMonths(toDate(date), months);
}

/** First day of the month containing `date`. */
export function startOfMonth(date: DateInput): Date {
  return dfStartOfMonth(toDate(date));
}

/** Last day of the month containing `date`. */
export function endOfMonth(date: DateInput): Date {
  return dfEndOfMonth(toDate(date));
}

/** True if both inputs fall in the same calendar month + year. */
export function isSameMonth(a: DateInput, b: DateInput): boolean {
  return dfIsSameMonth(toDate(a), toDate(b));
}

export interface WeekOptions {
  /** 0 = Sunday, 1 = Monday, … 6 = Saturday. Defaults to Sunday. */
  weekStartsOn?: 0 | 1 | 2 | 3 | 4 | 5 | 6;
}

/** Start of the week containing `date`. Defaults to Sunday. */
export function startOfWeek(date: DateInput, options: WeekOptions = {}): Date {
  return dfStartOfWeek(toDate(date), options);
}

/** End of the week containing `date`. Defaults to Sunday-start. */
export function endOfWeek(date: DateInput, options: WeekOptions = {}): Date {
  return dfEndOfWeek(toDate(date), options);
}

/** True if both inputs fall on the same calendar day. */
export function isSameDay(a: DateInput, b: DateInput): boolean {
  return dfIsSameDay(toDate(a), toDate(b));
}

/** True if `date` is today (local time). */
export function isToday(date: DateInput): boolean {
  return dfIsToday(toDate(date));
}

/** True if `date` is yesterday (local time). */
export function isYesterday(date: DateInput): boolean {
  return dfIsYesterday(toDate(date));
}
