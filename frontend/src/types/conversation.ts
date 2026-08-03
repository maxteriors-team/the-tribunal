// Conversation and Message types

import type { Contact } from "./contact";

export type MessageDirection = "inbound" | "outbound";
export type MessageStatus = "queued" | "sending" | "sent" | "delivered" | "failed" | "received";
export type MessageChannel = "sms" | "email" | "imessage" | "voice" | "voicemail" | "note";

export interface Message {
  id: string;
  conversation_id?: string;
  contact_id: number;
  direction: MessageDirection;
  channel: MessageChannel;
  body: string;
  status: MessageStatus;
  from_number?: string;
  to_number?: string;
  is_ai: boolean;
  agent_id?: string;
  // For voice messages
  duration_seconds?: number;
  recording_url?: string;
  transcript?: string;
  // Timestamps
  created_at: string;
  sent_at?: string;
  delivered_at?: string;
}

export interface Conversation {
  id: string;
  user_id: string;
  workspace_id?: string;
  contact_id: number | null;
  contact?: Contact;
  /** Contact's display name; null when the thread isn't linked to a contact yet. */
  contact_name?: string | null;
  workspace_phone: string;
  contact_phone: string;
  channel: string;
  status: "active" | "archived" | "blocked";
  unread_count: number;
  last_message_preview?: string;
  last_message_at?: string;
  last_message_direction?: MessageDirection;
  ai_enabled: boolean;
  ai_paused: boolean;
  assigned_agent_id?: string;
  // Follow-up settings
  followup_enabled?: boolean;
  followup_delay_hours?: number;
  followup_max_count?: number;
  followup_count_sent?: number;
  next_followup_at?: string;
  last_followup_at?: string;
  created_at: string;
  updated_at: string;
}

// Follow-up Types
export interface FollowupSettings {
  enabled: boolean;
  delay_hours: number;
  max_count: number;
  count_sent: number;
  next_followup_at?: string;
  last_followup_at?: string;
}

export interface FollowupGenerateResponse {
  message: string;
  conversation_id: string;
}

export interface FollowupSendResponse {
  success: boolean;
  message_id?: string;
  message_body: string;
}

// Call outcome signals.
// `sentiment`/`sentiment_score` are populated live during the call by the voice
// bridge's streaming sentiment scorer (`sentiment_live: true`), then refined
// post-call by the transcript analysis worker (`analyzed: true`). The remaining
// fields are populated only by the post-call worker.
export interface CallSignals {
  sentiment?: "positive" | "neutral" | "negative";
  sentiment_score?: number;
  // True while sentiment is being scored live during an in-progress call.
  sentiment_live?: boolean;
  // True once sustained negative sentiment triggered an escalation.
  sentiment_escalated?: boolean;
  intents?: string[];
  topics?: string[];
  summary?: string;
  objections?: string[];
  next_steps?: string[];
  analyzed?: boolean | "error";
  [key: string]: unknown;
}

// Unified timeline item for the conversation feed
export type TimelineItemType = "sms" | "call" | "email" | "voicemail" | "appointment" | "note";

export interface TimelineItem {
  id: string;
  type: TimelineItemType;
  timestamp: string;
  direction?: MessageDirection;
  is_ai: boolean;
  // Content varies by type
  content: string;
  // Optional metadata
  duration_seconds?: number;
  recording_url?: string;
  transcript?: string;
  status?: string;
  booking_outcome?: string;
  signals?: CallSignals | null;
  // Reference to original record
  original_id: string;
  original_type: "sms_message" | "call_record" | "appointment" | "note";
}
