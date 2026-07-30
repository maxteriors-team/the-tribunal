import { describe, expect, it } from "vitest";

import type { ReferralPartnerScoreboardRow } from "@/lib/api/referral-partners";

import {
  describePartnerContext,
  describeReferralSample,
  describeSilence,
  formatMoney,
  formatRate,
  isLowSample,
  NO_VALUE,
  PARTNER_TYPE_OPTIONS,
  partnerTypeLabel,
} from "./partner-metrics";

function row(
  overrides: Partial<ReferralPartnerScoreboardRow> = {},
): ReferralPartnerScoreboardRow {
  return {
    partner_id: "partner-1",
    name: "Dana Ruiz",
    company: "Keller Williams",
    partner_type: "realtor",
    is_active: true,
    referrals_sent: 0,
    jobs_closed: 0,
    close_rate: null,
    total_revenue: 0,
    average_job_value: null,
    last_referral_at: null,
    days_since_last_referral: null,
    is_gone_quiet: false,
    ...overrides,
  };
}

describe("formatRate", () => {
  it("renders a dash rather than 0% when the denominator was empty", () => {
    // Coercing null to 0 would libel a partner nobody has asked for a referral.
    expect(formatRate(null)).toBe(NO_VALUE);
    expect(formatRate(undefined)).toBe(NO_VALUE);
  });

  it("renders a real zero rate as 0%", () => {
    // Referrals that genuinely never closed *are* a 0% close rate.
    expect(formatRate(0)).toBe("0%");
  });

  it("formats a fraction as a percent", () => {
    expect(formatRate(0.25)).toBe("25%");
    expect(formatRate(1)).toBe("100%");
  });
});

describe("formatMoney", () => {
  it("renders a dash when there was nothing to average", () => {
    expect(formatMoney(null, "USD")).toBe(NO_VALUE);
  });

  it("formats currency", () => {
    expect(formatMoney(12000, "USD")).toBe("$12,000.00");
    expect(formatMoney(0, "USD")).toBe("$0.00");
  });
});

describe("isLowSample", () => {
  it("flags thin samples but not empty ones", () => {
    expect(isLowSample(0)).toBe(false);
    expect(isLowSample(1)).toBe(true);
    expect(isLowSample(4)).toBe(true);
    expect(isLowSample(5)).toBe(false);
  });
});

describe("describeReferralSample", () => {
  it("singularizes one referral", () => {
    expect(describeReferralSample(1)).toBe("1 referral");
    expect(describeReferralSample(4)).toBe("4 referrals");
    expect(describeReferralSample(1200)).toBe("1,200 referrals");
  });
});

describe("partnerTypeLabel", () => {
  it("labels every known relationship kind", () => {
    for (const option of PARTNER_TYPE_OPTIONS) {
      expect(partnerTypeLabel(option.value)).toBe(option.label);
    }
  });

  it("degrades to the raw value for an unmapped kind", () => {
    // A type added to the API without an option here must not crash the table.
    expect(
      partnerTypeLabel("franchise" as ReferralPartnerScoreboardRow["partner_type"]),
    ).toBe("franchise");
  });
});

describe("describePartnerContext", () => {
  it("combines company and relationship", () => {
    expect(describePartnerContext(row())).toBe("Keller Williams · Realtor");
  });

  it("falls back to the relationship alone", () => {
    expect(describePartnerContext(row({ company: null }))).toBe("Realtor");
  });
});

describe("describeSilence", () => {
  it("separates never-referred from gone-quiet", () => {
    // These are different problems: one is an activation task, the other a
    // win-back call, so they must never share a label.
    expect(describeSilence(row())).toEqual({
      headline: "Never referred",
      detail: null,
    });
  });

  it("treats a partner with no last-referral date as never-referred", () => {
    const result = describeSilence(
      row({ referrals_sent: 3, last_referral_at: null, days_since_last_referral: 40 }),
    );
    expect(result.headline).toBe("Never referred");
  });

  it("reads a same-day referral as today", () => {
    const result = describeSilence(
      row({
        referrals_sent: 1,
        last_referral_at: "2026-07-30T09:00:00Z",
        days_since_last_referral: 0,
      }),
    );
    expect(result.headline).toBe("Today");
  });

  it("singularizes one day and groups large day counts", () => {
    expect(
      describeSilence(
        row({
          referrals_sent: 1,
          last_referral_at: "2026-07-29T09:00:00Z",
          days_since_last_referral: 1,
        }),
      ).headline,
    ).toBe("1 day ago");
    expect(
      describeSilence(
        row({
          referrals_sent: 1,
          last_referral_at: "2023-07-29T09:00:00Z",
          days_since_last_referral: 1097,
        }),
      ).headline,
    ).toBe("1,097 days ago");
  });
});
