"use client";

import { useMutation } from "@tanstack/react-query";
import { FileText, Users, Bot, Eye, Send, Phone, AlertCircle, FlaskConical } from "lucide-react";
import { motion } from "motion/react";
import { useState, useCallback } from "react";

import { SegmentPicker } from "@/components/segments/segment-picker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { WizardContainer } from "@/components/wizard";
import { useWizard } from "@/hooks/useWizard";
import type { CreateMessageTestRequest } from "@/lib/api/message-tests";
import { segmentsApi } from "@/lib/api/segments";
import type { Contact, Agent, PhoneNumber, MessageTest } from "@/types";

import { AgentSelector } from "../campaigns/agent-selector";
import { ContactSelector } from "../campaigns/contact-selector";

import { VariantEditor, type VariantFormData } from "./variant-editor";

const STEPS = [
  { id: "basics", label: "Basics", icon: FileText },
  { id: "contacts", label: "Contacts", icon: Users },
  { id: "variants", label: "Variants", icon: FlaskConical },
  { id: "agent", label: "AI Agent", icon: Bot },
  { id: "review", label: "Review", icon: Eye },
] as const;

type StepId = (typeof STEPS)[number]["id"];

interface MessageTestWizardProps {
  workspaceId?: string;
  contacts: Contact[];
  agents: Agent[];
  phoneNumbers: PhoneNumber[];
  onSubmit: (data: CreateMessageTestRequest, contactIds: number[]) => Promise<MessageTest>;
  onCancel?: () => void;
  isSubmitting?: boolean;
}

interface FormData {
  name: string;
  description: string;
  from_phone_number: string;
  use_number_pool: boolean;
  agent_id?: string;
  ai_enabled: boolean;
  qualification_criteria: string;
  sending_hours_start: string;
  sending_hours_end: string;
  sending_days: number[];
  timezone: string;
  messages_per_minute: number;
}

const initialFormData: FormData = {
  name: "",
  description: "",
  from_phone_number: "",
  use_number_pool: false,
  agent_id: undefined,
  ai_enabled: true,
  qualification_criteria: "",
  sending_hours_start: "09:00",
  sending_hours_end: "17:00",
  sending_days: [1, 2, 3, 4, 5],
  timezone: "America/New_York",
  messages_per_minute: 10,
};

