import * as z from "zod";

import type { CreateAgentRequest, UpdateAgentRequest } from "@/lib/api/agents";
import {
  TEXT_RESPONSE_DEFAULT_DELAY_MS,
  TEXT_RESPONSE_MAX_DELAY_MS,
  TEXT_RESPONSE_MIN_DELAY_MS,
  clampTextResponseDelayMs,
} from "@/lib/text-response-timing";
import type { Agent } from "@/types/agent";

import { getDefaultVoiceForProvider, getVoiceProviderForTier } from "./agent-voice";

/**
 * Single source of truth for the agent create/edit forms: shared field schema
 * fragments (voice, language, tools, IVR, reminders, auto-evaluation), their
 * defaults, and the mappers that translate form values to API requests and
 * agent records back to form values.
 *
 * The create wizard and the edit screen both compose these fragments so a field
 * is declared, defaulted, and mapped in exactly one place.
 */

export const PRICING_TIER_IDS = [
  "budget",
  "balanced",
  "premium-mini",
  "premium",
  "hume-evi",
  "openai-hume",
  "grok",
  "elevenlabs",
] as const;

export type PricingTierId = (typeof PRICING_TIER_IDS)[number];

// ---------------------------------------------------------------------------
// Shared schema fragments
// ---------------------------------------------------------------------------

/** Voice provider + voice id selection (used by edit; create derives provider). */
export const voiceFields = {
  voiceProvider: z.string(),
  voiceId: z.string(),
} as const;

/** Language selection. */
export const languageField = {
  language: z.string().min(1, { error: "Please select a language" }),
} as const;

/** Tools enablement, shared by create and edit. */
export const toolsFields = {
  enabledTools: z.array(z.string()),
  enabledToolIds: z.record(z.string(), z.array(z.string())),
} as const;

/** Website-form lead qualification gate (edit screen). */
export const qualificationFields = {
  websiteLeadQualificationEnabled: z.boolean(),
  qualificationQuestions: z.string().superRefine((value, context) => {
    const questions = value
      .split("\n")
      .map((question) => question.trim())
      .filter(Boolean);
    if (questions.length > 10 || questions.some((question) => question.length > 200)) {
      context.addIssue({
        code: "custom",
        message: "Use at most 10 questions of 200 characters each",
      });
    }
  }),
  qualificationMinScore: z.number().int().min(0).max(100),
  qualificationBookingLabel: z.string().trim().min(1).max(100),
} as const;

/** IVR navigation settings (Grok only). */
export const ivrFields = {
  enableIvrNavigation: z.boolean(),
  ivrNavigationGoal: z.string().optional(),
  ivrLoopThreshold: z.number().min(1).max(10),
  ivrSilenceDurationMs: z.number().min(1000).max(10000),
  ivrPostDtmfCooldownMs: z.number().min(0).max(10000),
  ivrMenuBufferSilenceMs: z.number().min(0).max(10000),
} as const;

/** Appointment reminder settings shared by both forms. */
export const reminderCoreFields = {
  reminderEnabled: z.boolean(),
  reminderMinutesBefore: z.number().min(5).max(1440),
} as const;

/** Extended reminder settings only available on the edit screen. */
export const reminderExtendedFields = {
  reminderOffsets: z.array(z.number().int().min(1).max(10080)),
  reminderTemplate: z.string().nullable().optional(),
  // Backend rejects anything outside this set, so keep the enum in step.
  reminderChannels: z.array(z.enum(["sms", "email"])),
  confirmationEmailEnabled: z.boolean(),
} as const;

/** Experiment auto-evaluation toggle shared by both forms. */
export const autoEvaluationField = {
  autoEvaluate: z.boolean(),
} as const;

/** Live human transfer / handoff settings (edit screen). */
export const transferFields = {
  transferDestinationNumber: z.string().nullable().optional(),
  transferMode: z.enum(["warm", "cold"]),
  transferBriefingTemplate: z.string().nullable().optional(),
} as const;

// ---------------------------------------------------------------------------
// Shared defaults
// ---------------------------------------------------------------------------

export const IVR_DEFAULTS = {
  enableIvrNavigation: false,
  ivrNavigationGoal: "",
  ivrLoopThreshold: 2,
  ivrSilenceDurationMs: 3000,
  ivrPostDtmfCooldownMs: 3000,
  ivrMenuBufferSilenceMs: 2000,
} as const;

export const REMINDER_CORE_DEFAULTS = {
  reminderEnabled: true,
  reminderMinutesBefore: 30,
} as const;

