import type { Opportunity } from "@/types";

/**
 * A deal sitting this long in one stage is the signal a pipeline board exists
 * to surface: nobody has moved it, and nobody noticed. Two weeks is the point
 * where a home-service quote has gone cold without a follow-up.
 */
export const STALE_STAGE_DAYS = 14;

const MS_PER_DAY = 86_400_000;

/**
 * Whole days a deal has sat in its current stage.
 *
 * Falls back to `created_at` for deals that have never moved (the backend only
 * sets `stage_changed_at` on an actual stage change), so a card opened by lead
 * capture and forgotten still ages visibly.
 *
 * Returns `null` for an unparseable timestamp rather than rendering "NaNd".
 */
export function daysInStage(
  opportunity: Pick<Opportunity, "stage_changed_at" | "created_at">,
  now: Date = new Date(),
): number | null {
  const since = opportunity.stage_changed_at ?? opportunity.created_at;
  if (!since) return null;
  const start = new Date(since).getTime();
  if (Number.isNaN(start)) return null;
  return Math.max(0, Math.floor((now.getTime() - start) / MS_PER_DAY));
}

const MONTH_NAMES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

interface CalendarDate {
  year: number;
  month: number;
  day: number;
}

/**
 * Parse the calendar parts of an API date (`YYYY-MM-DD`).
 *
 * Deliberately does **not** go through `new Date(value)`: a date-only string
 * parses as UTC midnight, so every US timezone renders and compares it as the
 * previous day. A close date of the 24th showing as the 23rd is not a cosmetic
 * bug on a card an operator schedules work from.
 */
function parseCalendarDate(value: string): CalendarDate | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  const [, year, month, day] = match.map(Number);
  const probe = new Date(Date.UTC(year, month - 1, day));
  // Rejects impossible dates like 2026-02-31, which would silently roll over.
  if (
    probe.getUTCFullYear() !== year ||
    probe.getUTCMonth() !== month - 1 ||
    probe.getUTCDate() !== day
  ) {
    return null;
  }
  return { year, month, day };
}

export type CloseDateTone = "overdue" | "due-soon" | "scheduled";

export interface CloseDateStatus {
  tone: CloseDateTone;
  /** Whole days until close; negative once the date has passed. */
  daysUntil: number;
}

/**
 * Classify an expected close date so the card can lead with the deals that
 * need attention today.
 *
 * Only open deals can be overdue — a won or lost deal that closed after its
 * forecast date is history, not a task, and flagging it red would train
 * operators to ignore the colour.
 */
export function closeDateStatus(
  opportunity: Pick<Opportunity, "expected_close_date" | "status">,
  now: Date = new Date(),
): CloseDateStatus | null {
  if (!opportunity.expected_close_date) return null;
  const due = parseCalendarDate(opportunity.expected_close_date);
  if (!due) return null;

  // Compare calendar days, not instants, so "today" does not become overdue
  // after lunch.
  const dueDay = Date.UTC(due.year, due.month - 1, due.day);
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const daysUntil = Math.round((dueDay - today) / MS_PER_DAY);

  if (opportunity.status !== "open") return { tone: "scheduled", daysUntil };
  if (daysUntil < 0) return { tone: "overdue", daysUntil };
  if (daysUntil <= 2) return { tone: "due-soon", daysUntil };
  return { tone: "scheduled", daysUntil };
}

/**
 * The close-date line as an operator reads it: near dates in plain language,
 * everything else as a date. The year only appears when it is not this one — a
 * card has no room for noise that is right 95% of the time.
 */
export function closeDateLabel(
  opportunity: Pick<Opportunity, "expected_close_date" | "status">,
  now: Date = new Date(),
): string | null {
  const status = closeDateStatus(opportunity, now);
  if (!status || !opportunity.expected_close_date) return null;
  const due = parseCalendarDate(opportunity.expected_close_date);
  if (!due) return null;

  const dateText =
    `${MONTH_NAMES[due.month - 1]} ${due.day}` +
    (due.year === now.getFullYear() ? "" : `, ${due.year}`);

  if (status.tone === "overdue") return `Overdue since ${dateText}`;
  if (status.daysUntil === 0) return "Closes today";
  if (status.daysUntil === 1) return "Closes tomorrow";
  return `Closes ${dateText}`;
}

/** Sum of an opportunity's line items, or `null` when it has none. */
export function lineItemsTotal(opportunity: Pick<Opportunity, "line_items">): number | null {
  const items = opportunity.line_items;
  if (!items || items.length === 0) return null;
  return items.reduce((sum, item) => sum + (Number(item.total) || 0), 0);
}

/**
 * Human label for a `source` slug ("lead_form" -> "Lead form"). Sources are
 * free-text on the backend, so this stays a formatter rather than a lookup
 * table that silently drops unknown values.
 */
export function formatSourceLabel(source: string): string {
  const spaced = source.replace(/[_-]+/g, " ").trim();
  if (!spaced) return source;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
