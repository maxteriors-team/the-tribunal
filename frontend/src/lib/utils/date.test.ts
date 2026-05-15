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