export function MessageTestWizard({
  workspaceId,
  contacts,
  agents,
  phoneNumbers,
  onSubmit,
  onCancel,
  isSubmitting = false,
}: MessageTestWizardProps) {
  const [selectedContactIds, setSelectedContactIds] = useState<number[]>([]);
  const [selectedSegmentId, setSelectedSegmentId] = useState<string | null>(null);
  const [variants, setVariants] = useState<VariantFormData[]>([]);

  // Resolve segment contacts when a segment is selected
  const segmentMutation = useMutation({
    mutationFn: async (segmentId: string) => {
      if (!workspaceId) throw new Error("Workspace not loaded");
      return segmentsApi.getContacts(workspaceId, segmentId);
    },
    onSuccess: (data) => {
      const contactIdSet = new Set(contacts.map((c) => c.id));
      const matching = data.ids.filter((id) => contactIdSet.has(id));
      setSelectedContactIds(matching);
    },
  });

  const handleSegmentSelect = (segmentId: string | null) => {
    setSelectedSegmentId(segmentId);
    if (segmentId) {
      segmentMutation.mutate(segmentId);
    }
  };

  const validateStep = useCallback(
    (
      step: StepId,
      data: FormData,
      setErrors: React.Dispatch<React.SetStateAction<Record<string, string>>>,
    ) => {
      const newErrors: Record<string, string> = {};

      switch (step) {
        case "basics":
          if (!data.name.trim()) newErrors.name = "Experiment name is required";
          if (!data.from_phone_number) newErrors.from_phone_number = "Phone number is required";
          break;
        case "contacts":
          if (selectedContactIds.length === 0) newErrors.contacts = "Select at least one contact";
          break;
        case "variants":
          if (variants.length < 2)
            newErrors.variants = "You need at least 2 variants for an A/B test";
          if (variants.some((v) => !v.message_template.trim()))
            newErrors.variants = "All variants must have a message";
          break;
      }

      setErrors(newErrors);
      return Object.keys(newErrors).length === 0;
    },
    [selectedContactIds, variants],
  );

  const wizard = useWizard<StepId, FormData>({
    steps: STEPS,
    initialFormData,
    validateStep,
  });

  const { formData, errors, updateField } = wizard;

  const handleSubmit = async () => {
    if (!wizard.validateAllSteps()) return;

    const request: CreateMessageTestRequest = {
      name: formData.name,
      description: formData.description || undefined,
      from_phone_number: formData.from_phone_number,
      use_number_pool: formData.use_number_pool,
      agent_id: formData.agent_id,
      ai_enabled: formData.ai_enabled,
      qualification_criteria: formData.qualification_criteria || undefined,
      sending_hours_start: formData.sending_hours_start,
      sending_hours_end: formData.sending_hours_end,
      sending_days: formData.sending_days,
      timezone: formData.timezone,
      messages_per_minute: formData.messages_per_minute,
      variants: variants.map((v) => ({
        name: v.name,
        message_template: v.message_template,
        is_control: v.is_control,
        sort_order: v.sort_order,
      })),
    };

    await onSubmit(request, selectedContactIds);
  };

  const selectedAgent = agents.find((a) => a.id === formData.agent_id);
  const selectedPhone = phoneNumbers.find((p) => p.phone_number === formData.from_phone_number);

  const renderStepContent = () => {
    switch (wizard.currentStepId) {
      case "basics":
        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <Label htmlFor="test-name">Experiment Name *</Label>
              <Input
                id="test-name"
                placeholder="e.g., Intro Message Test - Q1"
                value={formData.name}
                onChange={(e) => updateField("name", e.target.value)}
                className={errors.name ? "border-destructive" : ""}
              />
              {errors.name && <p className="text-sm text-destructive">{errors.name}</p>}
            </div>

            <div className="space-y-2">
              <Label htmlFor="test-description">Description</Label>
              <Textarea
                id="test-description"
                placeholder="What are you testing? What hypothesis are you trying to validate?"
                value={formData.description}
                onChange={(e) => updateField("description", e.target.value)}
                rows={3}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="experiment-phone-number">From Phone Number *</Label>
              <Select
                value={formData.from_phone_number}
                onValueChange={(v) => updateField("from_phone_number", v)}
              >
                <SelectTrigger
                  id="experiment-phone-number"
                  className={errors.from_phone_number ? "border-destructive" : ""}
                >
                  <SelectValue placeholder="Select a phone number" />
                </SelectTrigger>
                <SelectContent>
                  {phoneNumbers.map((phone) => (
                    <SelectItem key={phone.id} value={phone.phone_number}>
                      <div className="flex items-center gap-2">
                        <Phone className="size-4" />
                        <span>{phone.phone_number}</span>
                        {phone.friendly_name && (
                          <span className="text-muted-foreground">({phone.friendly_name})</span>
                        )}
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {errors.from_phone_number && (
                <p className="text-sm text-destructive">{errors.from_phone_number}</p>
              )}
            </div>
          </div>
        );

      case "contacts":
        return (
          <div className="space-y-4">
            {errors.contacts && (
              <Alert variant="destructive">
                <AlertCircle className="size-4" />
                <AlertDescription>{errors.contacts}</AlertDescription>
              </Alert>
            )}
            {workspaceId && (
              <SegmentPicker
                workspaceId={workspaceId}
                selectedSegmentId={selectedSegmentId}
                onSegmentSelect={handleSegmentSelect}
              />
            )}
            <ContactSelector
              contacts={contacts}
              selectedIds={selectedContactIds}
              onSelectionChange={setSelectedContactIds}
            />
          </div>
        );

      case "variants":
        return (
          <div className="space-y-4">
            <div className="mb-4">
              <h3 className="text-lg font-medium">Message Variants</h3>
              <p className="text-sm text-muted-foreground">
                Create at least 2 different message variants. Contacts will be randomly assigned to
                each variant using round-robin distribution.
              </p>
            </div>
            <VariantEditor variants={variants} onChange={setVariants} error={errors.variants} />
          </div>
        );

      case "agent":
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
                aria-label="AI responses"
                checked={formData.ai_enabled}
                onCheckedChange={(v) => updateField("ai_enabled", v)}
              />
            </div>

            {formData.ai_enabled && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
                <AgentSelector
                  agents={agents}
                  selectedId={formData.agent_id}
                  onSelect={(id) => updateField("agent_id", id)}
                  showTextAgentsOnly={true}
                />

                <div className="space-y-2">
                  <Label htmlFor="qualification-criteria">Qualification Criteria (Optional)</Label>
                  <Textarea
                    id="qualification-criteria"
                    placeholder="e.g., Interested in scheduling a demo, Has budget over $1000..."
                    value={formData.qualification_criteria}
                    onChange={(e) => updateField("qualification_criteria", e.target.value)}
                    rows={3}
                  />
                  <p className="text-xs text-muted-foreground">
                    The AI will mark contacts as qualified when they meet these criteria
                  </p>
                </div>
              </motion.div>
            )}
          </div>
        );

      case "review":
        return (
          <div className="space-y-6">
            <Card>
              <CardHeader>
                <CardTitle className="text-lg">Experiment Summary</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Name</p>
                    <p className="font-medium">{formData.name}</p>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">From</p>
                    <p className="font-medium">
                      {selectedPhone?.friendly_name || formData.from_phone_number}
                    </p>
                  </div>
                </div>
                {formData.description && (
                  <div>
                    <p className="text-sm text-muted-foreground">Description</p>
                    <p className="font-medium">{formData.description}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Users className="size-5" />
                  Recipients
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-lg px-3 py-1">
                    {selectedContactIds.length}
                  </Badge>
                  <span className="text-muted-foreground">contacts selected</span>
                </div>
                <p className="text-sm text-muted-foreground mt-2">
                  Each contact will receive ONE message from ONE randomly assigned variant
                </p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <FlaskConical className="size-5" />
                  Variants ({variants.length})
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {variants.map((variant, index) => (
                  <div key={variant.id} className="p-3 bg-muted/50 rounded-lg">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge variant="outline">{String.fromCharCode(65 + index)}</Badge>
                      <span className="font-medium">{variant.name}</span>
                      {variant.is_control && (
                        <Badge variant="secondary" className="text-xs">
                          Control
                        </Badge>
                      )}
                    </div>
                    <p className="text-sm whitespace-pre-wrap">{variant.message_template}</p>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-lg flex items-center gap-2">
                  <Bot className="size-5" />
                  AI Configuration
                </CardTitle>
              </CardHeader>
              <CardContent>
                {formData.ai_enabled ? (
                  <div className="space-y-2">
                    {selectedAgent ? (
                      <div className="flex items-center gap-2">
                        <Badge variant="default">{selectedAgent.name}</Badge>
                        <span className="text-sm text-muted-foreground">will handle responses</span>
                      </div>
                    ) : (
                      <p className="text-muted-foreground">AI enabled but no agent selected</p>
                    )}
                    {formData.qualification_criteria && (
                      <div className="mt-2">
                        <p className="text-sm text-muted-foreground">Qualification criteria:</p>
                        <p className="text-sm">{formData.qualification_criteria}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="text-muted-foreground">
                    AI responses disabled - manual responses only
                  </p>
                )}
              </CardContent>
            </Card>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <WizardContainer
      steps={STEPS}
      currentStepId={wizard.currentStepId}
      currentStepIndex={wizard.currentStepIndex}
      onStepClick={wizard.goToStep}
      isFirstStep={wizard.isFirstStep}
      isLastStep={wizard.isLastStep}
      onPrevious={wizard.goPrevious}
      onNext={wizard.goNext}
      onSubmit={handleSubmit}
      isSubmitting={isSubmitting}
      onCancel={onCancel}
      submitLabel="Create Experiment"
      submitIcon={Send}
    >
      {renderStepContent()}
    </WizardContainer>
  );
}