export const REMINDER_EXTENDED_DEFAULTS = {
  reminderOffsets: [1440, 120, 30] as number[],
  reminderTemplate: null as string | null,
  reminderChannels: ["sms"] as ("sms" | "email")[],
  confirmationEmailEnabled: true,
} as const;

export const TOOLS_DEFAULTS = {
  enabledTools: [] as string[],
  enabledToolIds: {} as Record<string, string[]>,
} as const;

export const QUALIFICATION_DEFAULTS = {
  websiteLeadQualificationEnabled: false,
  qualificationQuestions: "",
  qualificationMinScore: 60,
  qualificationBookingLabel: "Zoom consultation",
} as const;

export const AUTO_EVALUATION_DEFAULT = {
  autoEvaluate: false,
} as const;

export const TRANSFER_DEFAULTS = {
  transferDestinationNumber: null as string | null,
  transferMode: "warm" as "warm" | "cold",
  transferBriefingTemplate: null as string | null,
} as const;

// ---------------------------------------------------------------------------
// Create wizard schema
// ---------------------------------------------------------------------------

export const createAgentFormSchema = z.object({
  pricingTier: z.enum(PRICING_TIER_IDS),
  name: z.string().min(2, { error: "Name must be at least 2 characters" }),
  description: z.string().optional(),
  ...languageField,
  voice: z.string(),
  channelMode: z.enum(["voice", "text", "both"]),
  systemPrompt: z.string().min(10, { error: "System prompt is required" }),
  initialGreeting: z.string().optional(),
  temperature: z.number().min(0).max(2),
  maxTokens: z.number().min(100).max(16000),
  ...toolsFields,
  enableRecording: z.boolean(),
  enableTranscript: z.boolean(),
  ...ivrFields,
  ...reminderCoreFields,
  ...autoEvaluationField,
});

export type CreateAgentFormValues = z.infer<typeof createAgentFormSchema>;

export const CREATE_AGENT_FORM_DEFAULTS: CreateAgentFormValues = {
  pricingTier: "premium",
  name: "",
  description: "",
  language: "en-US",
  voice: "marin",
  channelMode: "both",
  systemPrompt: "",
  initialGreeting: "",
  temperature: 0.7,
  maxTokens: 2000,
  ...TOOLS_DEFAULTS,
  enableRecording: true,
  enableTranscript: true,
  ...IVR_DEFAULTS,
  ...REMINDER_CORE_DEFAULTS,
  ...AUTO_EVALUATION_DEFAULT,
};

// ---------------------------------------------------------------------------
// Edit screen schema
// ---------------------------------------------------------------------------

export const editAgentFormSchema = z.object({
  name: z.string().min(2, { error: "Name must be at least 2 characters" }),
  description: z.string().optional(),
  ...languageField,
  channelMode: z.enum(["voice", "text", "both"]),
  ...voiceFields,
  systemPrompt: z.string().min(10, { error: "System prompt is required" }),
  temperature: z.number().min(0).max(2),
  textResponseDelayMs: z.number().min(TEXT_RESPONSE_MIN_DELAY_MS).max(TEXT_RESPONSE_MAX_DELAY_MS),
  textMaxContextMessages: z.number().min(1).max(50),
  assignmentStrategy: z.enum(["single", "round_robin", "skill_based"]),
  isActive: z.boolean(),
  ...toolsFields,
  ...qualificationFields,
  ...ivrFields,
  ...reminderCoreFields,
  ...reminderExtendedFields,
  // No-show re-engagement
  noshowSmsEnabled: z.boolean(),
  // No-show multi-day re-engagement sequence
  noshowReengagementEnabled: z.boolean(),
  noshowDay3Template: z.string().nullable().optional(),
  noshowDay7Template: z.string().nullable().optional(),
  // Never-booked re-engagement
  neverBookedReengagementEnabled: z.boolean(),
  neverBookedDelayDays: z.number().int().min(1).max(365),
  neverBookedMaxAttempts: z.number().int().min(1).max(10),
  neverBookedTemplate: z.string().nullable().optional(),
  // Value-reinforcement pre-appointment message
  valueReinforcementEnabled: z.boolean(),
  valueReinforcementOffsetMinutes: z.number().int().min(1).max(10080),
  valueReinforcementTemplate: z.string().nullable().optional(),
  // Post-meeting SMS
  postMeetingSmsEnabled: z.boolean(),
  postMeetingTemplate: z.string().nullable().optional(),
  // Live human transfer / handoff
  ...transferFields,
  ...autoEvaluationField,
});

export type EditAgentFormValues = z.infer<typeof editAgentFormSchema>;

