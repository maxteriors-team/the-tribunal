"use client";

import {
  ArrowDownLeft,
  ArrowUpRight,
  Bot,
  CalendarDays,
  FileText,
  History,
  MessageSquare,
  PhoneCall,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  PageEmptyState,
  PageErrorState,
} from "@/components/ui/page-state";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useContactAppointments,
  useContactQuotes,
} from "@/hooks/useContactRecords";
import { useContactTimeline } from "@/hooks/useContacts";
import {
  buildContactHistory,
  countByKind,
  groupByDay,
  splitUpcoming,
  HISTORY_KIND_LABELS,
  type HistoryEvent,
  type HistoryKind,
} from "@/lib/contacts/contact-history";
import { appointmentStatusColors } from "@/lib/status-colors";
import { cn } from "@/lib/utils";
import { formatDate, formatTime, isToday, isYesterday } from "@/lib/utils/date";

const KIND_ICONS: Record<HistoryKind, typeof MessageSquare> = {
  message: MessageSquare,
  call: PhoneCall,
  appointment: CalendarDays,
  quote: FileText,
};

const FILTERS: Array<HistoryKind | "all"> = [
  "all",
  "message",
  "call",
  "appointment",
  "quote",
];

function dayLabel(day: string): string {
  const date = new Date(day);
  if (isToday(date)) return "Today";
  if (isYesterday(date)) return "Yesterday";
  return formatDate(date, { pattern: "EEEE, MMM d, yyyy" });
}

function statusBadgeClass(event: HistoryEvent): string | undefined {
  if (event.kind === "appointment" && event.status) {
    return appointmentStatusColors[event.status];
  }
  return undefined;
}

function HistoryRow({
  event,
  showDate = false,
}: {
  event: HistoryEvent;
  /** Rows outside a day group (upcoming) need the date, not just the time. */
  showDate?: boolean;
}) {
  const Icon = KIND_ICONS[event.kind];
  const DirectionIcon =
    event.direction === "inbound"
      ? ArrowDownLeft
      : event.direction === "outbound"
        ? ArrowUpRight
        : null;

  return (
    <li className="flex gap-3 py-3">
      <div
        className="bg-muted text-muted-foreground mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg"
        aria-hidden
      >
        <Icon className="size-4" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-sm font-medium">{event.title}</span>
          {DirectionIcon && (
            <DirectionIcon className="text-muted-foreground size-3.5" aria-hidden />
          )}
          {event.isAi && (
            <Badge variant="outline" className="gap-1 px-1.5 py-0 text-[10px]">
              <Bot className="size-3" aria-hidden />
              AI
            </Badge>
          )}
          {event.status && (
            <Badge
              variant="outline"
              className={cn("px-1.5 py-0 text-[10px] capitalize", statusBadgeClass(event))}
            >
              {event.status.replace(/_/g, " ")}
            </Badge>
          )}
          {event.meta.map((fact) => (
            <span key={fact} className="text-muted-foreground text-xs">
              {fact}
            </span>
          ))}
          <time
            className="text-muted-foreground ml-auto shrink-0 text-xs tabular-nums"
            dateTime={event.timestamp}
          >
            {showDate
              ? `${formatDate(event.timestamp, { pattern: "EEE, MMM d" })} · ${formatTime(event.timestamp)}`
              : formatTime(event.timestamp)}
          </time>
        </div>

        {event.body && (
          <p className="text-muted-foreground mt-1 text-sm break-words whitespace-pre-line">
            {event.body}
          </p>
        )}
      </div>
    </li>
  );
}

function HistorySection({
  label,
  events,
  showDates = false,
}: {
  label: string;
  events: HistoryEvent[];
  showDates?: boolean;
}) {
  return (
    <section aria-label={label}>
      <h3 className="text-muted-foreground bg-background/95 sticky top-0 z-10 py-2 text-xs font-medium tracking-wide uppercase">
        {label}
      </h3>
      <ul className="divide-border/60 divide-y">
        {events.map((event) => (
          <HistoryRow key={event.id} event={event} showDate={showDates} />
        ))}
      </ul>
    </section>
  );
}

