import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  formatDate,
  formatDateTime,
  formatDayMonth,
  formatLongDate,
  formatRelative,
  formatTime,
} from "./date";

// Fixed reference date keeps formatRelative assertions deterministic.
const NOW = new Date("2026-05-15T12:00:00.000Z");

describe("date utils", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllEnvs();
  });

  describe("formatDate", () => {
    it("formats a Date in the default short pattern", () => {
      // Construct via local-time components so the formatted day is timezone-stable.
      const date = new Date(2026, 0, 5, 12, 0, 0); // Jan 5, 2026
      expect(formatDate(date)).toBe("Jan 5, 2026");
    });

    it("accepts a custom pattern", () => {
      const date = new Date(2026, 0, 5, 12, 0, 0);
      expect(formatDate(date, { pattern: "yyyy-MM-dd" })).toBe("2026-01-05");
    });

    it("accepts a numeric epoch input", () => {
      const date = new Date(2026, 5, 1, 12, 0, 0); // Jun 1, 2026
      expect(formatDate(date.getTime())).toBe("Jun 1, 2026");
    });

    it("accepts a string input", () => {
      const date = new Date(2026, 5, 1, 12, 0, 0);
      expect(formatDate(date.toISOString())).toBe("Jun 1, 2026");
    });
  });

  describe.each([
    { timezone: "America/New_York", offset: 240, midnight: "Sep 29, 2026", late: "Sep 30, 2026" },
    { timezone: "Pacific/Honolulu", offset: 600, midnight: "Sep 29, 2026", late: "Sep 30, 2026" },
    { timezone: "UTC", offset: 0, midnight: "Sep 30, 2026", late: "Sep 30, 2026" },
    { timezone: "Europe/Berlin", offset: -120, midnight: "Sep 30, 2026", late: "Oct 1, 2026" },
    { timezone: "Asia/Kolkata", offset: -330, midnight: "Sep 30, 2026", late: "Oct 1, 2026" },
    { timezone: "Pacific/Kiritimati", offset: -840, midnight: "Sep 30, 2026", late: "Oct 1, 2026" },
  ])("calendar dates versus instants in $timezone", ({ timezone, offset, midnight, late }) => {
    beforeEach(() => {
      vi.stubEnv("TZ", timezone);
    });

    it("keeps September 30 in short, long, compact, and custom date formats", () => {
      // Prove the runtime changed zones, not just the TZ environment string.
      expect(new Date("2026-09-30T00:00:00Z").getTimezoneOffset()).toBe(offset);
      expect(formatDate("2026-09-30")).toBe("Sep 30, 2026");
      expect(formatLongDate("2026-09-30")).toBe("September 30, 2026");
      expect(formatDayMonth("2026-09-30")).toBe("Sep 30");
      expect(formatDate("2026-09-30", { pattern: "yyyy-MM-dd" })).toBe("2026-09-30");
    });

    it.each([
      "2026-03-08",
      "2026-11-01", // US DST boundaries
      "2026-03-29",
      "2026-10-25", // European DST boundaries
      "2024-02-29",
      "2000-02-29", // leap days
      "2026-01-01",
      "2026-12-31", // year boundaries
    ])("preserves the calendar day %s", (date) => {
      expect(formatDate(date, { pattern: "yyyy-MM-dd" })).toBe(date);
    });

    it("still converts timestamp strings, Date objects, and epoch numbers", () => {
      for (const [timestamp, expected] of [
        ["2026-09-30T00:00:00Z", midnight],
        ["2026-09-30T23:30:00Z", late],
      ]) {
        const instant = new Date(timestamp);
        expect(formatDate(timestamp)).toBe(expected);
        expect(formatDate(instant)).toBe(expected);
        expect(formatDate(instant.getTime())).toBe(expected);
      }
      expect(formatDate(0)).toBe(formatDate(new Date(0)));
      expect(formatDate(0)).not.toBe("—");
      expect(formatRelative("2026-05-15T10:00:00Z")).toBe("about 2 hours ago");
    });

    it.each([
      null,
      undefined,
      "",
      "not-a-date",
      new Date(NaN),
      NaN,
      Infinity,
      "2026-02-29",
      "2026-02-30",
      "1900-02-29",
      "2026-04-31",
      "2026-00-10",
      "2026-13-01",
      "2026-09-00",
      "2026-09-31",
    ])(
      "uses a placeholder for missing/invalid input %s instead of rolling over or throwing",
      (date) => {
        expect(formatDate(date)).toBe("—");
      },
    );
  });

  it.each([
    ["America/New_York", "2026-03-08T06:30:00Z", "Mar 8, 2026, 1:30 AM"],
    ["America/New_York", "2026-03-08T07:30:00Z", "Mar 8, 2026, 3:30 AM"],
    ["America/New_York", "2026-11-01T05:30:00Z", "Nov 1, 2026, 1:30 AM"],
    ["America/New_York", "2026-11-01T06:30:00Z", "Nov 1, 2026, 1:30 AM"],
    ["Europe/Berlin", "2026-03-29T00:30:00Z", "Mar 29, 2026, 1:30 AM"],
    ["Europe/Berlin", "2026-03-29T01:30:00Z", "Mar 29, 2026, 3:30 AM"],
    ["Europe/Berlin", "2026-10-25T00:30:00Z", "Oct 25, 2026, 2:30 AM"],
    ["Europe/Berlin", "2026-10-25T01:30:00Z", "Oct 25, 2026, 2:30 AM"],
    ["America/New_York", "2026-09-30T00:00:00+14:00", "Sep 29, 2026, 6:00 AM"],
    ["Europe/Berlin", "2026-09-30T23:00:00-04:00", "Oct 1, 2026, 5:00 AM"],
  ])(
    "converts instants across DST and explicit offsets: %s / %s",
    (timezone, instant, expected) => {
      vi.stubEnv("TZ", timezone);
      expect(formatDateTime(instant)).toBe(expected);
    },
  );

  describe("formatDateTime", () => {
    it("includes time of day", () => {
      const date = new Date(2026, 0, 5, 15, 4, 0); // 3:04 PM local
      expect(formatDateTime(date)).toBe("Jan 5, 2026, 3:04 PM");
    });
  });

  describe("formatTime", () => {
    it("formats only the clock time", () => {
      const date = new Date(2026, 0, 5, 9, 7, 0);
      expect(formatTime(date)).toBe("9:07 AM");
    });
  });

  describe("formatRelative", () => {
    it("returns a suffixed past phrase", () => {
      const twoHoursAgo = new Date(NOW.getTime() - 2 * 60 * 60 * 1000);
      expect(formatRelative(twoHoursAgo)).toBe("about 2 hours ago");
    });

    it("returns a prefixed future phrase", () => {
      const inFiveMinutes = new Date(NOW.getTime() + 5 * 60 * 1000);
      expect(formatRelative(inFiveMinutes)).toBe("in 5 minutes");
    });
  });

  describe("formatDayMonth", () => {
    it("renders compact day + month", () => {
      const date = new Date(2026, 0, 5, 12, 0, 0);
      expect(formatDayMonth(date)).toBe("Jan 5");
    });
  });

  describe("formatLongDate", () => {
    it("renders the long-form month name", () => {
      const date = new Date(2026, 0, 5, 12, 0, 0);
      expect(formatLongDate(date)).toBe("January 5, 2026");
    });
  });
});
