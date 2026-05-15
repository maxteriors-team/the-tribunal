"use client";

import { useState, useMemo, useEffect, Fragment } from "react";
import { useRouter } from "next/navigation";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as z from "zod";

import { agentsApi, type CreateAgentRequest } from "@/lib/api/agents";
import { useWorkspaceId } from "@/hooks/use-workspace-id";
import { queryKeys } from "@/lib/query-keys";
import { getApiErrorMessage } from "@/lib/utils/errors";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  Check,
  Loader2,
  MessageSquare,
  Play,
  Settings,
  Sparkles,
  Wrench,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";

import { PRICING_TIERS } from "@/lib/pricing-tiers";
import { getLanguagesForTier, getFallbackLanguage } from "@/lib/languages";
import { cn } from "@/lib/utils";
import {
  REALTIME_VOICES,
  HUME_VOICES,
  GROK_VOICES,
  ELEVENLABS_VOICES,
} from "@/lib/voice-constants";

import { PricingTierStep } from "./pricing-tier-step";
import { BasicInfoStep } from "./basic-info-step";
import { SystemPromptStep } from "./system-prompt-step";
import { ToolsIntegrationsStep } from "./tools-integrations-step";
import { SettingsReviewStep } from "./settings-review-step";

const WIZARD_STEPS = [
  { id: 1, label: "Pricing", icon: Sparkles },
  { id: 2, label: "Basics", icon: Bot },
  { id: 3, label: "Prompt", icon: MessageSquare },
  { id: 4, label: "Tools", icon: Wrench },
  { id: 5, label: "Settings", icon: Settings },
] as const;

const agentFormSchema = z.object({
  pricingTier: z.enum(["budget", "balanced", "premium-mini", "premium", "hume-evi", "openai-hume", "grok", "elevenlabs"]),
  name: z.string().min(2, { error: "Name must be at least 2 characters" }),
  description: z.string().optional(),
  language: z.string(),
  voice: z.string(),
  channelMode: z.enum(["voice", "text", "both"]),
  systemPrompt: z.string().min(10, { error: "System prompt is required" }),
  initialGreeting: z.string().optional(),
  temperature: z.number().min(0).max(2),
  maxTokens: z.number().min(100).max(16000),
  enabledTools: z.array(z.string()),
  enabledToolIds: z.record(z.string(), z.array(z.string())),
  enableRecording: z.boolean(),
  enableTranscript: z.boolean(),
  // IVR navigation settings (Grok only)
  enableIvrNavigation: z.boolean(),
  ivrNavigationGoal: z.string().optional(),
  ivrLoopThreshold: z.number().min(1).max(10),
  ivrSilenceDurationMs: z.number().min(1000).max(10000),
  ivrPostDtmfCooldownMs: z.number().min(0).max(10000),
  ivrMenuBufferSilenceMs: z.number().min(0).max(10000),
  // Appointment reminder settings
  reminderEnabled: z.boolean(),
  reminderMinutesBefore: z.number().min(5).max(1440),
  // Experiment auto-evaluation
  autoEvaluate: z.boolean(),
});

export type AgentFormValues = z.infer<typeof agentFormSchema>;

