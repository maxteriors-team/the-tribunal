"use client";

import { MessageSquare, Bot, Sparkles, FileText } from "lucide-react";
import { motion } from "motion/react";

import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { insertPlaceholderAtCursor } from "@/lib/utils/placeholder";
import type { Agent } from "@/types";

import { AgentSelector } from "./agent-selector";

export type SMSFallbackMode = "template" | "ai";

interface SMSFallbackStepProps {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  mode: SMSFallbackMode;
  onModeChange: (mode: SMSFallbackMode) => void;
  template: string;
  onTemplateChange: (template: string) => void;
  agentId?: string;
  onAgentChange: (agentId: string | undefined) => void;
  agents: Agent[];
  errors?: Record<string, string>;
}

export function SMSFallbackStep({
  enabled,
  onEnabledChange,
  mode,
  onModeChange,
  template,
  onTemplateChange,
  agentId,
  onAgentChange,
  agents,
  errors,
}: SMSFallbackStepProps) {
  const insertPlaceholder = (placeholder: string) => {
    insertPlaceholderAtCursor("fallback-template", placeholder, template, onTemplateChange);
  };

  return (
    <div className="space-y-6">
      {/* Enable/Disable Toggle */}
      <div className="flex items-center justify-between p-4 bg-muted/50 rounded-lg">
        <div className="flex items-center gap-3">
          <MessageSquare className="size-5 text-primary" />
          <div>
            <h4 className="font-medium">SMS Fallback</h4>
            <p className="text-sm text-muted-foreground">Automatically send SMS when calls fail</p>
          </div>
        </div>
        <Switch aria-label="SMS fallback" checked={enabled} onCheckedChange={onEnabledChange} />
      </div>

      {enabled && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          className="space-y-6"
        >
          {/* Fallback Mode Selection */}
          <div className="space-y-4">
            <Label>Fallback Message Type</Label>
            <RadioGroup
              value={mode}
              onValueChange={(v) => onModeChange(v as SMSFallbackMode)}
              className="grid grid-cols-2 gap-4"
            >
              <label
                htmlFor="mode-template"
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  mode === "template"
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <RadioGroupItem value="template" id="mode-template" />
                <div className="flex-1">
                  <div className="flex items-center gap-2 font-medium">
                    <FileText className="size-4" />
                    Template
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">
                    Use a pre-written message template with placeholders
                  </p>
                </div>
              </label>

              <label
                htmlFor="mode-ai"
                className={`flex items-start gap-3 p-4 rounded-lg border-2 cursor-pointer transition-colors ${
                  mode === "ai"
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/50"
                }`}
              >
                <RadioGroupItem value="ai" id="mode-ai" />
                <div className="flex-1">
                  <div className="flex items-center gap-2 font-medium">
                    <Sparkles className="size-4" />
                    AI-Generated
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">
                    Let AI create personalized messages based on context
                  </p>
                </div>
              </label>
            </RadioGroup>
          </div>

          {/* Template Input */}
          {mode === "template" && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label htmlFor="fallback-template">SMS Template</Label>
                  <div className="flex items-center gap-1">
                    <span className="text-xs text-muted-foreground mr-2">Insert:</span>
                    {[
                      { label: "First Name", value: "{first_name}" },
                      { label: "Company", value: "{company_name}" },
                      { label: "Call Reason", value: "{call_reason}" },
                    ].map((p) => (
                      <button
                        key={p.value}
                        type="button"
                        className="text-xs px-2 py-1 rounded border hover:bg-muted transition-colors"
                        onClick={() => insertPlaceholder(p.value)}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>
                </div>
                <Textarea
                  id="fallback-template"
                  placeholder="Hi {first_name}, {call_reason} - reply to this message or call us back at your convenience."
                  value={template}
                  onChange={(e) => onTemplateChange(e.target.value)}
                  rows={4}
                  className={errors?.template ? "border-destructive" : ""}
                />
                {errors?.template && <p className="text-sm text-destructive">{errors.template}</p>}
                <p className="text-xs text-muted-foreground">
                  {template.length}/160 characters (standard SMS)
                </p>
              </div>

              <div className="p-3 bg-info/10 rounded-lg text-sm">
                <p className="font-medium text-info mb-1">Available Placeholders:</p>
                <ul className="text-info text-xs space-y-1">
                  <li>
                    <code>{"{first_name}"}</code> - Contact&apos;s first name
                  </li>
                  <li>
                    <code>{"{last_name}"}</code> - Contact&apos;s last name
                  </li>
                  <li>
                    <code>{"{company_name}"}</code> - Contact&apos;s company
                  </li>
                  <li>
                    <code>{"{call_reason}"}</code> - Why the call failed (e.g., &quot;we tried
                    calling but couldn&apos;t reach you&quot;)
                  </li>
                </ul>
              </div>
            </motion.div>
          )}

          {/* AI Agent Selection */}
          {mode === "ai" && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
              <div className="p-3 bg-primary/10 rounded-lg text-sm">
                <p className="flex items-center gap-2 font-medium text-primary mb-1">
                  <Bot className="size-4" />
                  AI Message Generation
                </p>
                <p className="text-primary text-xs">
                  The AI will generate a personalized SMS based on the contact&apos;s information,
                  why the call failed, and the agent&apos;s personality. Messages are optimized for
                  SMS length.
                </p>
              </div>

              <div className="space-y-2">
                <Label>Select AI Agent for SMS Generation</Label>
                <AgentSelector
                  agents={agents}
                  selectedId={agentId}
                  onSelect={onAgentChange}
                  showTextAgentsOnly={true}
                  allowNone={false}
                />
                {errors?.agentId && <p className="text-sm text-destructive">{errors.agentId}</p>}
              </div>
            </motion.div>
          )}
        </motion.div>
      )}
    </div>
  );
}
