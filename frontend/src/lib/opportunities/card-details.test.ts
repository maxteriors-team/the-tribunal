import { describe, expect, it } from "vitest";

import {
  closeDateLabel,
  closeDateStatus,
  daysInStage,
  formatSourceLabel,
  lineItemsTotal,
  STALE_STAGE_DAYS,
} from "@/lib/opportunities/card-details";

const NOW = new Date("2026-08-03T15:00:00Z");

describe("daysInStage", () => {
  it("counts whole days since the last stage change", () => {
    expect(
      daysInStage(
        { stage_changed_at: "2026-07-30T15:00:00Z", created_at: "2026-01-01T00:00:00Z" },
        NOW,
      ),
    ).toBe(4);
  });

  it("falls back to created_at for a deal that has never moved", () => {
    expect(
      daysInStage({ stage_changed_at: undefined, created_at: "2026-07-04T15:00:00Z" }, NOW),
    ).toBe(30);
  });

  it("floors a partial day to 0 rather than rounding up", () => {
    expect(
      daysInStage({ stage_changed_at: "2026-08-03T01:00:00Z", created_at: "" }, NOW),
    ).toBe(0);
  });

  it("never reports negative age for a clock-skewed future timestamp", () => {
    expect(
      daysInStage({ stage_changed_at: "2026-09-01T00:00:00Z", created_at: "" }, NOW),
    ).toBe(0);
  });

  it("returns null for an unparseable timestamp instead of NaN", () => {
    expect(daysInStage({ stage_changed_at: "not-a-date", created_at: "" }, NOW)).toBeNull();
    expect(daysInStage({ stage_changed_at: undefined, created_at: "" }, NOW)).toBeNull();
  });

  it("flags a deal parked past the stale threshold", () => {
    const age = daysInStage(
      { stage_changed_at: "2026-07-01T15:00:00Z", created_at: "" },
      NOW,
    );
    expect(age).not.toBeNull();
    expect(age! >= STALE_STAGE_DAYS).toBe(true);
  });
});

describe("closeDateStatus", () => {
  it("marks a passed close date on an open deal as overdue", () => {
    expect(
      closeDateStatus({ expected_close_date: "2026-08-01", status: "open" }, NOW),
    ).toEqual({ tone: "overdue", daysUntil: -2 });
  });

  it("treats today as due-soon, not overdue, later in the day", () => {
    expect(
      closeDateStatus({ expected_close_date: "2026-08-03", status: "open" }, NOW),
    ).toEqual({ tone: "due-soon", daysUntil: 0 });
  });

  it("flags the next two days as due-soon", () => {
    expect(
      closeDateStatus({ expected_close_date: "2026-08-05", status: "open" }, NOW)?.tone,
    ).toBe("due-soon");
    expect(
      closeDateStatus({ expected_close_date: "2026-08-06", status: "open" }, NOW)?.tone,
    ).toBe("scheduled");
  });

  it("never marks a closed deal overdue — it is history, not a task", () => {
    expect(
      closeDateStatus({ expected_close_date: "2026-08-01", status: "won" }, NOW)?.tone,
    ).toBe("scheduled");
    expect(
      closeDateStatus({ expected_close_date: "2026-08-01", status: "lost" }, NOW)?.tone,
    ).toBe("scheduled");
  });

  it("returns null when no close date is forecast", () => {
    expect(closeDateStatus({ expected_close_date: undefined, status: "open" }, NOW)).toBeNull();
    expect(closeDateStatus({ expected_close_date: "nope", status: "open" }, NOW)).toBeNull();
    expect(closeDateStatus({ expected_close_date: "2026-02-31", status: "open" }, NOW)).toBeNull();
  });
});

describe("closeDateLabel", () => {
  it("renders the date the API sent, not the day before", () => {
    // Regression: a date-only value parsed via `new Date()` lands on UTC
    // midnight and renders as the previous day in every US timezone.
    expect(closeDateLabel({ expected_close_date: "2026-08-24", status: "open" }, NOW)).toBe(
      "Closes Aug 24",
    );
  });

  it("speaks plainly about the next two days", () => {
    expect(closeDateLabel({ expected_close_date: "2026-08-03", status: "open" }, NOW)).toBe(
      "Closes today",
    );
    expect(closeDateLabel({ expected_close_date: "2026-08-04", status: "open" }, NOW)).toBe(
      "Closes tomorrow",
    );
  });

  it("names the day an open deal slipped", () => {
    expect(closeDateLabel({ expected_close_date: "2026-07-31", status: "open" }, NOW)).toBe(
      "Overdue since Jul 31",
    );
  });

  it("adds the year only when it is not the current one", () => {
    expect(closeDateLabel({ expected_close_date: "2027-01-09", status: "open" }, NOW)).toBe(
      "Closes Jan 9, 2027",
    );
  });

  it("returns null without a usable close date", () => {
    expect(closeDateLabel({ expected_close_date: undefined, status: "open" }, NOW)).toBeNull();
    expect(closeDateLabel({ expected_close_date: "nope", status: "open" }, NOW)).toBeNull();
  });
});

describe("lineItemsTotal", () => {
  const item = (total: number) => ({
    id: String(total),
    opportunity_id: "o1",
    name: "Soft wash",
    quantity: 1,
    unit_price: total,
    discount: 0,
    total,
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
  });

  it("sums the line items", () => {
    expect(lineItemsTotal({ line_items: [item(450), item(275.5)] })).toBe(725.5);
  });

  it("returns null when the deal has no line items", () => {
    expect(lineItemsTotal({ line_items: [] })).toBeNull();
    expect(lineItemsTotal({ line_items: undefined })).toBeNull();
  });
});

describe("formatSourceLabel", () => {
  it("humanizes a slug", () => {
    expect(formatSourceLabel("lead_form")).toBe("Lead form");
    expect(formatSourceLabel("google-ads")).toBe("Google ads");
  });

  it("passes through an already-readable source", () => {
    expect(formatSourceLabel("Referral")).toBe("Referral");
  });
});
