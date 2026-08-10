import * as z from "zod";

import type { CreateAppointmentRequest } from "@/lib/api/appointments";

/**
 * Shared appointment scheduling form logic used by both the calendar
 * "New Appointment" dialog and the contact "Schedule Appointment" dialog.
 */

export const appointmentFormSchema = z.object({
  date: z.date({ message: "Please select a date" }),
  time: z.string().min(1, { error: "Please select a time" }),
  duration_minutes: z.number().min(15).max(480),
  service_type: z.string().optional(),
  notes: z.string().optional(),
  agent_id: z.string().optional(),
});

export type AppointmentFormValues = z.infer<typeof appointmentFormSchema>;

export const APPOINTMENT_FORM_DEFAULTS: Partial<AppointmentFormValues> = {
  duration_minutes: 30,
  service_type: "",
  notes: "",
  agent_id: undefined,
};

export interface DurationOption {
  value: number;
  label: string;
}

export const DURATION_OPTIONS: readonly DurationOption[] = [
  { value: 15, label: "15 minutes" },
  { value: 30, label: "30 minutes" },
  { value: 45, label: "45 minutes" },
  { value: 60, label: "1 hour" },
  { value: 90, label: "1.5 hours" },
  { value: 120, label: "2 hours" },
];

/**
 * Generate selectable time slots in `HH:MM` (24h) format.
 *
 * @param startHour first hour to include (inclusive)
 * @param endHour last hour to include (inclusive); the trailing `:30` slot at
 *   `endHour` is omitted so the final slot lands exactly on `endHour:00`
 * @param stepMinutes increment between slots (must divide 60)
 */
export function generateTimeSlots(startHour = 8, endHour = 18, stepMinutes = 30): string[] {
  if (stepMinutes <= 0 || 60 % stepMinutes !== 0) {
    throw new Error("stepMinutes must be a positive divisor of 60");
  }
  if (startHour > endHour) {
    throw new Error("startHour must be <= endHour");
  }

  const slots: string[] = [];
  for (let hour = startHour; hour <= endHour; hour++) {
    for (let minute = 0; minute < 60; minute += stepMinutes) {
      // Stop exactly on the end hour; do not emit slots past `endHour:00`.
      if (hour === endHour && minute > 0) break;
      const h = hour.toString().padStart(2, "0");
      const m = minute.toString().padStart(2, "0");
      slots.push(`${h}:${m}`);
    }
  }
  return slots;
}

/** Format a stored 24-hour slot for operator-facing controls. */
export function formatTimeSlot(time: string): string {
  const match = /^(\d{2}):(\d{2})$/.exec(time);
  if (!match) {
    throw new Error(`Invalid time string: "${time}"`);
  }

  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) {
    throw new Error(`Invalid time string: "${time}"`);
  }

  const period = hours >= 12 ? "PM" : "AM";
  const displayHour = hours % 12 || 12;
  return `${displayHour}:${match[2]} ${period}`;
}

/**
 * Combine a calendar date and an `HH:MM` time string into a local-time ISO
 * datetime string suitable for the appointments API.
 */
export function buildScheduledAtISO(date: Date, time: string): string {
  const parts = time.split(":");
  if (parts.length !== 2) {
    throw new Error(`Invalid time string: "${time}"`);
  }
  const hours = Number(parts[0]);
  const minutes = Number(parts[1]);
  if (
    !Number.isInteger(hours) ||
    !Number.isInteger(minutes) ||
    hours < 0 ||
    hours > 23 ||
    minutes < 0 ||
    minutes > 59
  ) {
    throw new Error(`Invalid time string: "${time}"`);
  }

  const scheduledAt = new Date(date);
  scheduledAt.setHours(hours, minutes, 0, 0);
  return scheduledAt.toISOString();
}

/**
 * Map validated form values plus a resolved numeric contact id into the
 * `CreateAppointmentRequest` payload, normalizing empty strings to `undefined`.
 */
export function buildCreateAppointmentRequest(
  values: AppointmentFormValues,
  contactId: number,
): CreateAppointmentRequest {
  return {
    contact_id: contactId,
    scheduled_at: buildScheduledAtISO(values.date, values.time),
    duration_minutes: values.duration_minutes,
    service_type: values.service_type || undefined,
    notes: values.notes || undefined,
    agent_id: values.agent_id || undefined,
  };
}