export function CreateAgentForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const workspaceId = useWorkspaceId();
  const [step, setStep] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const createAgentMutation = useMutation({
    mutationFn: (data: CreateAgentRequest) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return agentsApi.create(workspaceId, data);
    },
    onSuccess: () => {
      if (workspaceId) {
        queryClient.invalidateQueries({ queryKey: queryKeys.agents.bare(workspaceId) });
      }
      toast.success("Agent created successfully!");
      router.push("/agents");
    },
    onError: (error) => {
      toast.error(getApiErrorMessage(error, "Failed to create agent. Please try again."));
      setIsSubmitting(false);
    },
  });

  const form = useForm<AgentFormValues>({
    resolver: zodResolver(agentFormSchema),
    defaultValues: {
      name: "",
      description: "",
      systemPrompt: "",
      initialGreeting: "",
      pricingTier: "premium",
      language: "en-US",
      voice: "marin",
      channelMode: "both",
      temperature: 0.7,
      maxTokens: 2000,
      enabledTools: [],
      enabledToolIds: {},
      enableRecording: true,
      enableTranscript: true,
      // IVR navigation defaults
      enableIvrNavigation: false,
      ivrNavigationGoal: "",
      ivrLoopThreshold: 2,
      ivrSilenceDurationMs: 3000,
      ivrPostDtmfCooldownMs: 3000,
      ivrMenuBufferSilenceMs: 2000,
      // Appointment reminder defaults
      reminderEnabled: true,
      reminderMinutesBefore: 30,
      // Experiment auto-evaluation
      autoEvaluate: false,
    },
  });

  const pricingTier = useWatch({ control: form.control, name: "pricingTier" });
  const enabledTools = useWatch({ control: form.control, name: "enabledTools" });
  const enabledToolIds = useWatch({ control: form.control, name: "enabledToolIds" });
  const agentName = useWatch({ control: form.control, name: "name" });
  const systemPrompt = useWatch({ control: form.control, name: "systemPrompt" });
  const currentLanguage = useWatch({ control: form.control, name: "language" });

  const selectedTier = useMemo(
    () => PRICING_TIERS.find((t) => t.id === pricingTier),
    [pricingTier]
  );

  const availableLanguages = useMemo(
    () => getLanguagesForTier(pricingTier),
    [pricingTier]
  );

  // Reset language if invalid for new tier
  useEffect(() => {
    const fallback = getFallbackLanguage(currentLanguage, pricingTier);
    if (fallback !== currentLanguage) {
      form.setValue("language", fallback);
    }
  }, [pricingTier, currentLanguage, form]);

  // Set default voice when pricing tier changes
  useEffect(() => {
    const currentVoice = form.getValues("voice");
    let defaultVoice = "marin"; // OpenAI default

    if (pricingTier === "grok") {
      defaultVoice = "ara";
      // Only reset if current voice isn't a valid Grok voice
      const grokVoiceIds = GROK_VOICES.map((v) => v.id);
      if (!grokVoiceIds.includes(currentVoice as typeof grokVoiceIds[number])) {
        form.setValue("voice", defaultVoice);
      }
    } else if (pricingTier === "openai-hume") {
      defaultVoice = "kora";
      const humeVoiceIds = HUME_VOICES.map((v) => v.id);
      if (!humeVoiceIds.includes(currentVoice as typeof humeVoiceIds[number])) {
        form.setValue("voice", defaultVoice);
      }
    } else if (pricingTier === "elevenlabs") {
      defaultVoice = "ava";
      const elevenlabsVoiceIds = ELEVENLABS_VOICES.map((v) => v.id);
      if (!elevenlabsVoiceIds.includes(currentVoice as typeof elevenlabsVoiceIds[number])) {
        form.setValue("voice", defaultVoice);
      }
    } else {
      // OpenAI Realtime
      const realtimeVoiceIds = REALTIME_VOICES.map((v) => v.id);
      if (!realtimeVoiceIds.includes(currentVoice as typeof realtimeVoiceIds[number])) {
        form.setValue("voice", defaultVoice);
      }
    }
  }, [pricingTier, form]);

  const validateStep = async (currentStep: number): Promise<boolean> => {
    switch (currentStep) {
      case 1: {
        const selectedTierId = form.getValues("pricingTier");
        const tier = PRICING_TIERS.find((t) => t.id === selectedTierId);
        return !tier?.underConstruction;
      }
      case 2:
        return form.trigger(["name"]);
      case 3:
        return form.trigger("systemPrompt");
      case 4:
        return true;
      case 5:
        return true;
      default:
        return true;
    }
  };

  const handleNext = async () => {
    const isValid = await validateStep(step);
    if (isValid && step < 5) {
      setStep(step + 1);
    }
  };

  const handleBack = () => {
    if (step > 1) {
      setStep(step - 1);
    } else {
      router.push("/agents");
    }
  };

  const handleSubmit = (data: AgentFormValues) => {
    if (isSubmitting) return;
    setIsSubmitting(true);

    // Determine voice provider based on pricing tier
    const getVoiceProvider = (tier: string): string => {
      switch (tier) {
        case "grok":
          return "grok";
        case "openai-hume":
          return "hume";
        case "elevenlabs":
          return "elevenlabs";
        default:
          return "openai";
      }
    };

    // Map form data to API request format
    const apiRequest: CreateAgentRequest = {
      name: data.name,
      description: data.description || undefined,
      channel_mode: data.channelMode,
      voice_provider: getVoiceProvider(data.pricingTier),
      voice_id: data.voice,
      language: data.language,
      system_prompt: data.systemPrompt,
      temperature: data.temperature,
      enabled_tools: data.enabledTools,
      tool_settings: data.enabledToolIds,
      // Include IVR settings for Grok agents
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

    createAgentMutation.mutate(apiRequest);
  };

  return (
    <div className="min-h-screen">
      <div className="mx-auto max-w-4xl p-6">
        {/* Header */}
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight">Create Voice Agent</h1>
          <p className="text-muted-foreground">
            Step {step} of 5 &middot; {WIZARD_STEPS[step - 1]?.label ?? ""}
          </p>
        </div>

        {/* Progress Bar */}
        <div className="mb-6">
          <div className="grid grid-cols-[1fr_1rem_1fr_1rem_1fr_1rem_1fr_1rem_1fr] items-center">
            {WIZARD_STEPS.map((s, idx) => {
              const Icon = s.icon;
              const isActive = s.id === step;
              const isCompleted = s.id < step;

              return (
                <Fragment key={s.id}>
                  <button
                    type="button"
                    onClick={() => s.id < step && setStep(s.id)}
                    disabled={s.id > step}
                    className={cn(
                      "relative z-10 flex items-center gap-2 rounded-lg border p-2 transition-all duration-300",
                      isActive && "border-primary bg-primary/10 ring-1 ring-primary",
                      isCompleted && "cursor-pointer border-primary bg-primary/5 hover:bg-primary/10",
                      !isActive && !isCompleted && "cursor-not-allowed border-border bg-muted/30"
                    )}
                  >
                    <div
                      className={cn(
                        "flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-medium transition-all",
                        isActive && "bg-primary text-primary-foreground",
                        isCompleted && "bg-primary text-primary-foreground",
                        !isActive && !isCompleted && "bg-muted text-muted-foreground"
                      )}
                    >
                      {isCompleted ? (
                        <Check className="h-3 w-3" />
                      ) : (
                        <Icon className="h-3 w-3" />
                      )}
                    </div>
                    <span
                      className={cn(
                        "hidden text-xs font-medium sm:block",
                        isActive && "text-foreground",
                        isCompleted && "text-foreground",
                        !isActive && !isCompleted && "text-muted-foreground"
                      )}
                    >
                      {s.label}
                    </span>
                  </button>

                  {idx < WIZARD_STEPS.length - 1 && (
                    <div className="relative h-0.5">
                      <div className="absolute inset-0 bg-border" />
                      {isCompleted && (
                        <div className="absolute inset-0 bg-primary" />
                      )}
                    </div>
                  )}
                </Fragment>
              );
            })}
          </div>
        </div>

        {/* Form Content */}
        <Form {...form}>
          <form onSubmit={(e) => e.preventDefault()} className="space-y-6">
            {step === 1 && <PricingTierStep form={form} pricingTier={pricingTier} />}
            {step === 2 && <BasicInfoStep form={form} pricingTier={pricingTier} availableLanguages={availableLanguages} />}
            {step === 3 && <SystemPromptStep form={form} />}
            {step === 4 && <ToolsIntegrationsStep form={form} pricingTier={pricingTier} enabledToolIds={enabledToolIds} />}
            {step === 5 && <SettingsReviewStep form={form} pricingTier={pricingTier} agentName={agentName} systemPrompt={systemPrompt} enabledTools={enabledTools} selectedTier={selectedTier} />}

            {/* Navigation */}
            <div className="flex items-center justify-between border-t pt-6">
              <Button
                type="button"
                variant="outline"
                onClick={handleBack}
              >
                <ArrowLeft className="mr-2 h-4 w-4" />
                {step === 1 ? "Cancel" : "Back"}
              </Button>

              {step < 5 ? (
                <Button type="button" onClick={() => void handleNext()}>
                  Next
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Button>
              ) : (
                <Button
                  type="button"
                  onClick={() => void form.handleSubmit(handleSubmit)()}
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="mr-2 h-4 w-4" />
                  )}
                  {isSubmitting ? "Creating..." : "Create Agent"}
                </Button>
              )}
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}
