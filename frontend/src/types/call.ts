// Call record types

export interface CapturedMessage {
  id: string;
  caller_name?: string | null;
  callback_number?: string | null;
  reason?: string | null;
  urgency: "low" | "medium" | "high" | string;
  preferred_callback_time?: string | null;
  message_body?: string | null;
  status: string;
  created_at: string;
}

export interface CallRecord {
  id: string;
  conversation_id: string;
  direction: "inbound" | "outbound";
  channel: string;
  status: "initiated" | "ringing" | "in_progress" | "completed" | "failed" | "busy" | "no_answer";
  from_number?: string;
  to_number?: string;
  contact_name?: string;
  contact_id?: number;
  contact_avatar_url?: string | null;
  duration_seconds?: number;
  recording_url?: string;
  transcript?: string;
  agent_id?: string;
  agent_name?: string;
  is_ai?: boolean;
  booking_outcome?: string;
  captured_messages?: CapturedMessage[];
  created_at: string;
  // Optional fields for active calls
  started_at?: string;
  answered_at?: string;
  ended_at?: string;
}
