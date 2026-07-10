import { describe, expect, it } from "vitest";

import type { Appointment } from "@/types";

import {
  appointmentsForDay,
  buildAppointmentsQueryParams,
  getContactName,
  getInitials,
  getMonthRange,
  getWeekRange,
  offsetToLabel,
  scheduledCount,
  statusFilterLabel,
  todaysAppointments,
  upcomingAppointments,
} from "./calendar-derivations";

function makeAppointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 1,
    contact_id: 1,
    scheduled_at: "2026-05-20T15:00:00.000Z",
    duration_minutes: 30,
    status: "scheduled",
    created_at: "2026-05-01T00:00:00.000Z",
    updated_at: "2026-05-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("getInitials", () => {
  it("combines first and last initials uppercased", () => {
    expect(getInitials("Ava", "Rivera")).toBe("AR");
  });

  it("handles a missing last name", () => {
    expect(getInitials("Ava")).toBe("A");
  });

  it("falls back to ? when no name is present", () => {
    expect(getInitials("")).toBe("?");
  });
});

describe("getContactName", () => {
  it("joins first and last name", () => {
    expect(
      getContactName({ first_name: "Ava", last_name: "Rivera" } as never),
    ).toBe("Ava Rivera");
  });

  it("omits empty parts", () => {
    expect(getContactName({ first_name: "Ava", last_name: "" } as never)).toBe("Ava");
  });

  it("returns Unknown for null/undefined", () => {
    expect(getContactName(null)).toBe("Unknown");
    expect(getContactName(undefined)).toBe("Unknown");
  });
});

describe("offsetToLabel", () => {
  it("formats whole days", () => {
    expect(offsetToLabel(1440)).toBe("1d");
    expect(offsetToLabel(2880)).toBe("2d");
  });

  it("formats whole hours", () => {
    expect(offsetToLabel(60)).toBe("1h");
    expect(offsetToLabel(180)).toBe("3h");
  });

  it("formats minutes when not an even hour/day", () => {
    expect(offsetToLabel(45)).toBe("45m");
    expect(offsetToLabel(90)).toBe("90m");
  });
});

describe("getWeekRange", () => {
  it("returns a Monday-based seven-day window covering the date", () => {
    // 2026-05-20 is a Wednesday
    const range = getWeekRange(new Date("2026-05-20T12:00:00.000Z"));
    expect(range.weekDays).toHaveLength(7);
    expect(range.weekStart.getTime()).toBeLessThanOrEqual(
      new Date("2026-05-20T12:00:00.000Z").getTime(),
    );
    expect(range.weekEnd.getTime()).toBeGreaterThanOrEqual(
      new Date("2026-05-20T12:00:00.000Z").getTime(),
    );
    expect(range.weekStartIso).toBe(range.weekStart.toISOString());
    expect(range.weekEndIso).toBe(range.weekEnd.toISOString());
  });
});

describe("getMonthRange", () => {
  it("returns a Sunday→Saturday grid of whole weeks covering the month", () => {
    // 2026-07-01 is a Wednesday; the grid spans Sun Jun 28 → Sat Aug 1.
    const range = getMonthRange(new Date(2026, 6, 15, 12, 0, 0));

    // monthDate is the first of the active month.
    expect(range.monthDate.getDate()).toBe(1);
    expect(range.monthDate.getMonth()).toBe(6); // July (0-based)

    // Every row is a full week and the grid is a whole number of weeks.
    expect(range.weeks.every((week) => week.length === 7)).toBe(true);
    const days = range.weeks.flat();
    expect(days.length % 7).toBe(0);

    // The grid starts on a Sunday and ends on a Saturday. gridEnd is the last
    // *instant* of Saturday (endOfWeek), while the grid cells are midnight-dated
    // days, so the final cell is compared by calendar day rather than instant.
    expect(range.gridStart.getDay()).toBe(0);
    expect(range.gridEnd.getDay()).toBe(6);
    expect(days[0].getTime()).toBe(range.gridStart.getTime());
    expect(days[days.length - 1].toDateString()).toBe(
      range.gridEnd.toDateString(),
    );

    // The whole active month falls inside the grid bounds.
    expect(range.gridStart.getTime()).toBeLessThanOrEqual(
      range.monthDate.getTime(),
    );
    const monthEnd = new Date(2026, 6, 31, 12, 0, 0);
    expect(range.gridEnd.getTime()).toBeGreaterThanOrEqual(monthEnd.getTime());

    // ISO bounds mirror the grid endpoints (drive the range fetch).
    expect(range.gridStartIso).toBe(range.gridStart.toISOString());
    expect(range.gridEndIso).toBe(range.gridEnd.toISOString());
  });

  it("produces an exact 4-week grid with no padding when the month aligns to weeks", () => {
    // 2026-02: Feb 1 is a Sunday and Feb 28 is a Saturday, so the grid needs no
    // leading/trailing days from adjacent months — exactly four Sun→Sat rows.
    const range = getMonthRange(new Date(2026, 1, 10, 12, 0, 0));
    expect(range.weeks).toHaveLength(4);
    expect(range.gridStart.getDate()).toBe(1);
    expect(range.gridStart.getMonth()).toBe(1); // February
    expect(range.gridStart.getDay()).toBe(0);
    expect(range.gridEnd.getDate()).toBe(28);
    expect(range.gridEnd.getDay()).toBe(6);
  });
});