export const EDIT_AGENT_FORM_DEFAULTS: EditAgentFormValues = {
  name: "",
  description: "",
  language: "en-US",
  channelMode: "voice",
  voiceProvider: "openai",
  voiceId: "marin",
  systemPrompt: "",
  temperature: 0.7,
  textResponseDelayMs: TEXT_RESPONSE_DEFAULT_DELAY_MS,
  textMaxContextMessages: 10,
  assignmentStrategy: "single",
  isActive: true,
  ...TOOLS_DEFAULTS,
  ...QUALIFICATION_DEFAULTS,
  ...IVR_DEFAULTS,
  ...REMINDER_CORE_DEFAULTS,
  ...REMINDER_EXTENDED_DEFAULTS,
  reminderChannels: [...REMINDER_EXTENDED_DEFAULTS.reminderChannels],
  noshowSmsEnabled: false,
  noshowReengagementEnabled: true,
  noshowDay3Template: null,
  noshowDay7Template: null,
  neverBookedReengagementEnabled: false,
  neverBookedDelayDays: 7,
  neverBookedMaxAttempts: 2,
  neverBookedTemplate: null,
  valueReinforcementEnabled: false,
  valueReinforcementOffsetMinutes: 120,
  valueReinforcementTemplate: null,
  postMeetingSmsEnabled: false,
  postMeetingTemplate: null,
  ...TRANSFER_DEFAULTS,
  ...AUTO_EVALUATION_DEFAULT,
};

// Map fields to their respective tabs for error tracking on the edit screen.
export const TAB_FIELDS: Record<string, (keyof EditAgentFormValues)[]> = {
  basic: ["name", "description", "language", "channelMode", "isActive"],
  voice: ["voiceProvider", "voiceId"],
  prompt: [
    "systemPrompt",
    "temperature",
    "websiteLeadQualificationEnabled",
    "qualificationQuestions",
    "qualificationMinScore",
    "qualificationBookingLabel",
  ],
  tools: ["enabledTools", "enabledToolIds"],
  advanced: [
    "textResponseDelayMs",
    "textMaxContextMessages",
    "assignmentStrategy",
    "reminderEnabled",
    "reminderMinutesBefore",
    "reminderOffsets",
    "reminderTemplate",
    "reminderChannels",
    "confirmationEmailEnabled",
    "noshowSmsEnabled",
    "noshowReengagementEnabled",
    "noshowDay3Template",
    "noshowDay7Template",
    "neverBookedReengagementEnabled",
    "neverBookedDelayDays",
    "neverBookedMaxAttempts",
    "neverBookedTemplate",
    "valueReinforcementEnabled",
    "valueReinforcementOffsetMinutes",
    "valueReinforcementTemplate",
    "postMeetingSmsEnabled",
    "postMeetingTemplate",
    "transferDestinationNumber",
    "transferMode",
    "transferBriefingTemplate",
    "autoEvaluate",
  ],
};

// ---------------------------------------------------------------------------
// Mappers
// ---------------------------------------------------------------------------

/** Map create-wizard form values to the API create request. */
export function buildCreateAgentRequest(data: CreateAgentFormValues): CreateAgentRequest {
  return {
    name: data.name,
    description: data.description || undefined,
    channel_mode: data.channelMode,
    voice_provider: getVoiceProviderForTier(data.pricingTier),
    voice_id: data.voice,
    language: data.language,
    system_prompt: data.systemPrompt,
    temperature: data.temperature,
    text_response_delay_ms: TEXT_RESPONSE_DEFAULT_DELAY_MS,
    enabled_tools: data.enabledTools,
    tool_settings: data.enabledToolIds,
    enable_ivr_navigation: data.enableIvrNavigation,
    ivr_navigation_goal: data.ivrNavigationGoal || undefined,
    ivr_loop_threshold: data.ivrLoopThreshold,
    ivr_silence_duration_ms: data.ivrSilenceDurationMs,
    ivr_post_dtmf_cooldown_ms: data.ivrPostDtmfCooldownMs,
    ivr_menu_buffer_silence_ms: data.ivrMenuBufferSilenceMs,
    enable_recording: data.enableRecording,
    reminder_enabled: data.reminderEnabled,
    reminder_minutes_before: data.reminderMinutesBefore,
    auto_evaluate: data.autoEvaluate,
  };
}

function qualificationQuestionsFromText(value: string): string[] {
  return value
    .split("\n")
    .map((question) => question.trim())
    .filter(Boolean);
}

function buildToolSettings(data: EditAgentFormValues): Record<string, unknown> {
  return {
    ...data.enabledToolIds,
    website_lead_qualification_enabled: data.websiteLeadQualificationEnabled,
    qualification_questions: qualificationQuestionsFromText(data.qualificationQuestions),
    qualification_min_score: data.qualificationMinScore,
    qualification_booking_label: data.qualificationBookingLabel.trim(),
  };
}

