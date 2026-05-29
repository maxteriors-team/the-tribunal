"use client";

import { Bot, MessageSquare, Tag } from "lucide-react";
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
import type { CreateSMSCampaignRequest } from "@/lib/api/sms-campaigns";
import type { Agent, Offer, PhoneNumber, SMSCampaign } from "@/types";

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
  type AgentStepFields,
  type MessageStepFields,
  makeAgentStep,
  makeMessageStep,
} from "./sms-steps";
import type { WizardStep } from "./wizard-types";



type StepId =
  | "basics"
  | "contacts"
  | "message"
  | "agent"
  | "schedule"
  | "review";

interface SMSCampaignWizardProps {
  workspaceId: string;
  agents: Agent[];
  offers: Offer[];
  phoneNumbers: PhoneNumber[];
  onSubmit: (
    data: CreateSMSCampaignRequest,
    contactIds: Set<number>
  ) => Promise<SMSCampaign>;
  onCreateOffer?: (offer: Partial<Offer>) => Promise<void>;
  onCancel?: () => void;
  isSubmitting?: boolean;
}

interface SMSFormData
  extends BasicsFields,
    ScheduleFields,
    MessageStepFields,
    AgentStepFields {
  messages_per_minute: number;
  max_messages_per_contact: number;
}

const initialFormData: SMSFormData = {
  ...initialBasicsFields,
  ...initialScheduleFields,
  initial_message: "",
  agent_id: undefined,
  offer_id: undefined,
  ai_enabled: true,
  qualification_criteria: "",
  messages_per_minute: 10,
  max_messages_per_contact: 3,
  follow_up_enabled: false,
  follow_up_delay_hours: 24,
  follow_up_message: "",
  max_follow_ups: 2,
};

export function SMSCampaignWizard({
  workspaceId,
  agents,
  offers,
  phoneNumbers,
  onSubmit,
  onCreateOffer,
  onCancel,
  isSubmitting = false,
}: SMSCampaignWizardProps) {
  const [selectedContactIds, setSelectedContactIds] = useState<Set<number>>(
    new Set()
  );

  const steps = useMemo<ReadonlyArray<WizardStep<StepId, SMSFormData>>>(
    () => [
      makeBasicsStep<StepId, SMSFormData>({
        id: "basics",
        phoneNumbers,
        namePlaceholder: "e.g., Summer Sale Outreach",
        emptyPhoneLabel: "No SMS or iMessage sender identities available",
      }),
      makeContactsStep<StepId, SMSFormData>({
        id: "contacts",
        workspaceId,
        selectedContactIds,
        setSelectedContactIds,
      }),
      makeMessageStep<StepId, SMSFormData>({
        id: "message",
        offers,
        onCreateOffer,
      }),
      makeAgentStep<StepId, SMSFormData>({
        id: "agent",
        agents,
      }),
      makeScheduleStep<StepId, SMSFormData>({
        id: "schedule",
        sendingHoursLabel: "Restrict Sending Hours",
        sendingHoursDescription: "Only send messages during specific hours",
        daysLabel: "Sending Days",
        renderRateLimiting: ({ formData, updateField }) => (
          <div className="space-y-4">
            <h4 className="font-medium">Rate Limiting</h4>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Messages per Minute</Label>
                <Select
                  value={String(formData.messages_per_minute)}
                  onValueChange={(v) =>
                    updateField("messages_per_minute", parseInt(v))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="5">5 / minute</SelectItem>
                    <SelectItem value="10">10 / minute</SelectItem>
                    <SelectItem value="20">20 / minute</SelectItem>
                    <SelectItem value="30">30 / minute</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>Max Messages per Contact</Label>
                <Select
                  value={String(formData.max_messages_per_contact)}
                  onValueChange={(v) =>
                    updateField("max_messages_per_contact", parseInt(v))
                  }
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1">1 message</SelectItem>
                    <SelectItem value="2">2 messages</SelectItem>
                    <SelectItem value="3">3 messages</SelectItem>
                    <SelectItem value="5">5 messages</SelectItem>
                    <SelectItem value="10">10 messages</SelectItem>
                    <SelectItem value="0">Unlimited</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        ),
      }),
      makeReviewStep<StepId, SMSFormData>({
        id: "review",
        phoneNumbers,
        selectedContactIds,
        recipientsLabel: "contacts selected",
        scheduleHoursLabel: "Sending hours",
        renderRateDescription: (formData) => (
          <>
            {formData.messages_per_minute} messages/min,{" "}
            {formData.max_messages_per_contact === 0
              ? "unlimited messages per contact"
              : `max ${formData.max_messages_per_contact} per contact`}
          </>
        ),
        renderChannelCards: (formData) => {
          const selectedOffer = offers.find((o) => o.id === formData.offer_id);
          const selectedAgent = agents.find((a) => a.id === formData.agent_id);
          return (
            <>
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg flex items-center gap-2">
                    <MessageSquare className="size-5" />
                    Message
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="p-4 bg-muted rounded-lg">
                    <p className="whitespace-pre-wrap">
                      {formData.initial_message}
                    </p>
                  </div>
                  {selectedOffer && (
                    <div className="flex items-center gap-2">
                      <Tag className="size-4 text-success" />
                      <span className="text-sm">Attached offer:</span>
                      <Badge
                        variant="secondary"
                        className="bg-success/10 text-success"
                      >
                        {selectedOffer.name}
                      </Badge>
                    </div>
                  )}
                  {formData.follow_up_enabled && (
                    <div className="text-sm text-muted-foreground">
                      Follow-up enabled: {formData.max_follow_ups} message(s)
                      after {formData.follow_up_delay_hours} hours
                    </div>
                  )}
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
                          <span className="text-sm text-muted-foreground">
                            will handle responses
                          </span>
                        </div>
                      ) : (
                        <p className="text-muted-foreground">
                          AI enabled but no agent selected
                        </p>
                      )}
                      {formData.qualification_criteria && (
                        <div className="mt-2">
                          <p className="text-sm text-muted-foreground">
                            Qualification criteria:
                          </p>
                          <p className="text-sm">
                            {formData.qualification_criteria}
                          </p>
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
            </>
          );
        },
      }),
    ],
    [
      workspaceId,
      agents,
      offers,
      phoneNumbers,
      onCreateOffer,
      selectedContactIds,
    ]
  );

  const handleSubmit = async (formData: SMSFormData) => {
    const request: CreateSMSCampaignRequest = {
      name: formData.name,
      description: formData.description || undefined,
      from_phone_number: formData.from_phone_number,
      initial_message: formData.initial_message,
      agent_id: formData.agent_id,
      offer_id: formData.offer_id,
      ai_enabled: formData.ai_enabled,
      qualification_criteria: formData.qualification_criteria || undefined,
      ...mapScheduleToRequest(formData),
      messages_per_minute: formData.messages_per_minute,
      max_messages_per_contact: formData.max_messages_per_contact,
      follow_up_enabled: formData.follow_up_enabled,
      follow_up_delay_hours: formData.follow_up_delay_hours,
      follow_up_message: formData.follow_up_message || undefined,
      max_follow_ups: formData.max_follow_ups,
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
