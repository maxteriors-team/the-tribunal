// Appointment types

import type { Contact } from "./contact";

export interface Appointment {
  id: number;
  contact_id: number;
  contact?: Contact;
  workspace_id?: string;
  agent_id?: string;
  message_id?: string;
  campaign_id?: string;
  scheduled_at: string;
  duration_minutes: number;
  status: "scheduled" | "completed" | "cancelled" | "no_show";
  service_type?: string;
  notes?: string;
  created_at: string;
  updated_at: string;
  reminder_sent_at?: string;
  reminders_sent?: number[];
}
