import { describe, expect, it } from "vitest";

import {
  appointmentFormSchema,
  buildCreateAppointmentRequest,
  buildScheduledAtISO,
  DURATION_OPTIONS,
  formatTimeSlot,
  generateTimeSlots,
  type AppointmentFormValues,
} from "./appointment-form";

describe("generateTimeSlots", () => {
  it("generates 8AM-6PM in 30-minute increments by default", () => {
    const slots = generateTimeSlots();
    expect(slots[0]).toBe("08:00");
    expect(slots[1]).toBe("08:30");
    expect(slots.at(-1)).toBe("18:00");
    // 8:00..17:30 is 20 slots, plus 18:00 = 21
    expect(slots).toHaveLength(21);
  });

  it("does not emit slots past the end hour", () => {
    const slots = generateTimeSlots(8, 18, 30);
    expect(slots).not.toContain("18:30");
  });

  it("respects custom range and step", () => {
    expect(generateTimeSlots(9, 11, 60)).toEqual(["09:00", "10:00", "11:00"]);
  });

  it("supports 15-minute increments", () => {
    const slots = generateTimeSlots(9, 9, 15);
    expect(slots).toEqual(["09:00"]);
    const slots2 = generateTimeSlots(9, 10, 15);
    expect(slots2).toEqual(["09:00", "09:15", "09:30", "09:45", "10:00"]);
  });

  it("zero-pads hours and minutes", () => {
    const slots = generateTimeSlots(0, 1, 30);
    expect(slots).toEqual(["00:00", "00:30", "01:00"]);
  });

  it("rejects invalid step", () => {
    expect(() => generateTimeSlots(8, 18, 7)).toThrow();
    expect(() => generateTimeSlots(8, 18, 0)).toThrow();
  });

  it("rejects start after end", () => {
    expect(() => generateTimeSlots(18, 8)).toThrow();
  });
});

describe("formatTimeSlot", () => {
  it("shows operator-facing times in 12-hour format", () => {
    expect(formatTimeSlot("00:00")).toBe("12:00 AM");
    expect(formatTimeSlot("08:30")).toBe("8:30 AM");
    expect(formatTimeSlot("12:00")).toBe("12:00 PM");
    expect(formatTimeSlot("18:00")).toBe("6:00 PM");
  });

  it("rejects malformed times", () => {
    expect(() => formatTimeSlot("1800")).toThrow();
    expect(() => formatTimeSlot("25:00")).toThrow();
  });
});

describe("buildScheduledAtISO", () => {
  it("combines date and time into an ISO string at the chosen local time", () => {
    const date = new Date(2025, 0, 15); // Jan 15 2025, local midnight
    const iso = buildScheduledAtISO(date, "14:30");
    const parsed = new Date(iso);
    expect(parsed.getFullYear()).toBe(2025);
    expect(parsed.getMonth()).toBe(0);
    expect(parsed.getDate()).toBe(15);
    expect(parsed.getHours()).toBe(14);
    expect(parsed.getMinutes()).toBe(30);
    expect(parsed.getSeconds()).toBe(0);
  });

  it("does not mutate the input date", () => {
    const date = new Date(2025, 0, 15, 9, 0, 0, 0);
    const before = date.getTime();
    buildScheduledAtISO(date, "23:00");
    expect(date.getTime()).toBe(before);
  });

  it("rejects malformed time strings", () => {
    const date = new Date(2025, 0, 15);
    expect(() => buildScheduledAtISO(date, "1430")).toThrow();
    expect(() => buildScheduledAtISO(date, "25:00")).toThrow();
    expect(() => buildScheduledAtISO(date, "12:99")).toThrow();
    expect(() => buildScheduledAtISO(date, "ab:cd")).toThrow();
  });
});

describe("buildCreateAppointmentRequest", () => {
  const base: AppointmentFormValues = {
    date: new Date(2025, 5, 1),
    time: "10:00",
    duration_minutes: 45,
    service_type: "Consultation",
    notes: "Bring docs",
    agent_id: "agent-1",
  };

  it("maps populated values to the API request", () => {
    const req = buildCreateAppointmentRequest(base, 42);
    expect(req.contact_id).toBe(42);
    expect(req.duration_minutes).toBe(45);
    expect(req.service_type).toBe("Consultation");
    expect(req.notes).toBe("Bring docs");
    expect(req.agent_id).toBe("agent-1");
    expect(new Date(req.scheduled_at).getHours()).toBe(10);
  });

  it("normalizes empty optional strings to undefined", () => {
    const req = buildCreateAppointmentRequest(
      { ...base, service_type: "", notes: "", agent_id: "" },
      7,
    );
    expect(req.service_type).toBeUndefined();
    expect(req.notes).toBeUndefined();
    expect(req.agent_id).toBeUndefined();
  });
});

describe("appointmentFormSchema", () => {
  it("accepts a valid payload", () => {
    const result = appointmentFormSchema.safeParse({
      date: new Date(),
      time: "09:00",
      duration_minutes: 30,
    });
    expect(result.success).toBe(true);
  });

  it("requires a date and time", () => {
    const result = appointmentFormSchema.safeParse({
      duration_minutes: 30,
      time: "",
    });
    expect(result.success).toBe(false);
  });

  it("enforces duration bounds", () => {
    expect(
      appointmentFormSchema.safeParse({
        date: new Date(),
        time: "09:00",
        duration_minutes: 5,
      }).success,
    ).toBe(false);
    expect(
      appointmentFormSchema.safeParse({
        date: new Date(),
        time: "09:00",
        duration_minutes: 600,
      }).success,
    ).toBe(false);
  });
});

describe("DURATION_OPTIONS", () => {
  it("all values are within the schema bounds", () => {
    for (const opt of DURATION_OPTIONS) {
      expect(opt.value).toBeGreaterThanOrEqual(15);
      expect(opt.value).toBeLessThanOrEqual(480);
    }
  });
});
