import { describe, expect, it } from "vitest";

import {
  APPROVED_SAMPLE,
  currentMonthRange,
  describeDelta,
  describeRange,
  describeSample,
  formatMoney,
  formatRate,
  fromIsoDate,
  isLowSample,
  NO_VALUE,
  previousRange,
  QUOTED_SAMPLE,
  toIsoDate,
} from "./sales-performance-metrics";

describe("date windows", () => {
  it("defaults to the whole current calendar month", () => {
    expect(currentMonthRange(new Date(2026, 6, 29))).toEqual({
      from: "2026-07-01",
      to: "2026-07-31",
    });
  });

  it("keeps local dates when the browser is behind UTC", () => {
    // 2026-07-01T00:00 local is 2026-07-01T07:00Z in the US; naive
    // `toISOString().slice(0, 10)` would still say July 1 here, but for a
    // browser *ahead* of UTC it flips the month. Assert the local-time answer.
    expect(toIsoDate(new Date(2026, 6, 1))).toBe("2026-07-01");
    expect(toIsoDate(new Date(2026, 0, 1))).toBe("2026-01-01");
    expect(toIsoDate(new Date(2025, 11, 31))).toBe("2025-12-31");
  });

  it("round-trips an ISO date through local time", () => {
    expect(toIsoDate(fromIsoDate("2026-02-28"))).toBe("2026-02-28");
  });

  it("compares against the equal-length window ending the day before", () => {
    // July has 31 days, so the comparison window is the 31 days before July 1.
    expect(previousRange({ from: "2026-07-01", to: "2026-07-31" })).toEqual({
      from: "2026-05-31",
      to: "2026-06-30",
    });
  });

  it("compares a partial window against an equally partial one", () => {
    // 10 days in -> the 10 days before it, not a whole calendar month.
    expect(previousRange({ from: "2026-07-01", to: "2026-07-10" })).toEqual({
      from: "2026-06-21",
      to: "2026-06-30",
    });
  });

  it("handles a single-day window", () => {
    expect(previousRange({ from: "2026-07-15", to: "2026-07-15" })).toEqual({
      from: "2026-07-14",
      to: "2026-07-14",
    });
  });

  it("describes a window for the picker label", () => {
    expect(describeRange({ from: "2026-07-01", to: "2026-07-31" })).toBe(
      "Jul 1 – Jul 31, 2026",
    );
  });
});

describe("describeDelta", () => {
  it("reports rate movement in percentage points, not percent change", () => {
    // 20% -> 30% is +10 points. Calling it "+50%" is the misread this prevents.
    const delta = describeDelta(0.3, 0.2, "ratio", "USD");

    expect(delta).not.toBeNull();
    expect(delta?.label).toBe("+10.0 pts");
    expect(delta?.direction).toBe("up");
    expect(delta?.previousLabel).toBe("20%");
  });

  it("reports a falling rate as negative points", () => {
    const delta = describeDelta(0.18, 0.25, "ratio", "USD");

    expect(delta?.label).toBe("-7.0 pts");
    expect(delta?.direction).toBe("down");
  });

  it("reports money movement in currency", () => {
    const delta = describeDelta(4200, 3788, "currency", "USD");

    expect(delta?.label).toBe("+$412.00");
    expect(delta?.direction).toBe("up");
    expect(delta?.previousLabel).toBe("$3,788.00");
  });

  it("calls an unchanged metric flat rather than up", () => {
    // Float noise: 0.3 - 0.2 is 0.09999999999999998, and 0.1 + 0.2 - 0.3 is not
    // exactly 0. Direction must come from the rounded value or a flat metric
    // renders a green up-arrow beside "+0.0 pts".
    const delta = describeDelta(0.30000000000000004, 0.3, "ratio", "USD");

    expect(delta?.direction).toBe("flat");
    expect(delta?.label).toBe("0.0 pts");
  });

  it("refuses to compare when the prior window has no value", () => {
    // A null baseline is "no data", not zero. Treating it as zero would invent
    // a "+100%" win out of an empty previous month.
    expect(describeDelta(0.42, null, "ratio", "USD")).toBeNull();
    expect(describeDelta(0.42, undefined, "ratio", "USD")).toBeNull();
  });

  it("refuses to compare when the current window has no value", () => {
    expect(describeDelta(null, 0.42, "ratio", "USD")).toBeNull();
  });

  it("still compares a genuine zero", () => {
    // 0 is a real measurement (quotes were decided, none closed); only null
    // means "no denominator".
    expect(describeDelta(0, 0.2, "ratio", "USD")?.label).toBe("-20.0 pts");
  });
});

describe("null-safe formatting", () => {
  it("renders a missing rate as a dash, never 0%", () => {
    expect(formatRate(null)).toBe(NO_VALUE);
    expect(formatRate(undefined)).toBe(NO_VALUE);
    expect(formatRate(0)).toBe("0%");
    expect(formatRate(0.3333)).toBe("33.33%");
  });

  it("renders a missing average as a dash, never $0.00", () => {
    expect(formatMoney(null, "USD")).toBe(NO_VALUE);
    expect(formatMoney(undefined, "USD")).toBe(NO_VALUE);
    expect(formatMoney(0, "USD")).toBe("$0.00");
    expect(formatMoney(4200, "USD")).toBe("$4,200.00");
  });

  it("never produces NaN from an absent value", () => {
    expect(formatRate(null)).not.toContain("NaN");
    expect(formatMoney(null, "USD")).not.toContain("NaN");
  });
});

describe("sample size", () => {
  it("flags a sample too thin to act on", () => {
    expect(isLowSample(2)).toBe(true);
    expect(isLowSample(4)).toBe(true);
    expect(isLowSample(5)).toBe(false);
    expect(isLowSample(40)).toBe(false);
  });

  it("does not flag an empty sample as merely low", () => {
    // Zero has no rate at all, so it is a dash, not a shaky number.
    expect(isLowSample(0)).toBe(false);
  });

  it("pluralizes the denominator noun", () => {
    expect(describeSample(1, QUOTED_SAMPLE)).toBe("1 quote");
    expect(describeSample(12, QUOTED_SAMPLE)).toBe("12 quotes");
  });

  it("leaves an invariant denominator noun alone", () => {
    // "8 approved", never "8 approveds".
    expect(describeSample(1, APPROVED_SAMPLE)).toBe("1 approved");
    expect(describeSample(8, APPROVED_SAMPLE)).toBe("8 approved");
  });
});
