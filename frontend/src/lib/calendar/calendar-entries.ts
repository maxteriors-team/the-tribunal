/**
 * The unified calendar's entry model.
 *
 * The schedule is one thing to the people who work it, but it arrives from two
 * endpoints with two shapes: appointments (sales/estimate visits, keyed by
 * `scheduled_at`) and jobs (field work, keyed by `scheduled_start`). This module
 * is the single place that reconciles them into one sortable, day-groupable
 * `CalendarEntry`, so the grid components never branch on where a row came from
 * and the two lists can never drift apart in ordering or day placement.
 *
 * Pure and unit-testable: no React, no fetching.
 */

import type { Job } from "@/lib/api/jobs";
import { isSameDay } from "@/lib/utils/date";
import type { Appointment } from "@/types";

/** What kind of work an entry represents. Drives the chip's icon and accent. */
export type CalendarEntryKind = "appointment" | "job";

interface CalendarEntryBase {
  /** Unique across both species, so it is safe as a React key in a merged list. */
  key: string;
  kind: CalendarEntryKind;
  /** When it happens. Already parsed, so sorting and grouping never re-parse. */
  startsAt: Date;
  /** The chip's visible label. */
  title: string;
}

export interface AppointmentEntry extends CalendarEntryBase {
  kind: "appointment";
  appointment: Appointment;
}

export interface JobEntry extends CalendarEntryBase {
  kind: "job";
  job: Job;
}

export type CalendarEntry = AppointmentEntry | JobEntry;

/** Wrap one appointment as a calendar entry. */
export function appointmentEntry(appointment: Appointment): AppointmentEntry {
  return {
    key: `appointment-${appointment.id}`,
    kind: "appointment",
    startsAt: new Date(appointment.scheduled_at),
    title: appointment.service_type || "Appointment",
    appointment,
  };
}

/**
 * Wrap one scheduled job as a calendar entry.
 *
 * Returns null for a job with no time window: it belongs in the unscheduled
 * queue, not in a day cell. Callers filter on the null rather than guessing.
 */
export function jobEntry(job: Job): JobEntry | null {
  if (!job.scheduled_start) return null;
  return {
    key: `job-${job.id}`,
    kind: "job",
    startsAt: new Date(job.scheduled_start),
    title: job.title,
    job,
  };
}

/**
 * Merge both sources into one chronological list.
 *
 * Sorted by start time so a day cell reads top-to-bottom as the day actually
 * runs, regardless of which endpoint each row came from. Ties keep appointments
 * first, purely so the order is stable across refetches rather than jittering
 * with server response order.
 */
export function toCalendarEntries(
  appointments: readonly Appointment[],
  jobs: readonly Job[],
): CalendarEntry[] {
  const entries: CalendarEntry[] = [
    ...appointments.map(appointmentEntry),
    ...jobs.map(jobEntry).filter((entry): entry is JobEntry => entry !== null),
  ];
  return entries.sort((a, b) => {
    const delta = a.startsAt.getTime() - b.startsAt.getTime();
    if (delta !== 0) return delta;
    if (a.kind === b.kind) return a.key.localeCompare(b.key);
    return a.kind === "appointment" ? -1 : 1;
  });
}

/** Entries falling on the given calendar day, in time order. */
export function entriesForDay(
  entries: readonly CalendarEntry[],
  day: Date,
): CalendarEntry[] {
  return entries.filter((entry) => isSameDay(entry.startsAt, day));
}

/** Entries happening today, relative to `now`. */
export function todaysEntries(
  entries: readonly CalendarEntry[],
  now: Date = new Date(),
): CalendarEntry[] {
  return entriesForDay(entries, now);
}

/** Entries still ahead of `now`, in time order. */
export function upcomingEntries(
  entries: readonly CalendarEntry[],
  now: Date = new Date(),
): CalendarEntry[] {
  return entries.filter((entry) => entry.startsAt.getTime() > now.getTime());
}

/**
 * Screen-reader label for a chip.
 *
 * The visual chip distinguishes species with an icon and an accent rail, neither
 * of which reaches assistive technology, so the accessible name has to say which
 * kind of work this is in words.
 */
export function entryAccessibleLabel(entry: CalendarEntry, timeLabel: string): string {
  const kind = entry.kind === "job" ? "Job" : "Appointment";
  return `${kind}: ${entry.title}, ${timeLabel}`;
}

/** How many of each species are in a list — for the "N jobs, N appointments" counts. */
export function countByKind(entries: readonly CalendarEntry[]): {
  appointments: number;
  jobs: number;
} {
  let appointments = 0;
  let jobs = 0;
  for (const entry of entries) {
    if (entry.kind === "appointment") appointments += 1;
    else jobs += 1;
  }
  return { appointments, jobs };
}
