/**
 * Season windows, lead time, and offer maths for pre-booking campaigns.
 *
 * Pure functions over plain values so the wizard can answer two questions
 * *before* anything is saved, and so they can be tested without rendering:
 *
 * 1. **When is the work actually happening?** The operator picks months
 *    ("March through May"), not dates, and a season may wrap the new year
 *    (November through February is one season, not two).
 * 2. **Is it too late to run this campaign?** Selling a spring season in March
 *    is not pre-booking, it is scrambling. Lead time is graded here so the UI
 *    can say so before a month of SMS is spent on it.
 *
 * These mirror `app/services/prebooking/season.py` and `.../slots.py` so the
 * number shown in the wizard is the number the backend later computes.
 */

import type {
  PreBookingAmountType,
  PreBookingLeadTimeStatus,
} from "@/types/pre-booking";

/**
 * The gap that makes pre-booking work. A January–March season built in
 * September has ~120 days of runway: enough for a first send, two follow-ups,
 * and the customer's own "let me talk to my wife" cycle — while the money is
 * still being spent on Christmas rather than on somebody else's spring special.
 */
export const AMPLE_LEAD_DAYS = 90;

/**
 * Below this the campaign can still land, but the discount is buying urgency
 * rather than planning, and the crew has no room left to shape the calendar.
 */
export const TIGHT_LEAD_DAYS = 30;

const MS_PER_DAY = 24 * 60 * 60 * 1000;

const MONTH_NAMES = [
  "January",
  "February",
  "March",
  "April",
  "May",
  "June",
  "July",
  "August",
  "September",
  "October",
  "November",
  "December",
] as const;

/** Month options for the season pickers, in calendar order. */
export const MONTH_OPTIONS = MONTH_NAMES.map((label, index) => ({
  value: index + 1,
  label,
}));

export interface SeasonWindow {
  /** First day the work could be performed. */
  start: Date;
  /** Last day the work could be performed. */
  end: Date;
  /** Operator-facing season name, e.g. "March–May 2027". */
  label: string;
}

export interface LeadTime {
  days: number;
  status: PreBookingLeadTimeStatus;
  message: string;
}

/** English month name for 1-12, for operator-facing copy. */
export function monthName(month: number): string {
  assertMonth(month);
  return MONTH_NAMES[month - 1];
}

/**
 * Resolve a month range plus a start year into concrete dates.
 *
 * `year` is the year the window *starts* in. A season whose end month is
 * earlier than its start month wraps into the following year — holiday lighting
 * sold as "November through January" is one season — which is why the end year
 * is derived rather than asked for. The end date is the last day of `endMonth`,
 * so a February season is 28 or 29 days without the caller knowing which.
 */
export function resolveSeasonWindow({
  startMonth,
  endMonth,
  year,
}: {
  startMonth: number;
  endMonth: number;
  year: number;
}): SeasonWindow {
  assertMonth(startMonth);
  assertMonth(endMonth);

  const endYear = endMonth >= startMonth ? year : year + 1;
  const start = new Date(year, startMonth - 1, 1);
  // Day 0 of the next month is the last day of this one.
  const end = new Date(endYear, endMonth, 0);

  return { start, end, label: seasonLabel(startMonth, endMonth, year, endYear) };
}

/** Human label for a season window, e.g. "March–May 2027". */
export function describeSeason({
  startMonth,
  endMonth,
  year,
}: {
  startMonth: number;
  endMonth: number;
  year: number;
}): string {
  return resolveSeasonWindow({ startMonth, endMonth, year }).label;
}

/**
 * The next year in which `startMonth` is still ahead of `today`.
 *
 * Used to prefill the wizard: an operator opening the form in September for a
 * January season means *next* January, and making them work that out is how a
 * campaign ends up pointed at a season that has already happened.
 */
export function nextSeasonYear({
  startMonth,
  today = new Date(),
}: {
  startMonth: number;
  today?: Date;
}): number {
  assertMonth(startMonth);
  return startMonth > today.getMonth() + 1
    ? today.getFullYear()
    : today.getFullYear() + 1;
}

/** Whole days between a campaign launching and the season opening (may be negative). */
export function leadTimeDays({
  launchOn,
  seasonStart,
}: {
  launchOn: Date;
  seasonStart: Date;
}): number {
  // Compare calendar days, not instants: a launch at 9pm and one at 9am on the
  // same date have the same runway. Rounding also absorbs DST hour shifts.
  return Math.round((startOfDay(seasonStart) - startOfDay(launchOn)) / MS_PER_DAY);
}

