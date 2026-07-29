import { formatCurrency } from "@/lib/utils/number";
import type { Appointment, Quote, TimelineItem } from "@/types";

/** Activity categories a contact record can accumulate. */
export type HistoryKind = "message" | "call" | "appointment" | "quote";

export interface HistoryEvent {
  /** Stable across refetches: source type + source id. */
  id: string;
  kind: HistoryKind;
  /** ISO timestamp the event happened (or is due, for appointments). */
  timestamp: string;
  title: string;
  /** Free text detail: message body, call summary, appointment notes. */
  body?: string | null;
  /** Short muted facts rendered after the title (duration, totals). */
  meta: string[];
  /** Lifecycle state of the underlying record, when it has one. */
  status?: string | null;
  direction?: "inbound" | "outbound";
  isAi?: boolean;
}

export const HISTORY_KIND_LABELS: Record<HistoryKind, string> = {
  message: "Messages",
  call: "Calls",
  appointment: "Appointments",
  quote: "Quotes",
};

/** "4m 12s" / "48s" — call length in words rather than raw seconds. */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest === 0 ? `${minutes}m` : `${minutes}m ${rest}s`;
}

function messageTitle(item: TimelineItem): string {
  if (item.direction === "inbound") return "Message received";
  return item.is_ai ? "AI message sent" : "Message sent";
}

function callTitle(item: TimelineItem): string {
  return item.direction === "inbound" ? "Inbound call" : "Outbound call";
}

function timelineEvent(item: TimelineItem): HistoryEvent {
  const isCall = item.type === "call";
  const meta: string[] = [];

  if (isCall && item.duration_seconds) {
    meta.push(formatDuration(item.duration_seconds));
  }
  if (item.booking_outcome === "success") {
    meta.push("Booked");
  }

  return {
    id: `${item.original_type}:${item.original_id}`,
    kind: isCall ? "call" : "message",
    timestamp: item.timestamp,
    title: isCall ? callTitle(item) : messageTitle(item),
    body: isCall ? (item.transcript ?? item.content) : item.content,
    meta,
    status: item.status ?? null,
    direction: item.direction,
    isAi: item.is_ai,
  };
}

function appointmentEvent(appointment: Appointment): HistoryEvent {
  const meta = [`${appointment.duration_minutes} min`];

  return {
    id: `appointment:${appointment.id}`,
    kind: "appointment",
    timestamp: appointment.scheduled_at,
    title: appointment.service_type || "Appointment",
    body: appointment.notes ?? null,
    meta,
    status: appointment.status,
  };
}

function quoteEvent(quote: Quote): HistoryEvent {
  return {
    id: `quote:${quote.id}`,
    kind: "quote",
    // Quotes are filed under when they were sent, falling back to creation.
    timestamp: quote.sent_at ?? quote.created_at,
    title: quote.title ? `Quote ${quote.number} · ${quote.title}` : `Quote ${quote.number}`,
    body: null,
    meta: [formatCurrency(quote.total, quote.currency)],
    status: quote.status,
  };
}

export interface BuildContactHistoryArgs {
  timeline?: TimelineItem[];
  appointments?: Appointment[];
  quotes?: Quote[];
}

/**
 * Merge every per-contact record source into one activity list.
 *
 * Returns newest first. Appointments dated in the future stay in the list —
 * callers split them out as "upcoming" via {@link splitUpcoming} so a booking
 * next week never masquerades as something that already happened.
 */
export function buildContactHistory({
  timeline = [],
  appointments = [],
  quotes = [],
}: BuildContactHistoryArgs): HistoryEvent[] {
  const events: HistoryEvent[] = [
    ...timeline.map(timelineEvent),
    ...appointments.map(appointmentEvent),
    ...quotes.map(quoteEvent),
  ];

  return events.sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );
}

/**
 * Split a newest-first history into future-dated events (soonest first) and
 * everything that has already happened.
 */
export function splitUpcoming(
  events: HistoryEvent[],
  now: Date = new Date(),
): { upcoming: HistoryEvent[]; past: HistoryEvent[] } {
  const upcoming: HistoryEvent[] = [];
  const past: HistoryEvent[] = [];

  for (const event of events) {
    if (new Date(event.timestamp).getTime() > now.getTime()) {
      upcoming.push(event);
    } else {
      past.push(event);
    }
  }

  upcoming.reverse();
  return { upcoming, past };
}

/** Count events per kind for the filter control. */
export function countByKind(events: HistoryEvent[]): Record<HistoryKind, number> {
  const counts: Record<HistoryKind, number> = {
    message: 0,
    call: 0,
    appointment: 0,
    quote: 0,
  };
  for (const event of events) counts[event.kind] += 1;
  return counts;
}

/** Group events into consecutive same-day buckets, preserving input order. */
export function groupByDay(events: HistoryEvent[]): Array<{ day: string; events: HistoryEvent[] }> {
  const groups: Array<{ day: string; events: HistoryEvent[] }> = [];

  for (const event of events) {
    const day = new Date(event.timestamp).toDateString();
    const last = groups[groups.length - 1];
    if (last && last.day === day) {
      last.events.push(event);
    } else {
      groups.push({ day, events: [event] });
    }
  }

  return groups;
}
