// Appointment types

import type { Contact } from "./contact";

export type AppointmentContact = Pick<
  Contact,
  | "id"
  | "first_name"
  | "last_name"
  | "email"
  | "phone_number"
  | "address_line1"
  | "address_line2"
  | "address_city"
  | "address_state"
  | "address_zip"
>;

export interface Appointment {
  id: number;
  contact_id: number;
  contact?: AppointmentContact | null;
  workspace_id?: string;
  agent_id?: string;
  message_id?: string;
  campaign_id?: string;
  scheduled_at: string;
  anytime: boolean;
  duration_minutes: number;
  status: "scheduled" | "completed" | "cancelled" | "no_show";
  service_type?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
  reminder_sent_at?: string;
  reminders_sent?: number[];
  bookable_staff_id?: string | null;
  google_calendar_event_id?: string | null;
  google_calendar_event_url?: string | null;
  meeting_url?: string | null;
  sync_status?: string;
  last_synced_at?: string | null;
  sync_error?: string | null;
}
