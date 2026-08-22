import { describe, expect, it } from "vitest";

import type { Job } from "@/lib/api/jobs";
import {
  appointmentEntry,
  countByKind,
  entriesForDay,
  entryAccessibleLabel,
  jobEntry,
  toCalendarEntries,
  upcomingEntries,
  type CalendarEntry,
} from "@/lib/calendar/calendar-entries";
import type { Appointment } from "@/types";

/**
 * The reconciliation layer under the unified calendar.
 *
 * Appointments and jobs arrive from two endpoints with different time fields
 * and different shapes. Everything downstream — month cells, the week grid, the
 * agenda, the counts — assumes one sorted list, so the merge is where an
 * ordering or day-placement bug would silently misplace somebody's work.
 */

function makeAppointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 1,
    workspace_id: "ws-1",
    contact_id: 1,
    agent_id: null,
    scheduled_at: "2026-08-12T15:00:00.000Z",
    duration_minutes: 30,
    status: "scheduled",
    service_type: "Gutter estimate",
    notes: null,
    created_at: "2026-08-01T00:00:00.000Z",
    updated_at: "2026-08-01T00:00:00.000Z",
    ...overrides,
  } as Appointment;
}

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: "job-1",
    workspace_id: "ws-1",
    contact_id: 1,
    service_location_id: null,
    crew_id: null,
    title: "Roof tune-up",
    description: null,
    status: "scheduled",
    scheduled_start: "2026-08-12T17:00:00.000Z",
    scheduled_end: "2026-08-12T19:00:00.000Z",
    external_source: null,
    external_id: null,
    technicians: [],
    created_at: "2026-08-01T00:00:00.000Z",
    updated_at: "2026-08-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("toCalendarEntries", () => {
  it("interleaves both species in time order", () => {
    const entries = toCalendarEntries(
      [
        makeAppointment({ id: 1, scheduled_at: "2026-08-12T18:00:00.000Z" }),
        makeAppointment({ id: 2, scheduled_at: "2026-08-12T09:00:00.000Z" }),
      ],
      [
        makeJob({ id: "job-a", scheduled_start: "2026-08-12T12:00:00.000Z" }),
        makeJob({ id: "job-b", scheduled_start: "2026-08-12T06:00:00.000Z" }),
      ],
    );

    // A day cell has to read top-to-bottom as the day actually runs, whichever
    // endpoint each row came from.
    expect(entries.map((entry) => entry.key)).toEqual([
      "job-job-b",
      "appointment-2",
      "job-job-a",
      "appointment-1",
    ]);
  });

  it("drops jobs with no time window", () => {
    // They belong in the unscheduled queue, not in a day cell.
    const entries = toCalendarEntries(
      [],
      [makeJob({ id: "queued", scheduled_start: null })],
    );
    expect(entries).toEqual([]);
  });

  it("orders ties deterministically so refetches do not jitter", () => {
    const sameMoment = "2026-08-12T15:00:00.000Z";
    const first = toCalendarEntries(
      [makeAppointment({ scheduled_at: sameMoment })],
      [makeJob({ scheduled_start: sameMoment })],
    );
    const reversedInput = toCalendarEntries(
      [makeAppointment({ scheduled_at: sameMoment })],
      [makeJob({ scheduled_start: sameMoment })],
    );
    expect(first.map((e) => e.key)).toEqual(reversedInput.map((e) => e.key));
    expect(first[0].kind).toBe("appointment");
  });

  it("falls back to a readable title when an appointment has no service type", () => {
    expect(appointmentEntry(makeAppointment({ service_type: undefined })).title).toBe(
      "Appointment",
    );
    expect(appointmentEntry(makeAppointment({ service_type: "" })).title).toBe(
      "Appointment",
    );
  });

  it("returns null rather than an untimed entry for a queued job", () => {
    expect(jobEntry(makeJob({ scheduled_start: null }))).toBeNull();
  });
});

describe("entriesForDay", () => {
  it("groups by calendar day, not by 24-hour distance", () => {
    const entries = toCalendarEntries(
      [makeAppointment({ id: 1, scheduled_at: "2026-08-12T15:00:00.000Z" })],
      [makeJob({ id: "next-day", scheduled_start: "2026-08-13T15:00:00.000Z" })],
    );

    const day = new Date("2026-08-12T15:00:00.000Z");
    const onDay = entriesForDay(entries, day);
    expect(onDay).toHaveLength(1);
    expect(onDay[0].kind).toBe("appointment");
  });
});

describe("countByKind", () => {
  it("counts each species separately", () => {
    const entries = toCalendarEntries(
      [makeAppointment({ id: 1 }), makeAppointment({ id: 2 })],
      [makeJob({ id: "job-a" })],
    );
    expect(countByKind(entries)).toEqual({ appointments: 2, jobs: 1 });
  });

  it("is zeroed for an empty calendar", () => {
    expect(countByKind([])).toEqual({ appointments: 0, jobs: 0 });
  });
});

describe("upcomingEntries", () => {
  it("keeps only what is still ahead", () => {
    const now = new Date("2026-08-12T12:00:00.000Z");
    const entries = toCalendarEntries(
      [makeAppointment({ id: 1, scheduled_at: "2026-08-12T09:00:00.000Z" })],
      [makeJob({ id: "later", scheduled_start: "2026-08-12T17:00:00.000Z" })],
    );
    expect(upcomingEntries(entries, now).map((e) => e.key)).toEqual(["job-later"]);
  });

  it("keeps an anytime appointment upcoming until its day ends", () => {
    const entries = toCalendarEntries(
      [
        makeAppointment({
          id: 1,
          anytime: true,
          scheduled_at: "2026-08-12T12:00:00.000Z",
        }),
      ],
      [],
    );

    expect(
      upcomingEntries(entries, new Date("2026-08-12T20:00:00.000Z")).map((entry) =>
        entry.key,
      ),
    ).toEqual(["appointment-1"]);
    expect(
      upcomingEntries(entries, new Date("2026-08-13T12:00:00.000Z")),
    ).toEqual([]);
  });
});

describe("entryAccessibleLabel", () => {
  it("says which species a chip is, since the icon does not reach a reader", () => {
    const [appointment, job] = toCalendarEntries(
      [makeAppointment()],
      [makeJob()],
    ) as CalendarEntry[];
    expect(entryAccessibleLabel(appointment, "9:00 AM")).toBe(
      "Appointment: Gutter estimate, 9:00 AM",
    );
    expect(entryAccessibleLabel(job, "11:00 AM")).toBe("Job: Roof tune-up, 11:00 AM");
  });
});
