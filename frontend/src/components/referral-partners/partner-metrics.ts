/**
 * Pure labels and formatting for the referral-partner scoreboard.
 *
 * Kept free of React so the rules that make these numbers trustworthy are
 * unit-testable on their own, mirroring
 * `components/reports/sales-performance-metrics.ts`:
 *
 * - **Rates are null, never zero, when their denominator is empty.** The backend
 *   already guarantees this; the UI must not undo it with `?? 0`, which would
 *   render a partner nobody has asked for a referral yet as a 0% close rate.
 * - **A rate without its denominator is not a fact.** Every rate is rendered
 *   beside the referral count it was computed from.
 * - **Silence is only meaningful with history.** "No referrals yet" and "sent
 *   work but has gone quiet" are different problems with different actions, so
 *   they never share a label.
 */

import type {
  ReferralPartnerScoreboardRow,
  ReferralPartnerType,
} from "@/lib/api/referral-partners";
import { formatDate } from "@/lib/utils/date";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/utils/number";

/** Rendered in place of any metric whose denominator was empty. */
export const NO_VALUE = "—";

/**
 * Below this many referrals a close rate is directional at best, so the UI flags
 * it. Five matches the sales report's threshold: the point where one extra win
 * or loss stops swinging the rate by more than ~20 points.
 */
export const LOW_SAMPLE_THRESHOLD = 5;

/** Relationship kinds in the order an owner tends to think about them. */
export const PARTNER_TYPE_OPTIONS: ReadonlyArray<{
  value: ReferralPartnerType;
  label: string;
}> = [
  { value: "realtor", label: "Realtor" },
  { value: "insurance", label: "Insurance agent" },
  { value: "trade", label: "Trade partner" },
  { value: "bni", label: "Networking group" },
  { value: "customer", label: "Past customer" },
  { value: "other", label: "Other" },
];

// Partial record so a type added to the API without an option here degrades to
// the raw value instead of type-asserting a missing label as present.
const PARTNER_TYPE_LABELS: Partial<Record<ReferralPartnerType, string>> =
  Object.fromEntries(PARTNER_TYPE_OPTIONS.map((o) => [o.value, o.label]));

export function partnerTypeLabel(type: ReferralPartnerType): string {
  return PARTNER_TYPE_LABELS[type] ?? type;
}

/** A 0..1 rate as a percent, or a dash when the denominator was empty. */
export function formatRate(value: number | null | undefined): string {
  return value === null || value === undefined ? NO_VALUE : formatPercent(value);
}

/** Money, or a dash when there was nothing to average. */
export function formatMoney(
  value: number | null | undefined,
  currency: string,
): string {
  return value === null || value === undefined
    ? NO_VALUE
    : formatCurrency(value, currency);
}

/** True when a rate rests on too few referrals to act on. */
export function isLowSample(sampleSize: number): boolean {
  return sampleSize > 0 && sampleSize < LOW_SAMPLE_THRESHOLD;
}

/** The denominator caption shown beside a rate, e.g. "4 referrals". */
export function describeReferralSample(sampleSize: number): string {
  return `${formatNumber(sampleSize)} referral${sampleSize === 1 ? "" : "s"}`;
}

/** Full company/relationship subtitle under a partner's name. */
export function describePartnerContext(
  row: Pick<ReferralPartnerScoreboardRow, "company" | "partner_type">,
): string {
  const type = partnerTypeLabel(row.partner_type);
  return row.company ? `${row.company} · ${type}` : type;
}

/**
 * How long a partner has been silent, phrased for the decision it drives.
 *
 * A partner with no history is an activation task ("Never referred"), not a
 * win-back call, so it never reads as a duration. That distinction is the whole
 * point of the gone-quiet list.
 */
export function describeSilence(
  row: Pick<
    ReferralPartnerScoreboardRow,
    "referrals_sent" | "last_referral_at" | "days_since_last_referral"
  >,
): { headline: string; detail: string | null } {
  if (row.referrals_sent === 0 || row.last_referral_at === null) {
    return { headline: "Never referred", detail: null };
  }

  const days = row.days_since_last_referral ?? 0;
  const headline =
    days === 0 ? "Today" : `${formatNumber(days)} day${days === 1 ? "" : "s"} ago`;
  return {
    headline,
    detail: formatDate(row.last_referral_at, { pattern: "MMM d, yyyy" }),
  };
}
