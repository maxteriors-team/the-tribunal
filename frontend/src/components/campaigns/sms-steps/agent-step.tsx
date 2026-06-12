"use client";

import { Bot } from "lucide-react";
import { motion } from "motion/react";

import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type { Agent } from "@/types";

import { validateAgent } from "../_shared/validators";
import { AgentSelector } from "../agent-selector";
import type { WizardStep } from "../wizard-types";

export interface AgentStepFields {
  agent_id?: string;
  ai_enabled: boolean;
  qualification_criteria: string;
}

/**
 * SMS-specific "AI Agent" step: toggles AI responses and picks the text
 * agent + qualification criteria used to score replies.
 */
export function makeAgentStep<
  TStepId extends string,
  TFormData extends AgentStepFields,
>(opts: {
  id: TStepId;
  agents: Agent[];
}): WizardStep<TStepId, TFormData> {
  return {
    id: opts.id,
    label: "AI Agent",
    icon: Bot,
    validate: (data) => validateAgent(data),
    render: ({ formData, errors, updateField }) => {
      const setField = <K extends keyof AgentStepFields>(
        key: K,
        value: AgentStepFields[K],
      ) =>
        updateField(
          key as unknown as keyof TFormData,
          value as unknown as TFormData[keyof TFormData],
        );

      return (
        <div className="space-y-6">
          <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
            <div>
              <h4 className="font-medium">Enable AI Responses</h4>
              <p className="text-sm text-muted-foreground">
                Let AI handle conversations automatically
              </p>
            </div>
            <Switch
              checked={formData.ai_enabled}
              onCheckedChange={(v) => setField("ai_enabled", v)}
            />
          </div>

          {formData.ai_enabled && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="space-y-6"
            >
              <div className="space-y-2">
                <AgentSelector
                  agents={opts.agents}
                  selectedId={formData.agent_id}
                  onSelect={(id) => setField("agent_id", id)}
                  showTextAgentsOnly={true}
                />
                {errors.agent_id && (
                  <p className="text-sm text-destructive">{errors.agent_id}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="qualification-criteria">
                  Qualification Criteria (Optional)
                </Label>
                <Textarea
                  id="qualification-criteria"
                  placeholder="e.g., Interested in scheduling a demo, Has budget over $1000..."
                  value={formData.qualification_criteria}
                  onChange={(e) =>
                    setField("qualification_criteria", e.target.value)
                  }
                  rows={3}
                />
                <p className="text-xs text-muted-foreground">
                  The AI will mark contacts as qualified when they meet these
                  criteria
                </p>
              </div>
            </motion.div>
          )}
        </div>
      );
    },
  };
}
