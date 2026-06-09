// Agent types

export interface Agent {
  id: string;
  workspace_id: string;
  name: string;
  description: string | null;
  channel_mode: string;
  voice_provider: string;
  voice_id: string;
  language: string;
  system_prompt: string;
  initial_greeting: string | null;
  temperature: number;
  text_response_delay_ms: number;
  text_max_context_messages: number;
  calcom_event_type_id: number | null;
  assignment_strategy: string;
  enabled_tools: string[];
  tool_settings: Record<string, string[]>;
  is_active: boolean;
  // IVR navigation settings
  enable_ivr_navigation: boolean;
  ivr_navigation_goal: string | null;
  ivr_loop_threshold: number;
  ivr_silence_duration_ms: number;
  ivr_post_dtmf_cooldown_ms: number;
  ivr_menu_buffer_silence_ms: number;
  enable_recording: boolean;
  // Live human transfer / handoff
  transfer_destination_number: string | null;
  transfer_mode: string;
  transfer_briefing_template: string | null;
  reminder_enabled: boolean;
  reminder_minutes_before: number;
  reminder_offsets: number[];
  reminder_template: string | null;
  noshow_sms_enabled: boolean;
  // No-show multi-day re-engagement sequence
  noshow_reengagement_enabled: boolean;
  noshow_day3_template: string | null;
  noshow_day7_template: string | null;
  // Never-booked re-engagement
  never_booked_reengagement_enabled: boolean;
  never_booked_delay_days: number;
  never_booked_max_attempts: number;
  never_booked_template: string | null;
  value_reinforcement_enabled: boolean;
  value_reinforcement_offset_minutes: number;
  value_reinforcement_template: string | null;
  // Post-meeting SMS
  post_meeting_sms_enabled: boolean;
  post_meeting_template: string | null;
  auto_evaluate: boolean;
  created_at: string;
  updated_at: string;
}

// Contact-Agent assignment
export interface ContactAgent {
  contact_id: number;
  agent_id: string;
  is_active: boolean;
  assigned_at: string;
}

// Quick Action type
export type QuickActionType =
  | "send_invoice"
  | "create_deal"
  | "schedule_appointment"
  | "add_to_campaign"
  | "send_followup"
  | "mark_vip"
  | "export_contact"
  | "archive_contact";