/**
 * Grade a lead time so the UI can warn before the money is spent. `late` is not
 * an error — an operator may deliberately run a mid-season fill-the-calendar
 * push — but it is never what pre-booking is *for*, so it is labelled rather
 * than silently accepted.
 */
export function assessLeadTime(days: number): LeadTime {
  if (days >= AMPLE_LEAD_DAYS) {
    return {
      days,
      status: "ample",
      message: `${Math.floor(days / 30)} month(s) of runway before the season opens — the right time to pre-sell.`,
    };
  }
  if (days >= TIGHT_LEAD_DAYS) {
    return {
      days,
      status: "tight",
      message: `Only ${days} days before the season opens. Still workable, but ${AMPLE_LEAD_DAYS}+ days gives follow-ups room to land.`,
    };
  }
  if (days >= 0) {
    return {
      days,
      status: "late",
      message: `The season opens in ${days} days. This is a fill-the-calendar push, not a pre-booking campaign — build next season's now.`,
    };
  }
  return {
    days,
    status: "late",
    message: `The season started ${Math.abs(days)} days ago. Point this at the next season instead.`,
  };
}

/** Lead time for a launch date against a month-range season, in one call. */
export function assessSeasonLeadTime({
  startMonth,
  endMonth,
  year,
  launchOn,
}: {
  startMonth: number;
  endMonth: number;
  year: number;
  launchOn: Date;
}): LeadTime {
  const { start } = resolveSeasonWindow({ startMonth, endMonth, year });
  return assessLeadTime(leadTimeDays({ launchOn, seasonStart: start }));
}

export interface OfferPreview {
  /** What the customer saves by committing early. */
  savings: number;
  /** Job price after the pre-booking discount. */
  discountedTotal: number;
  /** Paid now, to hold the slot. */
  depositDueToday: number;
  /** Left to pay when the crew shows up. */
  balanceAtService: number;
}

/**
 * Price one job under an offer's terms — the worked example the wizard shows.
 *
 * Order matters and matches the backend: the incentive comes off the subtotal,
 * then the deposit is taken against the *discounted* total, because that is the
 * quote the customer is actually paying a deposit on.
 */
export function previewOffer({
  baseAmount,
  incentiveType,
  incentiveValue,
  depositType,
  depositValue,
}: {
  baseAmount: number;
  incentiveType: PreBookingAmountType;
  incentiveValue: number;
  depositType: PreBookingAmountType;
  depositValue: number;
}): OfferPreview {
  const savings = resolveAmount(incentiveType, incentiveValue, baseAmount);
  const discountedTotal = round2(baseAmount - savings);
  const depositDueToday = resolveAmount(depositType, depositValue, discountedTotal);
  return {
    savings,
    discountedTotal,
    depositDueToday,
    balanceAtService: round2(discountedTotal - depositDueToday),
  };
}

/** "20% off" / "$50 off"-style rendering of an incentive or deposit value. */
export function formatAmountTerm(
  type: PreBookingAmountType,
  value: number
): string {
  return type === "percentage" ? `${value}%` : `$${value}`;
}

function resolveAmount(
  type: PreBookingAmountType,
  value: number,
  total: number
): number {
  if (value <= 0 || total <= 0) return 0;
  // A fat-fingered "$5,000 off" on a $450 house wash discounts the job to zero
  // rather than owing the customer money.
  if (type === "fixed") return round2(Math.min(value, total));
  return round2((total * Math.min(value, 100)) / 100);
}

function seasonLabel(
  startMonth: number,
  endMonth: number,
  startYear: number,
  endYear: number
): string {
  if (startMonth === endMonth) return `${monthName(startMonth)} ${startYear}`;
  if (startYear === endYear) {
    return `${monthName(startMonth)}–${monthName(endMonth)} ${startYear}`;
  }
  return `${monthName(startMonth)} ${startYear}–${monthName(endMonth)} ${endYear}`;
}

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function assertMonth(month: number): void {
  if (!Number.isInteger(month) || month < 1 || month > 12) {
    throw new Error(`Month must be between 1 and 12, got ${month}`);
  }
}