describe("appointmentsForDay", () => {
  it("keeps only appointments on the given day", () => {
    const onDay = makeAppointment({ id: 1, scheduled_at: "2026-05-20T09:00:00.000Z" });
    const otherDay = makeAppointment({ id: 2, scheduled_at: "2026-05-21T09:00:00.000Z" });
    const result = appointmentsForDay([onDay, otherDay], new Date("2026-05-20T18:00:00.000Z"));
    expect(result.map((a) => a.id)).toEqual([1]);
  });
});

describe("todaysAppointments", () => {
  it("filters to appointments on the reference day", () => {
    const now = new Date("2026-05-20T12:00:00.000Z");
    const today = makeAppointment({ id: 1, scheduled_at: "2026-05-20T20:00:00.000Z" });
    const tomorrow = makeAppointment({ id: 2, scheduled_at: "2026-05-21T08:00:00.000Z" });
    expect(todaysAppointments([today, tomorrow], now).map((a) => a.id)).toEqual([1]);
  });
});

describe("upcomingAppointments", () => {
  it("returns only future appointments, preserving the source order", () => {
    const now = new Date("2026-05-20T12:00:00.000Z");
    const past = makeAppointment({ id: 1, scheduled_at: "2026-05-19T12:00:00.000Z" });
    const soon = makeAppointment({ id: 2, scheduled_at: "2026-05-21T12:00:00.000Z" });
    const later = makeAppointment({ id: 3, scheduled_at: "2026-05-25T12:00:00.000Z" });
    const result = upcomingAppointments([later, past, soon], now);
    // past is dropped; remaining keep their original relative order
    expect(result.map((a) => a.id)).toEqual([3, 2]);
  });
});

describe("scheduledCount", () => {
  it("counts only scheduled appointments", () => {
    const appts = [
      makeAppointment({ id: 1, status: "scheduled" }),
      makeAppointment({ id: 2, status: "completed" }),
      makeAppointment({ id: 3, status: "scheduled" }),
    ];
    expect(scheduledCount(appts)).toBe(2);
  });
});

describe("statusFilterLabel", () => {
  it("returns Total for the empty filter", () => {
    expect(statusFilterLabel("")).toBe("Total");
  });

  it("returns the matching option label", () => {
    expect(statusFilterLabel("no_show")).toBe("No-Show");
    expect(statusFilterLabel("scheduled")).toBe("Scheduled");
  });
});

describe("buildAppointmentsQueryParams", () => {
  it("omits status_filter when empty", () => {
    const params = buildAppointmentsQueryParams("2026-05-18T00:00:00Z", "2026-05-24T23:59:59Z", "");
    expect(params).toEqual({
      page: 1,
      page_size: 100,
      date_from: "2026-05-18T00:00:00Z",
      date_to: "2026-05-24T23:59:59Z",
    });
    expect("status_filter" in params).toBe(false);
  });

  it("includes status_filter when set", () => {
    const params = buildAppointmentsQueryParams(
      "2026-05-18T00:00:00Z",
      "2026-05-24T23:59:59Z",
      "completed",
    );
    expect(params.status_filter).toBe("completed");
  });
});
