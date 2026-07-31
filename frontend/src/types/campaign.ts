// Campaign Types

import type { CallRecord } from "./call";
import type { Contact } from "./contact";
import type { MessageStatus } from "./conversation";
import type { CampaignPreBookingSummary } from "./pre-booking";

export type CampaignStatus = "draft" | "scheduled" | "running" | "paused" | "completed" | "cancelled";
export type CampaignType = "sms" | "email" | "voice" | "voice_sms_fallback" | "multi_channel";

export interface Campaign {
  id: string;
  workspace_id?: string;
  campaign_type: CampaignType;
  name: string;
  description?: string;
  status: CampaignStatus;
  from_phone_number: string;
  initial_message?: string;
  agent_id?: string;
  // Scheduling
  scheduled_start?: string;
  scheduled_end?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone: string;
  // Rate limiting
  messages_per_minute: number;
  follow_up_enabled: boolean;
  follow_up_delay_hours: number;
  follow_up_message?: string;
  max_follow_ups: number;
  ai_enabled: boolean;
  qualification_criteria?: string;
  // Stats
  total_contacts: number;
  messages_sent: number;
  messages_delivered: number;
  messages_failed: number;
  replies_received: number;
  contacts_qualified: number;
  contacts_opted_out: number;
  appointments_booked: number;
  appointments_completed: number;
  links_clicked?: number;
  guarantee_target?: number;
  guarantee_window_days?: number;
  guarantee_status?: "pending" | "met" | "missed" | null;
  // Pre-booking offer, when one is attached. A pre-booking campaign is still an
  // ordinary `sms` campaign, so this field — not `campaign_type` — is what marks
  // it as one.
  pre_booking?: CampaignPreBookingSummary | null;
  // Timestamps
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

export type CampaignContactStatus =
  | "pending"
  | "queued"
  | "sending"
  | "sent"
  | "delivered"
  | "failed"
  | "responded"
  | "opted_out"
  | "skipped";

export interface CampaignContact {
  id: string;
  campaign_id: string;
  contact_id: number;
  contact?: Contact;
  status: CampaignContactStatus;
  // Channel-specific delivery
  sms_status?: MessageStatus;
  email_status?: MessageStatus;
  call_status?: CallRecord["status"];
  // Tracking
  message_id?: string;
  call_id?: string;
  sent_at?: string;
  delivered_at?: string;
  responded_at?: string;
  failed_at?: string;
  failure_reason?: string;
  retry_count: number;
  next_retry_at?: string;
  // Personalization data
  personalization_data?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// Campaign Worker Job Types
export type CampaignJobType = "send_message" | "make_call" | "retry_failed" | "process_batch";

export interface CampaignJob {
  id: string;
  campaign_id: string;
  campaign_contact_id: string;
  job_type: CampaignJobType;
  status: "pending" | "processing" | "completed" | "failed";
  attempts: number;
  max_attempts: number;
  scheduled_at: string;
  started_at?: string;
  completed_at?: string;
  error_message?: string;
  created_at: string;
}

// Voice Campaign Types
export type VoiceCampaignContactStatus =
  | "pending"
  | "calling"
  | "call_answered"
  | "call_failed"
  | "sms_fallback_sent"
  | "responded"
  | "qualified"
  | "opted_out";

export interface VoiceCampaign {
  id: string;
  workspace_id: string;
  campaign_type: "voice_sms_fallback";
  name: string;
  description?: string;
  status: CampaignStatus;
  from_phone_number: string;

  // Voice settings
  voice_agent_id?: string;
  voice_connection_id?: string;
  enable_machine_detection: boolean;
  max_call_duration_seconds: number;
  calls_per_minute: number;

  // SMS fallback settings
  sms_fallback_enabled: boolean;
  sms_fallback_template?: string;
  sms_fallback_use_ai: boolean;
  sms_fallback_agent_id?: string;

  // AI settings (for responses to SMS replies)
  ai_enabled: boolean;
  agent_id?: string;
  qualification_criteria?: string;

  // Scheduling
  scheduled_start?: string;
  scheduled_end?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone: string;

  // Statistics
  total_contacts: number;
  calls_attempted: number;
  calls_answered: number;
  calls_no_answer: number;
  calls_busy: number;
  calls_voicemail: number;
  sms_fallbacks_sent: number;
  messages_sent: number;
  replies_received: number;
  contacts_qualified: number;
  contacts_opted_out: number;
  appointments_booked: number;
  appointments_completed: number;
  guarantee_target?: number;
  guarantee_window_days?: number;
  guarantee_status?: "pending" | "met" | "missed" | null;

  // Timestamps
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}

export interface VoiceCampaignContact {
  id: string;
  campaign_id: string;
  contact_id: number;
  contact?: Contact;
  conversation_id?: string;
  status: VoiceCampaignContactStatus;

  // Call tracking
  call_attempts: number;
  last_call_at?: string;
  last_call_status?: string;
  call_duration_seconds?: number;

  // SMS fallback tracking
  sms_fallback_sent: boolean;
  sms_fallback_sent_at?: string;

  // Standard fields
  messages_sent: number;
  is_qualified: boolean;
  opted_out: boolean;
  created_at: string;
}

export interface VoiceCampaignAnalytics {
  total_contacts: number;
  calls_attempted: number;
  calls_answered: number;
  calls_no_answer: number;
  calls_busy: number;
  calls_voicemail: number;
  sms_fallbacks_sent: number;
  messages_sent: number;
  replies_received: number;
  contacts_qualified: number;
  contacts_opted_out: number;
  appointments_booked: number;
  // Rates
  answer_rate: number;
  fallback_rate: number;
  qualification_rate: number;
}

export interface GuaranteeProgress {
  campaign_id: string;
  guarantee_target: number | null;
  appointments_booked: number;
  appointments_completed: number;
  guarantee_status: "pending" | "met" | "missed" | null;
  guarantee_window_days: number | null;
  days_remaining: number | null;
  deadline: string | null;
  started_at: string | null;
}

// SMS Campaign Types
export interface SMSCampaign {
  id: string;
  workspace_id: string;
  agent_id?: string;
  offer_id?: string;
  name: string;
  description?: string;
  status: CampaignStatus;
  from_phone_number: string;
  initial_message: string;
  ai_enabled: boolean;
  qualification_criteria?: string;
  // Scheduling
  scheduled_start?: string;
  scheduled_end?: string;
  sending_hours_start?: string;
  sending_hours_end?: string;
  sending_days?: number[];
  timezone: string;
  // Rate limiting
  messages_per_minute: number;
  max_messages_per_contact: number;
  // Follow-ups
  follow_up_enabled: boolean;
  follow_up_delay_hours: number;
  follow_up_message?: string;
  max_follow_ups: number;
  // Stats
  total_contacts: number;
  messages_sent: number;
  messages_delivered: number;
  messages_failed: number;
  replies_received: number;
  contacts_qualified: number;
  contacts_opted_out: number;
  appointments_booked: number;
  // Timestamps
  started_at?: string;
  completed_at?: string;
  created_at: string;
  updated_at: string;
}