const QUALIFICATION_SETTING_KEYS = new Set([
  "website_lead_qualification_enabled",
  "qualification_questions",
  "qualification_min_score",
  "qualification_booking_label",
]);

function toolIdSettingsFromAgent(agent: Agent): Record<string, string[]> {
  return Object.fromEntries(
    Object.entries(agent.tool_settings ?? {}).filter(
      (entry): entry is [string, string[]] =>
        !QUALIFICATION_SETTING_KEYS.has(entry[0]) &&
        Array.isArray(entry[1]) &&
        entry[1].every((value) => typeof value === "string"),
    ),
  );
}

function qualificationSetting<T>(agent: Agent, key: string, fallback: T): T {
  const value = agent.tool_settings?.[key];
  return (typeof value === typeof fallback ? value : fallback) as T;
}

/** Map edit-screen form values to the API update request. */
export function buildUpdateAgentRequest(data: EditAgentFormValues): UpdateAgentRequest {
  return {
    name: data.name,
    description: data.description || undefined,
    language: data.language,
    channel_mode: data.channelMode,
    voice_provider: data.voiceProvider,
    voice_id: data.voiceId,
    system_prompt: data.systemPrompt,
    temperature: data.temperature,
    text_response_delay_ms: clampTextResponseDelayMs(data.textResponseDelayMs),
    text_max_context_messages: data.textMaxContextMessages,
    assignment_strategy: data.assignmentStrategy,
    is_active: data.isActive,
    enabled_tools: data.enabledTools,
    tool_settings: buildToolSettings(data),
    enable_ivr_navigation: data.enableIvrNavigation,
    ivr_navigation_goal: data.ivrNavigationGoal || undefined,
    ivr_loop_threshold: data.ivrLoopThreshold,
    ivr_silence_duration_ms: data.ivrSilenceDurationMs,
    ivr_post_dtmf_cooldown_ms: data.ivrPostDtmfCooldownMs,
    ivr_menu_buffer_silence_ms: data.ivrMenuBufferSilenceMs,
    reminder_enabled: data.reminderEnabled,
    reminder_minutes_before: data.reminderMinutesBefore,
    reminder_offsets: data.reminderOffsets,
    reminder_template: data.reminderTemplate ?? null,
    reminder_channels: data.reminderChannels,
    confirmation_email_enabled: data.confirmationEmailEnabled,
    noshow_sms_enabled: data.noshowSmsEnabled,
    noshow_reengagement_enabled: data.noshowReengagementEnabled,
    noshow_day3_template: data.noshowDay3Template ?? null,
    noshow_day7_template: data.noshowDay7Template ?? null,
    never_booked_reengagement_enabled: data.neverBookedReengagementEnabled,
    never_booked_delay_days: data.neverBookedDelayDays,
    never_booked_max_attempts: data.neverBookedMaxAttempts,
    never_booked_template: data.neverBookedTemplate ?? null,
    value_reinforcement_enabled: data.valueReinforcementEnabled,
    value_reinforcement_offset_minutes: data.valueReinforcementOffsetMinutes,
    value_reinforcement_template: data.valueReinforcementTemplate ?? null,
    post_meeting_sms_enabled: data.postMeetingSmsEnabled,
    post_meeting_template: data.postMeetingTemplate ?? null,
    transfer_destination_number: data.transferDestinationNumber?.trim() || null,
    transfer_mode: data.transferMode,
    transfer_briefing_template: data.transferBriefingTemplate?.trim() || null,
    auto_evaluate: data.autoEvaluate,
  };
}

export type AssignmentStrategy = "single" | "round_robin" | "skill_based";

const ASSIGNMENT_STRATEGIES: readonly AssignmentStrategy[] = [
  "single",
  "round_robin",
  "skill_based",
];

/** Coerce a (possibly empty/unknown) strategy string to a valid value. */
function normalizeAssignmentStrategy(value: string | null | undefined): AssignmentStrategy {
  return ASSIGNMENT_STRATEGIES.includes(value as AssignmentStrategy)
    ? (value as AssignmentStrategy)
    : "single";
}

