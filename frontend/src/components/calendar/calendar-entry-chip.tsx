"use client";

/**
 * One chip on the unified calendar, for either species of entry.
 *
 * Jobs and appointments share the grid, so they must be told apart at a glance
 * without the eye having to decode two different tints. The species signal is
 * therefore structural, not chromatic: a job carries a left accent rail and a
 * wrench, an appointment carries a clock and no rail. That survives forced
 * colors and colour-vision differences, where a tint-only distinction does not,
 * and it leaves the existing status tint free to keep meaning what it already
 * means everywhere else in the app (scheduled / done / cancelled).
 */

import { CalendarClock, Wrench } from "lucide-react";

import type { JobStatus } from "@/lib/api/jobs";
import type { CalendarEntry } from "@/lib/calendar/calendar-entries";
import { entryAccessibleLabel } from "@/lib/calendar/calendar-entries";
import { jobStatusColors } from "@/lib/jobs/job-derivations";
import { cn } from "@/lib/utils";
import { formatDate } from "@/lib/utils/date";
import type { Appointment } from "@/types";

/** Status tint for an appointment chip, matching the app's appointment palette. */
function appointmentChipClasses(status: Appointment["status"]): string {
  switch (status) {
    case "completed":
      return "bg-success/15 text-success hover:bg-success/25";
    case "no_show":
      return "bg-destructive/15 text-destructive hover:bg-destructive/25";
    case "cancelled":
      return "bg-muted text-muted-foreground line-through hover:bg-muted/80";
    default:
      return "bg-primary/15 text-primary hover:bg-primary/25";
  }
}

/**
 * Status tint for a job chip.
 *
 * `jobStatusColors` is the badge palette used on the job cards and detail
 * dialog; reusing it keeps one job status colour in the product. The border
 * classes it carries are dropped here because the chip supplies its own rail.
 */
function jobChipClasses(status: JobStatus): string {
  const tint = jobStatusColors[status] ?? "bg-muted text-muted-foreground";
  return cn(
    tint.replace(/\bborder-\S+/g, "").trim(),
    "hover:brightness-95 dark:hover:brightness-110",
  );
}

export function chipClassesForEntry(entry: CalendarEntry): string {
  return entry.kind === "appointment"
    ? appointmentChipClasses(entry.appointment.status)
    : jobChipClasses(entry.job.status);
}

/**
 * Seven columns across means roughly 90px per day, and a single line of
 * "[icon] 6:57 PM Gutter clean" simply does not fit — the title is what gets
 * truncated away, which is the one part that says what the work is. So the chip
 * has three densities, chosen by how much room the surface actually has:
 *
 * - `comfortable`: one line, full time, icon. For the wide sidebar lists.
 * - `compact`: one line, no icon, short time ("6:57p"). For month cells, which
 *   are short as well as narrow — three chips have to fit.
 * - `stacked`: time above, title below. For week columns, which are just as
 *   narrow but tall, so the second line is free.
 *
 * Jobs keep their accent rail at every density, and the full time and the
 * species stay in the accessible name and tooltip regardless.
 */
type ChipDensity = "comfortable" | "compact" | "stacked";

function compactTime(at: Date): string {
  return formatDate(at, { pattern: "h:mma" })
    .replace(/\s+/g, "")
    .replace(/AM$/i, "a")
    .replace(/PM$/i, "p");
}

interface CalendarEntryChipProps {
  entry: CalendarEntry;
  onSelect: (entry: CalendarEntry) => void;
  /** Adds the customer line — worth the row in a wide column, not in a narrow one. */
  showDetail?: boolean;
  density?: ChipDensity;
  className?: string;
}

export function CalendarEntryChip({
  entry,
  onSelect,
  showDetail = false,
  density = "comfortable",
  className,
}: CalendarEntryChipProps) {
  const isAnytime = entry.kind === "appointment" && entry.appointment.anytime;
  const timeLabel = isAnytime ? "Any time" : formatDate(entry.startsAt, { pattern: "h:mm a" });
  const isCompact = density === "compact";
  const isStacked = density === "stacked";
  const isJob = entry.kind === "job";
  const Icon = isJob ? Wrench : CalendarClock;
  const detailLine =
    entry.kind === "job"
      ? (entry.job.customer?.name ?? "")
      : [entry.appointment.contact?.first_name, entry.appointment.contact?.last_name]
          .filter(Boolean)
          .join(" ");

  return (
    <button
      type="button"
      onClick={() => onSelect(entry)}
      aria-label={entryAccessibleLabel(entry, timeLabel)}
      title={`${timeLabel} · ${entry.title}`}
      className={cn(
        "w-full rounded text-left text-[11px] font-medium",
        isCompact ? "px-1 py-0.5" : "px-1.5 py-1",
        "transition-colors duration-150 motion-reduce:transition-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
        isJob && "border-l-2 border-current",
        chipClassesForEntry(entry),
        className,
      )}
    >
      <span className={cn("flex items-center", isCompact ? "gap-1" : "gap-1.5")}>
        {!isCompact && <Icon aria-hidden="true" className="size-3 shrink-0 opacity-70" />}
        <span className="shrink-0 tabular-nums opacity-80">
          {isAnytime
            ? "Any time"
            : isCompact || isStacked
              ? compactTime(entry.startsAt)
              : timeLabel}
        </span>
        {!isStacked && <span className="truncate">{entry.title}</span>}
      </span>
      {isStacked && (
        <span className="mt-0.5 line-clamp-2 block leading-tight">{entry.title}</span>
      )}
      {showDetail && detailLine && (
        <span className="mt-0.5 block truncate text-[10px] font-normal opacity-75">
          {detailLine}
        </span>
      )}
    </button>
  );
}
