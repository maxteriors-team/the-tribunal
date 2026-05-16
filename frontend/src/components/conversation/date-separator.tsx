"use client";


import { Separator } from "@/components/ui/separator";
import { formatLongDate, isToday, isYesterday } from "@/lib/utils/date";

function formatDateLabel(date: Date): string {
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  return formatLongDate(date);
}

export function DateSeparator({ date }: { date: Date }) {
  return (
    <div className="flex items-center gap-4 py-4 px-4">
      <Separator className="flex-1" />
      <span className="text-xs text-muted-foreground font-medium">
        {formatDateLabel(date)}
      </span>
      <Separator className="flex-1" />
    </div>
  );
}
