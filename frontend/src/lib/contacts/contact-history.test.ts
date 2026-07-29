import { describe, expect, it } from "vitest";

import type { Appointment, Quote, TimelineItem } from "@/types";

import {
  buildContactHistory,
  countByKind,
  formatDuration,
  groupByDay,
  splitUpcoming,
} from "./contact-history";

function makeTimelineItem(overrides: Partial<TimelineItem> = {}): TimelineItem {
  return {
    id: "m1",
    type: "sms",
    timestamp: "2026-05-20T15:00:00.000Z",
    direction: "inbound",
    is_ai: false,
    content: "Hello there",
    original_id: "m1",
    original_type: "sms_message",
    ...overrides,
  };
}

function makeAppointment(overrides: Partial<Appointment> = {}): Appointment {
  return {
    id: 7,
    contact_id: 1,
    scheduled_at: "2026-05-21T15:00:00.000Z",
    duration_minutes: 60,
    status: "scheduled",
    created_at: "2026-05-01T00:00:00.000Z",
    updated_at: "2026-05-01T00:00:00.000Z",
    ...overrides,
  };
}

function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: "q1",
    workspace_id: "ws",
    contact_id: 1,
    number: "Q-1001",
    status: "sent",
    subtotal: 600,
    tax_amount: 40,
    discount_amount: 0,
    total: 640,
    currency: "USD",
    created_at: "2026-05-19T12:00:00.000Z",
    updated_at: "2026-05-19T12:00:00.000Z",
    ...overrides,
  } as Quote;
}

describe("buildContactHistory", () => {
  it("merges every source into one newest-first list", () => {
    const events = buildContactHistory({
      timeline: [makeTimelineItem()],
      appointments: [makeAppointment()],
      quotes: [makeQuote()],
    });

    expect(events.map((e) => e.kind)).toEqual(["appointment", "message", "quote"]);
    expect(events.map((e) => e.id)).toEqual([
      "appointment:7",
      "sms_message:m1",
      "quote:q1",
    ]);
  });

  it("classifies voice timeline items as calls and keeps their duration", () => {
    const [event] = buildContactHistory({
      timeline: [
        makeTimelineItem({
          type: "call",
          direction: "outbound",
          duration_seconds: 214,
          transcript: "Agent: hello",
          original_type: "call_record",
        }),
      ],
    });

    expect(event.kind).toBe("call");
    expect(event.title).toBe("Outbound call");
    expect(event.meta).toContain("3m 34s");
    expect(event.body).toBe("Agent: hello");
  });

  it("labels AI replies separately from human sends", () => {
    const [ai, human] = buildContactHistory({
      timeline: [
        makeTimelineItem({
          id: "a",
          original_id: "a",
          direction: "outbound",
          is_ai: true,
          timestamp: "2026-05-20T16:00:00.000Z",
        }),
        makeTimelineItem({
          id: "b",
          original_id: "b",
          direction: "outbound",
          is_ai: false,
          timestamp: "2026-05-20T14:00:00.000Z",
        }),
      ],
    });

    expect(ai.title).toBe("AI message sent");
    expect(human.title).toBe("Message sent");
  });

  it("files quotes under when they were sent and shows the total", () => {
    const [event] = buildContactHistory({
      quotes: [makeQuote({ sent_at: "2026-05-25T09:00:00.000Z", title: "Roofline" })],
    });

    expect(event.timestamp).toBe("2026-05-25T09:00:00.000Z");
    expect(event.title).toBe("Quote Q-1001 · Roofline");
    expect(event.meta).toEqual(["$640.00"]);
  });

  it("returns an empty list when the contact has no records", () => {
    expect(buildContactHistory({})).toEqual([]);
  });
});

describe("splitUpcoming", () => {
  it("separates future-dated events, soonest first", () => {
    const events = buildContactHistory({
      appointments: [
        makeAppointment({ id: 1, scheduled_at: "2026-06-10T10:00:00.000Z" }),
        makeAppointment({ id: 2, scheduled_at: "2026-06-02T10:00:00.000Z" }),
        makeAppointment({ id: 3, scheduled_at: "2026-05-01T10:00:00.000Z" }),
      ],
    });

    const { upcoming, past } = splitUpcoming(events, new Date("2026-05-20T00:00:00.000Z"));

    expect(upcoming.map((e) => e.id)).toEqual(["appointment:2", "appointment:1"]);
    expect(past.map((e) => e.id)).toEqual(["appointment:3"]);
  });
});

describe("groupByDay", () => {
  it("buckets consecutive same-day events together", () => {
    const events = buildContactHistory({
      timeline: [
        makeTimelineItem({ id: "a", original_id: "a", timestamp: "2026-05-20T15:00:00.000Z" }),
        makeTimelineItem({ id: "b", original_id: "b", timestamp: "2026-05-20T09:00:00.000Z" }),
        makeTimelineItem({ id: "c", original_id: "c", timestamp: "2026-05-19T09:00:00.000Z" }),
      ],
    });

    const groups = groupByDay(events);

    expect(groups).toHaveLength(2);
    expect(groups[0].events.map((e) => e.id)).toEqual(["sms_message:a", "sms_message:b"]);
    expect(groups[1].events.map((e) => e.id)).toEqual(["sms_message:c"]);
  });
});

describe("countByKind", () => {
  it("counts each activity type", () => {
    const counts = countByKind(
      buildContactHistory({
        timeline: [
          makeTimelineItem(),
          makeTimelineItem({ id: "c1", original_id: "c1", type: "call" }),
        ],
        appointments: [makeAppointment()],
      }),
    );

    expect(counts).toEqual({ message: 1, call: 1, appointment: 1, quote: 0 });
  });
});

describe("formatDuration", () => {
  it.each([
    [45, "45s"],
    [60, "1m"],
    [214, "3m 34s"],
  ])("formats %i seconds as %s", (seconds, expected) => {
    expect(formatDuration(seconds)).toBe(expected);
  });
});
