/**
 * Pure maths and formatting for the sales-performance report.
 *
 * Kept free of React so the rules that make these numbers trustworthy are
 * unit-testable on their own:
 *
 * - **Rates are null, never zero, when their denominator is empty.** The backend
 *   already guarantees this (`app/services/reporting/sales_performance_service.py`);
 *   the UI must not undo it by coercing with `?? 0`, which would render a brand
 *   new workspace as a "0% close rate" instead of "no quotes yet".
 * - **Rate deltas are percentage points, not percent change.** A close rate that
 *   moves 20% -> 30% improved by 10 points; calling that "+50%" is the kind of
 *   number that gets a closer fired for the wrong reason.
 * - **A rate without its denominator is not a fact.** Every rate carries the
 *   sample it was computed from, and small samples are marked as such.
 */

import { addDays, endOfMonth, formatDate, startOfMonth } from "@/lib/utils/date";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils/number";

/** Rendered in place of any metric whose denominator was empty. */
export const NO_VALUE = "—";

/**
 * Below this many quotes a rate is directional at best, so the UI flags it.
 * Five is the point where one extra win or loss stops swinging the rate by
 * more than ~20 points, which is the smallest sample an owner can coach on.
 */
export const LOW_SAMPLE_THRESHOLD = 5;

/**
 * Inclusive date window, both edges as `yyyy-MM-dd` (what the API accepts).
 *
 * A type alias rather than an interface so it stays assignable to the
 * `Record<string, unknown>` that `queryKeys` normalizes params through.
 */
export type DateRange = {
  from: string;
  to: string;
};

/** `yyyy-MM-dd` in local time. `toISOString()` is deliberately avoided: it
 * converts to UTC first, which shifts the date by a day for anyone west of
 * Greenwich and would silently report the wrong month. */
export function toIsoDate(date: Date): string {
  return formatDate(date, { pattern: "yyyy-MM-dd" });
}

/** Parse `yyyy-MM-dd` as a local-time date (not UTC midnight). */
export function fromIsoDate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

/** The current calendar month, the report's default window. */
export function currentMonthRange(today: Date = new Date()): DateRange {
  return { from: toIsoDate(startOfMonth(today)), to: toIsoDate(endOfMonth(today)) };
}

/**
 * The equal-length window ending the day before `range` starts.
 *
 * Equal length (rather than "the previous calendar month") is what makes the
 * comparison fair for partial or custom windows: the first 10 days of a month
 * are compared against the 10 days before them, not against a full month.
 */
export function previousRange(range: DateRange): DateRange {
  const from = fromIsoDate(range.from);
  const to = fromIsoDate(range.to);
  const lengthInDays = Math.round((to.getTime() - from.getTime()) / 86_400_000) + 1;
  return {
    from: toIsoDate(addDays(from, -lengthInDays)),
    to: toIsoDate(addDays(from, -1)),
  };
}

/** Human-readable window, e.g. "Jul 1 – Jul 31, 2026". */
export function describeRange(range: DateRange): string {
  return `${formatDate(fromIsoDate(range.from), { pattern: "MMM d" })} – ${formatDate(
    fromIsoDate(range.to),
    { pattern: "MMM d, yyyy" },
  )}`;
}

export type MetricKind = "currency" | "ratio";

export interface MetricDelta {
  direction: "up" | "down" | "flat";
  /** Signed change in the metric's own unit, already rounded for display. */
  change: number;
  /** Unit-correct change, e.g. "+$412.00" or "+4.2 pts". */
  label: string;
  /** The value being compared against, e.g. "$3,788.00". */
  previousLabel: string;
}

/**
 * Compare a metric against the previous equal-length window.
 *
 * Returns `null` when the comparison cannot honestly be made — either window
 * missing its value means there is nothing to compare, and inventing a
 * "+100%" out of a null baseline is worse than saying so.
 */
export function describeDelta(
  current: number | null | undefined,
  previous: number | null | undefined,
  kind: MetricKind,
  currency: string,
): MetricDelta | null {
  if (current === null || current === undefined) return null;
  if (previous === null || previous === undefined) return null;

  // Round before deriving direction, otherwise float noise (0.3 - 0.2) renders
  // as an "up" arrow next to a "+0.0 pts" label.
  const raw = kind === "ratio" ? (current - previous) * 100 : current - previous;
  const change = Number(raw.toFixed(kind === "ratio" ? 1 : 2));
  const direction = change > 0 ? "up" : change < 0 ? "down" : "flat";
  const sign = change > 0 ? "+" : change < 0 ? "-" : "";
  const magnitude = Math.abs(change);

  const label =
    kind === "ratio"
      ? `${sign}${magnitude.toFixed(1)} pts`
      : `${sign}${formatCurrency(magnitude, currency)}`;

  return {
    direction,
    change,
    label,
    previousLabel:
      kind === "ratio" ? formatPercent(previous) : formatCurrency(previous, currency),
  };
}

/** A 0..1 ratio as a percent, or an em dash when the denominator was empty. */
export function formatRate(value: number | null | undefined): string {
  return value === null || value === undefined ? NO_VALUE : formatPercent(value);
}

/** Money, or an em dash when there was nothing to average. */
export function formatMoney(
  value: number | null | undefined,
  currency: string,
): string {
  return value === null || value === undefined
    ? NO_VALUE
    : formatCurrency(value, currency);
}

/** True when a rate rests on too few quotes to act on. */
export function isLowSample(sampleSize: number): boolean {
  return sampleSize > 0 && sampleSize < LOW_SAMPLE_THRESHOLD;
}

/**
 * Names what a rate's sample actually counted.
 *
 * The three rates do not share a denominator: average job value and attach rate
 * are computed over *approved* quotes, while close rate is approved / decided
 * (approved + declined + expired). Quotes still out with the customer are in
 * neither denominator, which is why the issued-quote caption reads "20 quotes"
 * and never "8 of 20" — the latter states a fraction the rate is not.
 */
export interface SampleNoun {
  singular: string;
  plural: string;
}

/** Denominator of average job value and attach rate: approved quotes. */
export const APPROVED_SAMPLE: SampleNoun = {
  singular: "approved",
  plural: "approved",
};

/** Volume behind a close rate: quotes issued in the window. */
export const QUOTED_SAMPLE: SampleNoun = { singular: "quote", plural: "quotes" };

/** The denominator caption shown beside a rate, e.g. "8 approved". */
export function describeSample(sampleSize: number, noun: SampleNoun): string {
  return `${formatNumber(sampleSize)} ${
    sampleSize === 1 ? noun.singular : noun.plural
  }`;
}
