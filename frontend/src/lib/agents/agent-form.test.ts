import { describe, expect, it } from "vitest";

import { TEXT_RESPONSE_DEFAULT_DELAY_MS } from "@/lib/text-response-timing";
import type { Agent } from "@/types/agent";

import {
  agentToEditFormValues,
  buildCreateAgentRequest,
  buildUpdateAgentRequest,
  createAgentFormSchema,
  CREATE_AGENT_FORM_DEFAULTS,
  editAgentFormSchema,
  EDIT_AGENT_FORM_DEFAULTS,
  TAB_FIELDS,
} from "./agent-form";
import {
  getDefaultVoiceForProvider,
  getVoiceProviderForTier,
  getVoicesForProvider,
  resolveVoiceForProvider,
} from "./agent-voice";

function makeAgent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "a1",
    workspace_id: "w1",
    name: "Test Agent",
    description: "desc",
    channel_mode: "both",
    voice_provider: "grok",
    voice_id: "rex",
    language: "en-US",
    system_prompt: "You are a helpful assistant.",
    initial_greeting: null,
    temperature: 0.5,
    text_response_delay_ms: 40_000,
    text_max_context_messages: 12,
    calcom_event_type_id: 42,
    enabled_tools: ["calendar"],
    tool_settings: { calendar: ["book"] },
    is_active: false,
    enable_ivr_navigation: true,
    ivr_navigation_goal: "reach support",
    ivr_loop_threshold: 3,
    ivr_silence_duration_ms: 4000,
    ivr_post_dtmf_cooldown_ms: 1500,
    ivr_menu_buffer_silence_ms: 1000,
    enable_recording: true,
    reminder_enabled: false,
    reminder_minutes_before: 60,
    reminder_offsets: [2880, 60],
    reminder_template: "Reminder!",
    noshow_sms_enabled: true,
    noshow_reengagement_enabled: false,
    noshow_day3_template: "d3",
    noshow_day7_template: "d7",
    never_booked_reengagement_enabled: true,
    never_booked_delay_days: 5,
    never_booked_max_attempts: 4,
    never_booked_template: "nb",
    value_reinforcement_enabled: true,
    value_reinforcement_offset_minutes: 90,
    value_reinforcement_template: "vr",
    post_meeting_sms_enabled: true,
    post_meeting_template: "pm",
    auto_evaluate: true,
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-02T00:00:00Z",
    ...overrides,
  };
}

describe("agent-voice helpers", () => {
  it("maps pricing tiers to providers", () => {
    expect(getVoiceProviderForTier("grok")).toBe("grok");
    expect(getVoiceProviderForTier("openai-hume")).toBe("hume");
    expect(getVoiceProviderForTier("elevenlabs")).toBe("elevenlabs");
    expect(getVoiceProviderForTier("premium")).toBe("openai");
    expect(getVoiceProviderForTier("unknown-tier")).toBe("openai");
  });

  it("returns provider default voices", () => {
    expect(getDefaultVoiceForProvider("grok")).toBe("ara");
    expect(getDefaultVoiceForProvider("hume")).toBe("kora");
    expect(getDefaultVoiceForProvider("elevenlabs")).toBe("ava");
    expect(getDefaultVoiceForProvider("openai")).toBe("marin");
    expect(getDefaultVoiceForProvider("mystery")).toBe("marin");
  });

  it("keeps valid voices and falls back otherwise", () => {
    const grokVoice = getVoicesForProvider("grok")[0]!.id;
    expect(resolveVoiceForProvider("grok", grokVoice)).toBe(grokVoice);
    expect(resolveVoiceForProvider("grok", "marin")).toBe("ara");
    expect(resolveVoiceForProvider("openai", "ara")).toBe("marin");
  });
});

describe("createAgentFormSchema + defaults", () => {
  it("accepts the defaults once name and prompt are filled", () => {
    const result = createAgentFormSchema.safeParse({
      ...CREATE_AGENT_FORM_DEFAULTS,
      name: "Sales Bot",
      systemPrompt: "You are a helpful assistant.",
    });
    expect(result.success).toBe(true);
  });

  it("rejects short names and prompts", () => {
    expect(
      createAgentFormSchema.safeParse({ ...CREATE_AGENT_FORM_DEFAULTS, name: "a" }).success,
    ).toBe(false);
    expect(
      createAgentFormSchema.safeParse({ ...CREATE_AGENT_FORM_DEFAULTS, systemPrompt: "short" })
        .success,
    ).toBe(false);
  });
});

