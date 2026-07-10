"use client";

/**
 * Jobber-style month grid for the calendar screen.
 *
 * Presentational: given the week rows and the appointments already fetched for
 * the visible range, it renders a Sun→Sat month grid with per-day appointment
 * chips. Clicking a chip bubbles the appointment up via `onSelect`; the page
 * owns the shared details dialog. Days outside the active month are dimmed.
 */
import { appointmentsForDay } from "@/lib/calendar/calendar-derivations";
import { cn } from "@/lib/utils";
import { formatDate, isSameDay, isSameMonth } from "@/lib/utils/date";
import type { Appointment } from "@/types";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] as const;

/** How many chips fit in a cell before collapsing into a "+N more" row. */
const MAX_CHIPS_PER_DAY = 3;

/** Chip tint by appointment status (background + text), matching the app palette. */
function chipClasses(status: Appointment["status"]): string {
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

interface CalendarMonthViewProps {
  weeks: Date[][];
  monthDate: Date;
  appointments: Appointment[];
  onSelect: (appointment: Appointment) => void;
}

export function CalendarMonthView({
  weeks,
  monthDate,
  appointments,
  onSelect,
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
              const dayAppointments = appointmentsForDay(appointments, day);
              const inMonth = isSameMonth(day, monthDate);
              const isToday = isSameDay(day, today);
              const overflow = dayAppointments.length - MAX_CHIPS_PER_DAY;

              return (
                <div
                  key={day.toISOString()}
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
                    {dayAppointments.slice(0, MAX_CHIPS_PER_DAY).map((apt) => (
                      <button
                        key={apt.id}
                        type="button"
                        onClick={() => onSelect(apt)}
                        title={`${formatDate(apt.scheduled_at, { pattern: "h:mm a" })} · ${
                          apt.service_type || "Appointment"
                        }`}
                        className={cn(
                          "flex w-full items-center gap-1 truncate rounded px-1.5 py-1 text-left text-[11px] font-medium transition-colors",
                          chipClasses(apt.status),
                        )}
                      >
                        <span className="shrink-0 tabular-nums opacity-80">
                          {formatDate(apt.scheduled_at, { pattern: "h:mm a" })}
                        </span>
                        <span className="truncate">
                          {apt.service_type || "Appointment"}
                        </span>
                      </button>
                    ))}
                    {overflow > 0 && (
                      <div className="px-1.5 text-[11px] font-medium text-muted-foreground">
                        +{overflow} more
                      </div>
                    )}
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
