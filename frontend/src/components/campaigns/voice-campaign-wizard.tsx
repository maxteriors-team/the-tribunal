"use client";

import { MessageSquare, Phone } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { CreateVoiceCampaignRequest } from "@/lib/api/voice-campaigns";
import type { Agent, PhoneNumber, VoiceCampaign } from "@/types";

import {
  type BasicsFields,
  type ScheduleFields,
  initialBasicsFields,
  initialScheduleFields,
  makeBasicsStep,
  makeContactsStep,
  makeReviewStep,
  makeScheduleStep,
  mapScheduleToRequest,
} from "./_shared";
import { BaseCampaignWizard } from "./base-campaign-wizard";
import {
  type SMSFallbackStepFields,
  type VoiceAgentStepFields,
  makeFallbackStep,
  makeVoiceAgentStep,
} from "./voice-steps";
import type { WizardStep } from "./wizard-types";

type StepId = "basics" | "contacts" | "voice" | "fallback" | "schedule" | "review";

interface VoiceCampaignWizardProps {
  workspaceId: string;
  voiceAgents: Agent[];
  textAgents: Agent[];
  phoneNumbers: PhoneNumber[];
  onSubmit: (data: CreateVoiceCampaignRequest, contactIds: Set<number>) => Promise<VoiceCampaign>;
  onCancel?: () => void;
  isSubmitting?: boolean;
}

interface VoiceFormData
  extends BasicsFields, ScheduleFields, VoiceAgentStepFields, SMSFallbackStepFields {
  ai_enabled: boolean;
  qualification_criteria: string;
  calls_per_minute: number;
}

const initialFormData: VoiceFormData = {
  ...initialBasicsFields,
  ...initialScheduleFields,
  sending_hours_enabled: true,
  voice_agent_id: undefined,
  enable_machine_detection: true,
  max_call_duration_seconds: 120,
  sms_fallback_enabled: true,
  sms_fallback_mode: "template",
  sms_fallback_template:
    "Hi {first_name}, {call_reason} - reply to this message or call us back at your convenience.",
  sms_fallback_agent_id: undefined,
  ai_enabled: true,
  qualification_criteria: "",
  calls_per_minute: 5,
};

export function VoiceCampaignWizard({
  workspaceId,
  voiceAgents,
  textAgents,
  phoneNumbers,
  onSubmit,
  onCancel,
  isSubmitting = false,
}: VoiceCampaignWizardProps) {
  const [selectedContactIds, setSelectedContactIds] = useState<Set<number>>(new Set());

  const steps = useMemo<ReadonlyArray<WizardStep<StepId, VoiceFormData>>>(
    () => [
      makeBasicsStep<StepId, VoiceFormData>({
        id: "basics",
        phoneNumbers,
        namePlaceholder: "e.g., Follow-up Calls - January",
        emptyPhoneLabel: "No voice-enabled phone numbers available",
      }),
      makeContactsStep<StepId, VoiceFormData>({
        id: "contacts",
        workspaceId,
        selectedContactIds,
        setSelectedContactIds,
      }),
      makeVoiceAgentStep<StepId, VoiceFormData>({
        id: "voice",
        voiceAgents,
      }),
      makeFallbackStep<StepId, VoiceFormData>({
        id: "fallback",
        textAgents,
      }),
      makeScheduleStep<StepId, VoiceFormData>({
        id: "schedule",
        sendingHoursLabel: "Restrict Calling Hours",
        sendingHoursDescription: "Only make calls during specific hours",
        daysLabel: "Calling Days",
        renderRateLimiting: ({ formData, updateField }) => (
          <div className="space-y-4">
            <h4 className="font-medium">Rate Limiting</h4>
            <div className="space-y-2">
              <Label htmlFor="voice-calls-per-minute">Calls per Minute</Label>
              <Select
                value={String(formData.calls_per_minute)}
                onValueChange={(v) => updateField("calls_per_minute", parseInt(v))}
              >
                <SelectTrigger id="voice-calls-per-minute">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">1 / minute</SelectItem>
                  <SelectItem value="3">3 / minute</SelectItem>
                  <SelectItem value="5">5 / minute</SelectItem>
                  <SelectItem value="10">10 / minute</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                Lower rates are recommended to avoid overwhelming your agents
              </p>
            </div>
          </div>
        ),
      }),
      makeReviewStep<StepId, VoiceFormData>({
        id: "review",
        phoneNumbers,
        selectedContactIds,
        recipientsLabel: "contacts will receive calls",
        scheduleHoursLabel: "Calling hours",
        renderRateDescription: (formData) => <>{formData.calls_per_minute} calls/min</>,
        renderChannelCards: (formData) => {
          const selectedVoiceAgent = voiceAgents.find((a) => a.id === formData.voice_agent_id);
          const selectedFallbackAgent = textAgents.find(
            (a) => a.id === formData.sms_fallback_agent_id,
          );
          return (
            <>
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <Phone className="size-5" />
                    Voice Agent
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {selectedVoiceAgent && <Badge variant="default">{selectedVoiceAgent.name}</Badge>}
                  <div className="text-sm text-muted-foreground">
                    Machine detection: {formData.enable_machine_detection ? "Enabled" : "Disabled"}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Max call duration: {formData.max_call_duration_seconds / 60} minute(s)
                  </div>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <MessageSquare className="size-5" />
                    SMS Fallback
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {formData.sms_fallback_enabled ? (
                    <div className="space-y-2">
                      <Badge variant="secondary" className="bg-success/10 text-success">
                        {formData.sms_fallback_mode === "ai" ? "AI-Generated" : "Template"}
                      </Badge>
                      {formData.sms_fallback_mode === "ai" && selectedFallbackAgent && (
                        <p className="text-sm text-muted-foreground">
                          Using agent: {selectedFallbackAgent.name}
                        </p>
                      )}
                      {formData.sms_fallback_mode === "template" && (
                        <p className="text-sm text-muted-foreground line-clamp-2">
                          {formData.sms_fallback_template}
                        </p>
                      )}
                    </div>
                  ) : (
                    <p className="text-muted-foreground">SMS fallback is disabled</p>
                  )}
                </CardContent>
              </Card>
            </>
          );
        },
      }),
    ],
    [workspaceId, voiceAgents, textAgents, phoneNumbers, selectedContactIds],
  );

  const handleSubmit = async (formData: VoiceFormData) => {
    const request: CreateVoiceCampaignRequest = {
      name: formData.name,
      description: formData.description || undefined,
      from_phone_number: formData.from_phone_number,
      voice_agent_id: formData.voice_agent_id!,
      enable_machine_detection: formData.enable_machine_detection,
      max_call_duration_seconds: formData.max_call_duration_seconds,
      sms_fallback_enabled: formData.sms_fallback_enabled,
      sms_fallback_template:
        formData.sms_fallback_mode === "template" ? formData.sms_fallback_template : undefined,
      sms_fallback_use_ai: formData.sms_fallback_mode === "ai",
      sms_fallback_agent_id:
        formData.sms_fallback_mode === "ai" ? formData.sms_fallback_agent_id : undefined,
      ai_enabled: formData.ai_enabled,
      qualification_criteria: formData.qualification_criteria || undefined,
      ...mapScheduleToRequest(formData),
      calls_per_minute: formData.calls_per_minute,
    };
    await onSubmit(request, selectedContactIds);
  };

  return (
    <BaseCampaignWizard
      steps={steps}
      initialFormData={initialFormData}
      onSubmit={handleSubmit}
      isSubmitting={isSubmitting}
      onCancel={onCancel}
    />
  );
}