describe("buildCreateAgentRequest", () => {
  it("derives voice provider from the pricing tier and maps fields", () => {
    const req = buildCreateAgentRequest({
      ...CREATE_AGENT_FORM_DEFAULTS,
      pricingTier: "grok",
      name: "Sales Bot",
      description: "",
      voice: "rex",
      systemPrompt: "You are a closer.",
      enabledTools: ["calendar"],
      enabledToolIds: { calendar: ["book"] },
      enableIvrNavigation: true,
      ivrNavigationGoal: "reach a human",
      autoEvaluate: true,
    });

    expect(req.voice_provider).toBe("grok");
    expect(req.voice_id).toBe("rex");
    expect(req.description).toBeUndefined();
    expect(req.text_response_delay_ms).toBe(TEXT_RESPONSE_DEFAULT_DELAY_MS);
    expect(req.enabled_tools).toEqual(["calendar"]);
    expect(req.tool_settings).toEqual({ calendar: ["book"] });
    expect(req.enable_ivr_navigation).toBe(true);
    expect(req.ivr_navigation_goal).toBe("reach a human");
    expect(req.auto_evaluate).toBe(true);
  });

  it("omits empty ivr goal", () => {
    const req = buildCreateAgentRequest({
      ...CREATE_AGENT_FORM_DEFAULTS,
      ivrNavigationGoal: "",
    });
    expect(req.ivr_navigation_goal).toBeUndefined();
  });
});

describe("editAgentFormSchema + defaults", () => {
  it("accepts the defaults once name and prompt are filled", () => {
    const result = editAgentFormSchema.safeParse({
      ...EDIT_AGENT_FORM_DEFAULTS,
      name: "Sales Bot",
      systemPrompt: "You are a helpful assistant.",
    });
    expect(result.success).toBe(true);
  });

  it("covers every advanced field in TAB_FIELDS", () => {
    expect(TAB_FIELDS.advanced).toContain("autoEvaluate");
    expect(TAB_FIELDS.advanced).toContain("reminderOffsets");
    expect(TAB_FIELDS.voice).toEqual(["voiceProvider", "voiceId"]);
  });
});

describe("agentToEditFormValues round-trips through buildUpdateAgentRequest", () => {
  it("maps agent record to form values", () => {
    const values = agentToEditFormValues(makeAgent());
    expect(values.name).toBe("Test Agent");
    expect(values.voiceProvider).toBe("grok");
    expect(values.voiceId).toBe("rex");
    expect(values.isActive).toBe(false);
    expect(values.reminderOffsets).toEqual([2880, 60]);
    expect(values.autoEvaluate).toBe(true);
    expect(editAgentFormSchema.safeParse(values).success).toBe(true);
  });

  it("falls back to provider default voice when missing", () => {
    const values = agentToEditFormValues(
      makeAgent({ voice_id: "", voice_provider: "hume" }),
    );
    expect(values.voiceId).toBe("kora");
  });

  it("produces an update request matching the source agent", () => {
    const agent = makeAgent();
    const req = buildUpdateAgentRequest(agentToEditFormValues(agent));
    expect(req.name).toBe(agent.name);
    expect(req.voice_provider).toBe(agent.voice_provider);
    expect(req.voice_id).toBe(agent.voice_id);
    expect(req.reminder_offsets).toEqual(agent.reminder_offsets);
    expect(req.never_booked_max_attempts).toBe(agent.never_booked_max_attempts);
    expect(req.value_reinforcement_template).toBe(agent.value_reinforcement_template);
    expect(req.post_meeting_template).toBe(agent.post_meeting_template);
    expect(req.auto_evaluate).toBe(agent.auto_evaluate);
    expect(req.calcom_event_type_id).toBe(agent.calcom_event_type_id);
  });

  it("normalizes empty description to undefined in update request", () => {
    const req = buildUpdateAgentRequest(
      agentToEditFormValues(makeAgent({ description: null })),
    );
    expect(req.description).toBeUndefined();
  });

  it("applies defaults for null optional fields coming from the API", () => {
    const values = agentToEditFormValues(
      makeAgent({
        description: null,
        ivr_navigation_goal: null,
        calcom_event_type_id: null,
        reminder_template: null,
        noshow_day3_template: null,
        noshow_day7_template: null,
        never_booked_template: null,
        value_reinforcement_template: null,
        post_meeting_template: null,
      }),
    );

    // Nullable string goal collapses to the IVR default (empty string).
    expect(values.ivrNavigationGoal).toBe("");
    // Empty description becomes a blank string the form can render.
    expect(values.description).toBe("");
    // Nullable id and templates pass through as null.
    expect(values.calcomEventTypeId).toBeNull();
    expect(values.reminderTemplate).toBeNull();
    expect(values.noshowDay3Template).toBeNull();
    expect(values.postMeetingTemplate).toBeNull();
    // Result still satisfies the edit schema.
    expect(editAgentFormSchema.safeParse(values).success).toBe(true);
  });
});
