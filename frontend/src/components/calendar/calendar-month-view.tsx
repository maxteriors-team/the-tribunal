"use client";

/**
 * Month grid for the unified calendar screen.
 *
 * Presentational: given the week rows and the entries already fetched for the
 * visible range, it renders a Sun→Sat month grid with per-day chips for both
 * species of work — appointments and scheduled jobs — in one cell, in time
 * order. Clicking a chip bubbles the entry up via `onSelect`; the page owns the
 * two detail dialogs. Days outside the active month are dimmed.
 */
import { CalendarEntryChip } from "@/components/calendar/calendar-entry-chip";
import type { CalendarEntry } from "@/lib/calendar/calendar-entries";
import { entriesForDay } from "@/lib/calendar/calendar-entries";
import { cn } from "@/lib/utils";
import { formatDate, isSameDay, isSameMonth } from "@/lib/utils/date";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

/** How many chips fit in a cell before collapsing into a "+N more" row. */
const MAX_CHIPS_PER_DAY = 3;

interface CalendarMonthViewProps {
  weeks: Date[][];
  monthDate: Date;
  entries: CalendarEntry[];
  onSelect: (entry: CalendarEntry) => void;
  /** Reveals a day's hidden chips; the page owns which day is expanded. */
  expandedDayIso?: string | null;
  onExpandDay?: (dayIso: string) => void;
}

export function CalendarMonthView({
  weeks,
  monthDate,
  entries,
  onSelect,
  expandedDayIso = null,
  onExpandDay,
}: CalendarMonthViewProps) {
  const today = new Date();

  return (
    <div className="overflow-hidden rounded-lg border">
      {/* Weekday header */}
      <div className="grid grid-cols-7 border-b bg-muted/40">
        {WEEKDAY_LABELS.map((label) => (
          <div
            key={label}
            className="px-2 py-2 text-center text-xs font-semibold uppercase tracking-wide text-muted-foreground"
          >
            {label}
          </div>
        ))}
      </div>

      {/* Week rows */}
      <div>
        {weeks.map((week) => (
          <div
            key={week[0].toISOString()}
            className="grid grid-cols-7 border-b last:border-b-0"
          >
            {week.map((day) => {
              const dayIso = day.toISOString();
              const dayEntries = entriesForDay(entries, day);
              const inMonth = isSameMonth(day, monthDate);
              const isToday = isSameDay(day, today);
              const expanded = expandedDayIso === dayIso;
              const visible = expanded
                ? dayEntries
                : dayEntries.slice(0, MAX_CHIPS_PER_DAY);
              const overflow = dayEntries.length - visible.length;

              return (
                <div
                  key={dayIso}
                  className={cn(
                    "min-h-[104px] border-r p-1.5 last:border-r-0",
                    !inMonth && "bg-muted/30",
                  )}
                >
                  <div className="mb-1 flex items-center justify-between px-0.5">
                    <span
                      className={cn(
                        "flex size-6 items-center justify-center rounded-full text-xs font-medium",
                        isToday
                          ? "bg-primary text-primary-foreground"
                          : inMonth
                            ? "text-foreground"
                            : "text-muted-foreground",
                      )}
                    >
                      {formatDate(day, { pattern: "d" })}
                    </span>
                  </div>

                  <div className="space-y-1">
                    {visible.map((entry) => (
                      <CalendarEntryChip
                        key={entry.key}
                        entry={entry}
                        onSelect={onSelect}
                        density="compact"
                      />
                    ))}
                    {overflow > 0 &&
                      (onExpandDay ? (
                        <button
                          type="button"
                          onClick={() => onExpandDay(dayIso)}
                          className="w-full rounded px-1.5 text-left text-[11px] font-medium text-muted-foreground transition-colors duration-150 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                        >
                          +{overflow} more
                        </button>
                      ) : (
                        <div className="px-1.5 text-[11px] font-medium text-muted-foreground">
                          +{overflow} more
                        </div>
                      ))}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
