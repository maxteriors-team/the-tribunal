import { describe, expect, it } from "vitest";

import type { Appointment } from "@/types";

import {
  appointmentsForDay,
  buildAppointmentsQueryParams,
  getContactName,
  getInitials,
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