function HistorySkeleton() {
  return (
    <div className="space-y-4" aria-hidden>
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="flex gap-3">
          <Skeleton className="size-8 shrink-0 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-4 w-full max-w-md" />
          </div>
        </div>
      ))}
    </div>
  );
}

interface ContactHistoryProps {
  workspaceId: string | null | undefined;
  contactId: number;
  className?: string;
}

/**
 * Everything that has happened with one contact — messages, calls,
 * appointments and quotes — merged into a single reverse-chronological record.
 */
export function ContactHistory({
  workspaceId,
  contactId,
  className,
}: ContactHistoryProps) {
  const [filter, setFilter] = useState<HistoryKind | "all">("all");

  const timelineQuery = useContactTimeline(workspaceId ?? "", contactId);
  const appointmentsQuery = useContactAppointments(workspaceId, contactId);
  const quotesQuery = useContactQuotes(workspaceId, contactId);

  const events = useMemo(
    () =>
      buildContactHistory({
        timeline: timelineQuery.data,
        appointments: appointmentsQuery.data?.items,
        quotes: quotesQuery.data?.items,
      }),
    [timelineQuery.data, appointmentsQuery.data, quotesQuery.data],
  );

  const counts = useMemo(() => countByKind(events), [events]);
  const visible = useMemo(
    () => (filter === "all" ? events : events.filter((e) => e.kind === filter)),
    [events, filter],
  );
  const { upcoming, past } = useMemo(() => splitUpcoming(visible), [visible]);
  const groups = useMemo(() => groupByDay(past), [past]);

  const isPending =
    timelineQuery.isPending || appointmentsQuery.isPending || quotesQuery.isPending;
  const isError =
    timelineQuery.isError || appointmentsQuery.isError || quotesQuery.isError;

  const retry = () => {
    void timelineQuery.refetch();
    void appointmentsQuery.refetch();
    void quotesQuery.refetch();
  };

  return (
    <div className={cn("flex min-w-0 flex-col gap-4", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-base font-semibold">History</h2>
        <div
          role="group"
          aria-label="Filter history by type"
          className="bg-muted/40 inline-flex flex-wrap items-center gap-1 rounded-lg border p-1"
        >
          {FILTERS.map((kind) => {
            const isActive = filter === kind;
            const count = kind === "all" ? events.length : counts[kind];
            return (
              <button
                key={kind}
                type="button"
                aria-pressed={isActive}
                onClick={() => setFilter(kind)}
                className={cn(
                  "focus-visible:ring-ring/50 rounded-md px-2.5 py-1 text-xs font-medium transition-colors outline-none focus-visible:ring-[3px]",
                  isActive
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {kind === "all" ? "All" : HISTORY_KIND_LABELS[kind]}
                <span className="ml-1 tabular-nums opacity-60">{count}</span>
              </button>
            );
          })}
        </div>
      </div>

      {isError ? (
        <PageErrorState
          className="min-h-[200px]"
          message="Couldn't load this contact's history."
          onRetry={retry}
        />
      ) : isPending ? (
        <HistorySkeleton />
      ) : visible.length === 0 ? (
        <PageEmptyState
          className="min-h-[200px]"
          icon={<History className="size-8" />}
          title={
            events.length === 0 ? "No activity yet" : "Nothing of this type yet"
          }
          description={
            events.length === 0
              ? "Messages, calls, appointments and quotes will appear here as they happen."
              : "Try a different filter to see the rest of this contact's history."
          }
        />
      ) : (
        <div className="space-y-4">
          {upcoming.length > 0 && (
            <HistorySection label="Upcoming" events={upcoming} showDates />
          )}
          {groups.map((group) => (
            <HistorySection
              key={group.day}
              label={dayLabel(group.day)}
              events={group.events}
            />
          ))}
        </div>
      )}
    </div>
  );
}
