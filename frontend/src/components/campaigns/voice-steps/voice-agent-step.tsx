"use client";

import { AlertCircle, Phone } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { Switch } from "@/components/ui/switch";
import type { Agent } from "@/types";

import { AgentSelector } from "../agent-selector";
import type { WizardStep } from "../wizard-types";

export interface VoiceAgentStepFields {
  voice_agent_id?: string;
  enable_machine_detection: boolean;
  max_call_duration_seconds: number;
}

/**
 * Voice-specific step: picks the AI voice agent and configures core call
 * behaviour (voicemail detection, max duration).
 */
export function makeVoiceAgentStep<
  TStepId extends string,
  TFormData extends VoiceAgentStepFields,
>(opts: { id: TStepId; voiceAgents: Agent[] }): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "Voice Agent",
    icon: Phone,
    validate: (data) => (!data.voice_agent_id ? { voice_agent_id: "Voice agent is required" } : {}),
    render: ({ formData, errors, updateField }) => {
      const setField = <K extends keyof VoiceAgentStepFields>(
        key: K,
        value: VoiceAgentStepFields[K],
      ) =>
        updateField(
          key as unknown as keyof TFormData,
          value as unknown as TFormData[keyof TFormData],
        );

      return (
        <div className="space-y-6">
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-sm text-muted-foreground mb-2">
              <Phone className="size-4" />
              <span>Select the AI agent that will handle voice calls</span>
            </div>

            {errors.voice_agent_id && (
              <Alert variant="destructive">
                <AlertCircle className="size-4" />
                <AlertDescription>{errors.voice_agent_id}</AlertDescription>
              </Alert>
            )}

            <AgentSelector
              agents={opts.voiceAgents}
              selectedId={formData.voice_agent_id}
              onSelect={(id) => setField("voice_agent_id", id)}
              showVoiceAgentsOnly={true}
              allowNone={false}
            />
          </div>

          <Separator />

          <div className="space-y-4">
            <h4 className="font-medium">Call Settings</h4>

            <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
              <div>
                <h5 className="font-medium">Machine Detection</h5>
                <p className="text-sm text-muted-foreground">
                  Detect voicemail and hang up automatically
                </p>
              </div>
              <Switch
                aria-label="Machine detection"
                checked={formData.enable_machine_detection}
                onCheckedChange={(v) => setField("enable_machine_detection", v)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="voice-max-call-duration">Max Call Duration</Label>
              <Select
                value={String(formData.max_call_duration_seconds)}
                onValueChange={(v) => setField("max_call_duration_seconds", parseInt(v))}
              >
                <SelectTrigger id="voice-max-call-duration">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="60">1 minute</SelectItem>
                  <SelectItem value="120">2 minutes</SelectItem>
                  <SelectItem value="180">3 minutes</SelectItem>
                  <SelectItem value="300">5 minutes</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>
      );
    },
  };
}