/** Map a loaded agent record into edit-screen form values. */
export function agentToEditFormValues(agent: Agent): EditAgentFormValues {
  return {
    name: agent.name,
    description: agent.description ?? "",
    language: agent.language,
    channelMode: (agent.channel_mode as "voice" | "text" | "both") ?? "voice",
    voiceProvider: agent.voice_provider ?? "openai",
    voiceId: agent.voice_id || getDefaultVoiceForProvider(agent.voice_provider ?? "openai"),
    systemPrompt: agent.system_prompt,
    temperature: agent.temperature ?? 0.7,
    textResponseDelayMs: clampTextResponseDelayMs(agent.text_response_delay_ms),
    textMaxContextMessages: agent.text_max_context_messages ?? 10,
    assignmentStrategy: normalizeAssignmentStrategy(agent.assignment_strategy),
    isActive: agent.is_active,
    enabledTools: agent.enabled_tools ?? [],
    enabledToolIds: toolIdSettingsFromAgent(agent),
    websiteLeadQualificationEnabled: qualificationSetting(
      agent,
      "website_lead_qualification_enabled",
      QUALIFICATION_DEFAULTS.websiteLeadQualificationEnabled,
    ),
    qualificationQuestions: Array.isArray(agent.tool_settings?.qualification_questions)
      ? agent.tool_settings.qualification_questions
          .filter((value): value is string => typeof value === "string")
          .join("\n")
      : QUALIFICATION_DEFAULTS.qualificationQuestions,
    qualificationMinScore: qualificationSetting(
      agent,
      "qualification_min_score",
      QUALIFICATION_DEFAULTS.qualificationMinScore,
    ),
    qualificationBookingLabel: qualificationSetting(
      agent,
      "qualification_booking_label",
      QUALIFICATION_DEFAULTS.qualificationBookingLabel,
    ),
    enableIvrNavigation: agent.enable_ivr_navigation ?? IVR_DEFAULTS.enableIvrNavigation,
    ivrNavigationGoal: agent.ivr_navigation_goal ?? IVR_DEFAULTS.ivrNavigationGoal,
    ivrLoopThreshold: agent.ivr_loop_threshold ?? IVR_DEFAULTS.ivrLoopThreshold,
    ivrSilenceDurationMs: agent.ivr_silence_duration_ms ?? IVR_DEFAULTS.ivrSilenceDurationMs,
    ivrPostDtmfCooldownMs: agent.ivr_post_dtmf_cooldown_ms ?? IVR_DEFAULTS.ivrPostDtmfCooldownMs,
    ivrMenuBufferSilenceMs: agent.ivr_menu_buffer_silence_ms ?? IVR_DEFAULTS.ivrMenuBufferSilenceMs,
    reminderEnabled: agent.reminder_enabled ?? REMINDER_CORE_DEFAULTS.reminderEnabled,
    reminderMinutesBefore:
      agent.reminder_minutes_before ?? REMINDER_CORE_DEFAULTS.reminderMinutesBefore,
    reminderOffsets: agent.reminder_offsets ?? [...REMINDER_EXTENDED_DEFAULTS.reminderOffsets],
    reminderTemplate: agent.reminder_template ?? null,
    reminderChannels: (agent.reminder_channels as ("sms" | "email")[] | undefined) ?? [
      ...REMINDER_EXTENDED_DEFAULTS.reminderChannels,
    ],
    confirmationEmailEnabled: agent.confirmation_email_enabled ?? true,
    noshowSmsEnabled: agent.noshow_sms_enabled ?? false,
    noshowReengagementEnabled: agent.noshow_reengagement_enabled ?? true,
    noshowDay3Template: agent.noshow_day3_template ?? null,
    noshowDay7Template: agent.noshow_day7_template ?? null,
    neverBookedReengagementEnabled: agent.never_booked_reengagement_enabled ?? false,
    neverBookedDelayDays: agent.never_booked_delay_days ?? 7,
    neverBookedMaxAttempts: agent.never_booked_max_attempts ?? 2,
    neverBookedTemplate: agent.never_booked_template ?? null,
    valueReinforcementEnabled: agent.value_reinforcement_enabled ?? false,
    valueReinforcementOffsetMinutes: agent.value_reinforcement_offset_minutes ?? 120,
    valueReinforcementTemplate: agent.value_reinforcement_template ?? null,
    postMeetingSmsEnabled: agent.post_meeting_sms_enabled ?? false,
    postMeetingTemplate: agent.post_meeting_template ?? null,
    transferDestinationNumber:
      agent.transfer_destination_number ?? TRANSFER_DEFAULTS.transferDestinationNumber,
    transferMode: (agent.transfer_mode as "warm" | "cold") ?? TRANSFER_DEFAULTS.transferMode,
    transferBriefingTemplate:
      agent.transfer_briefing_template ?? TRANSFER_DEFAULTS.transferBriefingTemplate,
    autoEvaluate: agent.auto_evaluate ?? AUTO_EVALUATION_DEFAULT.autoEvaluate,
  };
}
