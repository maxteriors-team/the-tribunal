"use client";

import { CalendarDays } from "lucide-react";
import { useState } from "react";
import type { DateRange as CalendarRange } from "react-day-picker";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar-lazy";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Separator } from "@/components/ui/separator";
import { addDays, endOfMonth, startOfMonth } from "@/lib/utils/date";

import {
  currentMonthRange,
  describeRange,
  fromIsoDate,
  toIsoDate,
  type DateRange,
} from "./sales-performance-metrics";

/**
 * Named windows an owner actually reviews. Built from the shared `date-fns`
 * wrappers in `@/lib/utils/date` rather than a second date library.
 */
const PRESETS: { label: string; build: (today: Date) => DateRange }[] = [
  { label: "This month", build: (today) => currentMonthRange(today) },
  {
    label: "Last month",
    build: (today) => {
      const lastMonth = addDays(startOfMonth(today), -1);
      return {
        from: toIsoDate(startOfMonth(lastMonth)),
        to: toIsoDate(endOfMonth(lastMonth)),
      };
    },
  },
  {
    label: "Last 30 days",
    build: (today) => ({ from: toIsoDate(addDays(today, -29)), to: toIsoDate(today) }),
  },
  {
    label: "Last 90 days",
    build: (today) => ({ from: toIsoDate(addDays(today, -89)), to: toIsoDate(today) }),
  },
];

export interface ReportDateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
}

/**
 * Inclusive date-window picker for the reports surface.
 *
 * Future dates stay selectable on purpose: the default window is the *whole*
 * current calendar month, so its end date is usually still ahead of today.
 */
export function ReportDateRangePicker({
  value,
  onChange,
}: ReportDateRangePickerProps) {
  const [open, setOpen] = useState(false);

  const selected: CalendarRange = {
    from: fromIsoDate(value.from),
    to: fromIsoDate(value.to),
  };

  const handleSelect = (range: CalendarRange | undefined) => {
    if (!range?.from) return;
    // react-day-picker reports the half-finished range on the first click; hold
    // the popover open until both edges exist so one click never fires a
    // single-day report the user did not ask for.
    if (!range.to) return;
    onChange({ from: toIsoDate(range.from), to: toIsoDate(range.to) });
    setOpen(false);
  };

  const applyPreset = (preset: (typeof PRESETS)[number]) => {
    onChange(preset.build(new Date()));
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          className="gap-2"
          aria-label={`Change date range. Currently ${describeRange(value)}`}
        >
          <CalendarDays className="size-4 text-muted-foreground" />
          <span className="tabular-nums">{describeRange(value)}</span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-auto p-0" align="end">
        <div className="flex flex-col gap-1 p-2">
          {PRESETS.map((preset) => (
            <Button
              key={preset.label}
              variant="ghost"
              size="sm"
              className="justify-start font-normal"
              onClick={() => applyPreset(preset)}
            >
              {preset.label}
            </Button>
          ))}
        </div>
        <Separator />
        {/* No `autoFocus`: Radix already moves focus into the popover, landing
            on the presets, which is the faster keyboard path anyway. */}
        <Calendar
          mode="range"
          defaultMonth={selected.from}
          selected={selected}
          onSelect={handleSelect}
          numberOfMonths={1}
        />
      </PopoverContent>
    </Popover>
  );
}
