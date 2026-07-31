/**
 * The calendar maths behind pre-booking.
 *
 * Two rules earn their own tests because getting either wrong silently points a
 * campaign at the wrong season: a season may wrap the new year (November →
 * February is ONE season), and the runway between launch and the season opening
 * is what decides whether the campaign is pre-booking at all. The 90- and
 * 30-day boundaries are the grading thresholds, so they are pinned exactly.
 */
import { describe, expect, it } from "vitest";

import {
  AMPLE_LEAD_DAYS,
  TIGHT_LEAD_DAYS,
  assessLeadTime,
  assessSeasonLeadTime,
  describeSeason,
  leadTimeDays,
  monthName,
  nextSeasonYear,
  previewOffer,
  resolveSeasonWindow,
} from "./pre-booking";

describe("resolveSeasonWindow", () => {
  it("resolves a same-year season to its first and last day", () => {
    const window = resolveSeasonWindow({ startMonth: 3, endMonth: 5, year: 2027 });
    expect(window.start).toEqual(new Date(2027, 2, 1));
    expect(window.end).toEqual(new Date(2027, 4, 31));
    expect(window.label).toBe("March–May 2027");
  });

  it("wraps into the following year when the end month precedes the start month", () => {
    // Holiday lighting sold as "November through February" is one season, not
    // two: the end year is derived, never asked for.
    const window = resolveSeasonWindow({ startMonth: 11, endMonth: 2, year: 2026 });
    expect(window.start).toEqual(new Date(2026, 10, 1));
    expect(window.end).toEqual(new Date(2027, 1, 28));
    expect(window.label).toBe("November 2026–February 2027");
  });

  it("ends a wrapped February season on the 29th in a leap year", () => {
    const window = resolveSeasonWindow({ startMonth: 11, endMonth: 2, year: 2027 });
    expect(window.end).toEqual(new Date(2028, 1, 29));
  });

  it("labels a single-month season without a range dash", () => {
    expect(describeSeason({ startMonth: 12, endMonth: 12, year: 2026 })).toBe(
      "December 2026",
    );
  });

  it("rejects months outside 1-12", () => {
    expect(() => resolveSeasonWindow({ startMonth: 0, endMonth: 5, year: 2027 })).toThrow();
    expect(() => resolveSeasonWindow({ startMonth: 3, endMonth: 13, year: 2027 })).toThrow();
    expect(monthName(9)).toBe("September");
  });
});

describe("nextSeasonYear", () => {
  it("prefills the year so the season is always still ahead", () => {
    // The headline case: building January work in September means NEXT January.
    const september = new Date(2026, 8, 15);
    expect(nextSeasonYear({ startMonth: 1, today: september })).toBe(2027);
    expect(nextSeasonYear({ startMonth: 12, today: september })).toBe(2026);
  });

  it("rolls to next year when the season starts in the current month", () => {
    // Mid-September is too late to pre-sell September, so September means 2027.
    const september = new Date(2026, 8, 15);
    expect(nextSeasonYear({ startMonth: 9, today: september })).toBe(2027);
  });
});

describe("assessLeadTime", () => {
  it("grades 90+ days as ample", () => {
    expect(assessLeadTime(AMPLE_LEAD_DAYS).status).toBe("ample");
    expect(assessLeadTime(120).status).toBe("ample");
    expect(assessLeadTime(120).message).toContain("runway");
  });

  it("grades 30-89 days as tight", () => {
    expect(assessLeadTime(AMPLE_LEAD_DAYS - 1).status).toBe("tight");
    expect(assessLeadTime(45).status).toBe("tight");
    expect(assessLeadTime(TIGHT_LEAD_DAYS).status).toBe("tight");
  });

  it("grades under 30 days as late, including the day the season opens", () => {
    expect(assessLeadTime(TIGHT_LEAD_DAYS - 1).status).toBe("late");
    expect(assessLeadTime(0).status).toBe("late");
    expect(assessLeadTime(0).message).toContain("fill-the-calendar");
  });

  it("reports a season that has already started", () => {
    const past = assessLeadTime(-14);
    expect(past.status).toBe("late");
    expect(past.days).toBe(-14);
    expect(past.message).toContain("started 14 days ago");
  });
});

describe("leadTimeDays", () => {
  it("counts calendar days and ignores the time of day", () => {
    const launchEvening = new Date(2026, 8, 1, 21, 30);
    const seasonStart = new Date(2027, 0, 1, 6, 0);
    expect(leadTimeDays({ launchOn: launchEvening, seasonStart })).toBe(122);
  });

  it("goes negative once the season has opened", () => {
    expect(
      leadTimeDays({
        launchOn: new Date(2027, 0, 20),
        seasonStart: new Date(2027, 0, 1),
      }),
    ).toBe(-19);
  });

  it("grades the canonical 'build January–March in September' plan as ample", () => {
    const lead = assessSeasonLeadTime({
      startMonth: 1,
      endMonth: 3,
      year: 2027,
      launchOn: new Date(2026, 8, 1),
    });
    expect(lead.days).toBe(122);
    expect(lead.status).toBe("ample");
  });

  it("grades a spring season sold in March as late", () => {
    const lead = assessSeasonLeadTime({
      startMonth: 4,
      endMonth: 6,
      year: 2027,
      launchOn: new Date(2027, 2, 25),
    });
    expect(lead.status).toBe("late");
  });
});

describe("previewOffer", () => {
  it("takes the incentive off the job, then the deposit off what's left", () => {
    const preview = previewOffer({
      baseAmount: 450,
      incentiveType: "percentage",
      incentiveValue: 20,
      depositType: "percentage",
      depositValue: 25,
    });
    expect(preview.savings).toBe(90);
    expect(preview.discountedTotal).toBe(360);
    expect(preview.depositDueToday).toBe(90);
    expect(preview.balanceAtService).toBe(270);
  });

  it("clamps a fixed amount that exceeds the job rather than owing money", () => {
    const preview = previewOffer({
      baseAmount: 450,
      incentiveType: "fixed",
      incentiveValue: 5000,
      depositType: "fixed",
      depositValue: 100,
    });
    expect(preview.savings).toBe(450);
    expect(preview.discountedTotal).toBe(0);
    expect(preview.depositDueToday).toBe(0);
  });
});
